import json

import pytest

from byte_mcp.errors import OXApprovalError, OXProtocolError, OXTransportError
from byte_mcp.ox.models import ProviderResult, ProviderUsage
from tests.ox.helpers import commit_files
from tests.ox.test_review_service import RecordingClient, make_service, prepare, verification


class TextClient(RecordingClient):
    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        if json_mode:
            return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "json_mode": json_mode,
                "attempt_id": attempt_id,
            }
        )
        raw = {
            "id": f"response-{attempt_id}",
            "model": "zai/glm-5.3-flash",
            "choices": [{"message": {"role": "assistant", "content": "Acknowledged."}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        return ProviderResult(
            "Acknowledged.",
            ProviderUsage(5, 2, 7, 0),
            response_id=raw["id"],
            model=raw["model"],
            raw_response=raw,
        )


class UnknownContinuationClient(TextClient):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        if not json_mode and self.fail_once:
            self.fail_once = False
            self.calls.append(
                {
                    "messages": [dict(message) for message in messages],
                    "json_mode": json_mode,
                    "attempt_id": attempt_id,
                }
            )
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)


def _establish_review(service, base: str, target: str) -> str:
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])
    return proposal["review_id"]


def test_continue_message_replays_approved_history_and_adds_one_turn(tmp_path) -> None:
    client = TextClient()
    service, _, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    initial_calls = len(client.calls)

    result = service.continue_message(review_id, "Explain the evidence for F001.")

    assert len(client.calls) == initial_calls + 1
    call = client.calls[-1]
    assert call["json_mode"] is False
    assert [message["role"] for message in call["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert call["messages"][-1] == {
        "role": "user",
        "content": "Explain the evidence for F001.",
    }
    assert result["response"] == "Acknowledged."


def test_ambiguous_continuation_retry_replays_exact_attempted_turn(tmp_path) -> None:
    client = UnknownContinuationClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)

    with pytest.raises(OXTransportError):
        service.continue_message(review_id, "Please test the disproof condition.")
    failed_call = client.calls[-1]
    failed_attempt = failed_call["attempt_id"]
    thread = service.get_review(review_id, view="thread")["messages"]
    assert thread[-1] == {"role": "user", "content": "Please test the disproof condition."}

    with pytest.raises(OXApprovalError):
        service.retry_continuation(review_id, failed_attempt, renewed_approval=False)

    result = service.retry_continuation(review_id, failed_attempt, renewed_approval=True)

    assert client.calls[-1]["messages"] == failed_call["messages"]
    assert result["response"] == "Acknowledged."
    assert store.get_review(review_id)["attempts"][-1]["outcome"] == "COMPLETED"


def test_adjudication_is_local_append_only_and_validates_finding_transitions(tmp_path) -> None:
    client = RecordingClient()
    service, _, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    calls_before = len(client.calls)

    result = service.adjudicate(
        review_id,
        [
            {
                "finding_id": f"{review_id}-F001",
                "status": "CONFIRMED",
                "evidence": "Reproduced against committed evidence.",
                "reasoning_summary": "The claim matches the persisted diff.",
            }
        ],
    )

    assert len(client.calls) == calls_before
    assert result["adjudications"][-1]["status"] == "CONFIRMED"
    with pytest.raises(OXProtocolError):
        service.adjudicate(
            review_id,
            [
                {
                    "finding_id": f"{review_id}-F999",
                    "status": "CONFIRMED",
                    "evidence": "none",
                    "reasoning_summary": "unknown finding",
                }
            ],
        )
    with pytest.raises(OXProtocolError):
        service.adjudicate(
            review_id,
            [
                {
                    "finding_id": f"{review_id}-F001",
                    "status": "RAISED",
                    "evidence": "none",
                    "reasoning_summary": "backwards transition",
                }
            ],
        )


def test_blind_revalidation_is_fresh_and_targeted_waits_for_blind_success(tmp_path) -> None:
    client = RecordingClient()
    service, _, repository_path, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    service.adjudicate(
        review_id,
        [
            {
                "finding_id": f"{review_id}-F001",
                "status": "CONFIRMED",
                "evidence": "Confirmed from the first review.",
                "reasoning_summary": "Needs remediation.",
            }
        ],
    )
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    calls_before = len(client.calls)

    proposal = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )

    assert len(client.calls) == calls_before
    assert proposal["revalidation_id"] == f"{review_id}-RV001"
    assert proposal["transmitted"] is False
    with pytest.raises(OXApprovalError):
        service.run_targeted_revalidation(
            proposal["revalidation_id"], [f"{review_id}-F001"]
        )

    blind = service.transmit_blind_revalidation(proposal["revalidation_id"])
    blind_call = client.calls[-1]
    serialized = json.dumps(blind_call["messages"])
    assert blind["state"] == "BLIND_REVALIDATED"
    assert "Confirmed from the first review." not in serialized
    assert "Needs remediation." not in serialized
    assert f"{review_id}-F001" not in serialized

    targeted = service.run_targeted_revalidation(
        proposal["revalidation_id"], [f"{review_id}-F001"]
    )
    targeted_payload = json.dumps(client.calls[-1]["messages"])
    assert targeted["state"] == "REVALIDATED"
    assert f"{review_id}-F001" in targeted_payload
    assert "Confirmed from the first review." in targeted_payload


def test_revalidation_retry_requires_renewed_approval_and_keeps_scope_fixed(tmp_path) -> None:
    client = RecordingClient()
    service, _, repository_path, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    proposal = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )

    original_complete = client.complete
    calls = 0

    def fail_once(messages, *, json_mode: bool, attempt_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        return original_complete(messages, json_mode=json_mode, attempt_id=attempt_id)

    client.complete = fail_once
    with pytest.raises(OXTransportError):
        service.transmit_blind_revalidation(proposal["revalidation_id"])
    with pytest.raises(OXApprovalError):
        service.retry_revalidation(proposal["revalidation_id"], renewed_approval=False)

    result = service.retry_revalidation(proposal["revalidation_id"], renewed_approval=True)

    assert result["state"] == "BLIND_REVALIDATED"
