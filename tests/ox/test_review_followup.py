import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from byte_mcp.errors import (
    OXApprovalError,
    OXEvidenceError,
    OXFindingValidationError,
    OXProtocolError,
    OXTransportError,
    OXUnavailableError,
)
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.jobs import OXLaneLease, OXOperationKey
from byte_mcp.ox.models import AttemptOutcome, ProviderResult, ProviderUsage, ReviewState
from byte_mcp.ox.service import _history_sha256
from tests.ox import q03h_revalidation_support as q03hr
from tests.ox.helpers import commit_files
from tests.ox.q03h_initial_support import wait_for_lane_release, wait_for_state
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


class MalformedBlindClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.request_count = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.request_count += 1
        if self.request_count == 2:
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
                "choices": [{"message": {"role": "assistant", "content": "not-json"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            return ProviderResult(
                content="not-json",
                usage=ProviderUsage(1, 1, 2, 0),
                response_id=raw["id"],
                model=raw["model"],
                raw_response=raw,
            )
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)


class UnknownTargetedClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.request_count = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.request_count += 1
        if self.request_count == 3:
            self.calls.append(
                {
                    "messages": [dict(message) for message in messages],
                    "json_mode": json_mode,
                    "attempt_id": attempt_id,
                }
            )
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)


class BlockingContinuationClient(TextClient):
    def __init__(self, order: list[str] | None = None) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.order = order

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
        if self.order is not None:
            self.order.append("client.complete")
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("blocked continuation fixture was not released")
        raw = {
            "id": f"response-{attempt_id}",
            "model": "zai/glm-5.3-flash",
            "choices": [{"message": {"role": "assistant", "content": "Continued."}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        return ProviderResult(
            "Continued.",
            ProviderUsage(5, 2, 7, 0),
            response_id=raw["id"],
            model=raw["model"],
            raw_response=raw,
        )


class OrderedContinuationStore(EvidenceStore):
    def __init__(self, root, order: list[str]) -> None:
        super().__init__(root)
        self.order = order
        self.record_continuation = False

    def record_provider_request_started(self, *args, **kwargs) -> None:
        if self.record_continuation:
            self.order.append("provider-start")
        super().record_provider_request_started(*args, **kwargs)

    def persist_provider_response(self, *args, **kwargs) -> None:
        if self.record_continuation:
            self.order.append("raw-response")
        super().persist_provider_response(*args, **kwargs)

    def append_thread_message(self, review_id, thread_name, message) -> None:
        if self.record_continuation and message.get("role") == "assistant":
            self.order.append("assistant-thread")
        super().append_thread_message(review_id, thread_name, message)

    def record_attempt_outcome(self, review_id, attempt_id, outcome) -> None:
        if self.record_continuation:
            value = outcome.value if isinstance(outcome, AttemptOutcome) else outcome
            self.order.append(f"outcome:{value}")
        super().record_attempt_outcome(review_id, attempt_id, outcome)


def _establish_review(service, base: str, target: str) -> str:
    proposal = prepare(service, base, target)
    launch = service.transmit_review(proposal["review_id"])
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(service._evidence, proposal["review_id"], ReviewState.REVIEWED)
    return proposal["review_id"]


def test_continue_message_replays_approved_history_and_adds_one_turn(tmp_path) -> None:
    client = TextClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    initial_calls = len(client.calls)

    launch = service.continue_message(review_id, "Explain the evidence for F001.")
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)

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
    thread = service.get_review(review_id, view="thread")["messages"]
    assert thread[-1] == {"role": "assistant", "content": "Acknowledged."}


def test_ambiguous_continuation_retry_replays_exact_attempted_turn(tmp_path) -> None:
    client = UnknownContinuationClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)

    launch = service.continue_message(review_id, "Please test the disproof condition.")
    wait_for_state(store, review_id, ReviewState.OUTCOME_UNKNOWN)
    wait_for_lane_release(service._jobs)
    failed_call = client.calls[-1]
    failed_attempt = launch["attempt_id"]
    assert failed_call["attempt_id"] == failed_attempt
    thread = service.get_review(review_id, view="thread")["messages"]
    assert thread[-1] == {"role": "user", "content": "Please test the disproof condition."}

    with pytest.raises(OXApprovalError):
        service.retry_continuation(review_id, failed_attempt, renewed_approval=False)

    retry = service.retry_continuation(review_id, failed_attempt, renewed_approval=True)
    assert retry["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)

    assert client.calls[-1]["messages"] == failed_call["messages"]
    final_thread = service.get_review(review_id, view="thread")["messages"]
    assert final_thread[-1] == {"role": "assistant", "content": "Acknowledged."}
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


def test_targeted_retry_rejects_history_changed_since_failed_attempt(tmp_path) -> None:
    client = UnknownTargetedClient()
    service, store, repository_path, base, target, _ = make_service(tmp_path, client)
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
    proposal = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )
    service.transmit_blind_revalidation(proposal["revalidation_id"])

    with pytest.raises(OXTransportError):
        service.run_targeted_revalidation(
            proposal["revalidation_id"], [f"{review_id}-F001"]
        )
    calls_before_retry = len(client.calls)
    store.append_revalidation_thread_message(
        proposal["revalidation_id"],
        "targeted-revalidation",
        {"role": "user", "content": "tampered local history"},
    )

    with pytest.raises(OXApprovalError):
        service.retry_revalidation(proposal["revalidation_id"], renewed_approval=True)

    assert len(client.calls) == calls_before_retry


def test_targeted_revalidation_blocked_after_malformed_blind_findings(tmp_path) -> None:
    client = MalformedBlindClient()
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

    with pytest.raises(OXFindingValidationError):
        service.transmit_blind_revalidation(proposal["revalidation_id"])
    calls_before_targeted = len(client.calls)

    with pytest.raises(OXApprovalError):
        service.run_targeted_revalidation(
            proposal["revalidation_id"], [f"{review_id}-F001"]
        )

    assert len(client.calls) == calls_before_targeted


def test_q03h_ac13_continuation_launch_preserves_history_and_natural_response(
    tmp_path,
) -> None:
    order: list[str] = []
    client = BlockingContinuationClient(order)
    store = OrderedContinuationStore(tmp_path / "evidence", order)
    service, _, _, base, target, _ = make_service(tmp_path, client, evidence=store)
    review_id = _establish_review(service, base, target)
    store.record_continuation = True
    calls_before = len(client.calls)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.continue_message,
            review_id,
            "Explain the evidence for F001.",
        )
        assert client.entered.wait(timeout=5)
        try:
            receipt = future.result(timeout=0.25)
        except TimeoutError:
            client.release.set()
            future.result(timeout=5)
            raise

    assert receipt["review_id"] == review_id
    assert receipt["attempt_id"] == f"{review_id}-A002"
    assert receipt["state"] == ReviewState.TRANSMITTING.value
    assert receipt["launch_accepted"] is True
    assert receipt["replayed"] is False
    assert receipt["provider_request_performed"] is False
    assert len(client.calls) == calls_before + 1
    assert client.calls[-1]["json_mode"] is False

    thread = service.get_review(review_id, view="thread")["messages"]
    assert thread[-1] == {
        "role": "user",
        "content": "Explain the evidence for F001.",
    }
    assert sum(
        message == {
            "role": "user",
            "content": "Explain the evidence for F001.",
        }
        for message in thread
    ) == 1
    identity = store.read_attempt_identity(review_id, receipt["attempt_id"])
    assert identity["history_sha256"] == _history_sha256(client.calls[-1]["messages"])

    replay = service.continue_message(review_id, "Explain the evidence for F001.")
    assert replay["attempt_id"] == receipt["attempt_id"]
    assert replay["launch_accepted"] is False
    assert replay["replayed"] is True
    assert len(client.calls) == calls_before + 1

    client.release.set()
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)
    final_thread = service.get_review(review_id, view="thread")["messages"]
    assert final_thread[-1] == {"role": "assistant", "content": "Continued."}
    assert order.index("provider-start") < order.index("client.complete")
    assert order.index("client.complete") < order.index("raw-response")
    assert order.index("raw-response") < order.index("assistant-thread")
    assert order.index("assistant-thread") < order.index("outcome:COMPLETED")


def test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval(
    tmp_path,
) -> None:
    client = UnknownContinuationClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)
    calls_before = len(client.calls)

    first = service.continue_message(review_id, "Please test the disproof condition.")
    assert first["attempt_id"] == f"{review_id}-A002"
    assert first["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, review_id, ReviewState.OUTCOME_UNKNOWN)
    wait_for_lane_release(service._jobs)
    assert len(client.calls) == calls_before + 1

    with pytest.raises(OXApprovalError):
        service.retry_continuation(
            review_id,
            first["attempt_id"],
            renewed_approval=False,
        )
    with pytest.raises(OXApprovalError):
        service.retry_continuation(
            review_id,
            f"{review_id}-A001",
            renewed_approval=True,
        )
    assert len(client.calls) == calls_before + 1
    assert len(store.get_review(review_id)["attempts"]) == 2

    retry = service.retry_continuation(
        review_id,
        first["attempt_id"],
        renewed_approval=True,
    )
    assert retry["attempt_id"] == f"{review_id}-A003"
    assert retry["state"] == ReviewState.TRANSMITTING.value
    assert retry["launch_accepted"] is True
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)

    assert len(client.calls) == calls_before + 2
    assert client.calls[-1]["json_mode"] is False
    attempts = store.get_review(review_id)["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        f"{review_id}-A001",
        f"{review_id}-A002",
        f"{review_id}-A003",
    ]
    assert all(
        attempt["runtime_session_id"] == service._jobs.runtime_session_id
        for attempt in attempts
    )


@pytest.mark.parametrize("path", ["continuation", "retry"])
def test_continuation_preacceptance_failures_do_not_leak_or_unsafely_reopen_lane(
    tmp_path,
    monkeypatch,
    path: str,
) -> None:
    client = UnknownContinuationClient() if path == "retry" else TextClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)

    retry_of: str | None = None
    if path == "retry":
        launch = service.continue_message(review_id, "Create one failed continuation.")
        wait_for_state(store, review_id, ReviewState.OUTCOME_UNKNOWN)
        wait_for_lane_release(service._jobs)
        retry_of = launch["attempt_id"]

    calls_before = len(client.calls)

    def fail_identity(*_args, **_kwargs) -> None:
        raise OXEvidenceError("synthetic continuation identity failure")

    monkeypatch.setattr(service, "_persist_attempt_identity", fail_identity)

    with pytest.raises(OXEvidenceError, match="synthetic continuation identity failure"):
        if path == "continuation":
            service.continue_message(review_id, "This launch must not escape.")
        else:
            assert retry_of is not None
            service.retry_continuation(
                review_id,
                retry_of,
                renewed_approval=True,
            )

    failed = store.get_review(review_id)["attempts"][-1]
    assert failed["outcome"] == AttemptOutcome.NOT_SENT.value
    assert "provider_started_at" not in failed
    assert len(client.calls) == calls_before
    key = OXOperationKey(
        operation="continuation-probe",
        subject_id=review_id,
        input_sha256="a" * 64,
    )
    lease = service._jobs.reserve(key)
    assert isinstance(lease, OXLaneLease)
    service._jobs.abandon(lease)


def test_continuation_terminalization_failure_faults_lane_closed(
    tmp_path,
    monkeypatch,
) -> None:
    client = TextClient()
    service, _, _, base, target, _ = make_service(tmp_path, client)
    review_id = _establish_review(service, base, target)

    def fail_identity(*_args, **_kwargs) -> None:
        raise OXEvidenceError("synthetic continuation identity failure")

    def fail_terminal(*_args, **_kwargs) -> None:
        raise OXEvidenceError("synthetic continuation terminal failure")

    monkeypatch.setattr(service, "_persist_attempt_identity", fail_identity)
    monkeypatch.setattr(service._evidence, "record_attempt_outcome", fail_terminal)

    with pytest.raises(OXEvidenceError):
        service.continue_message(review_id, "This launch must fault closed.")

    key = OXOperationKey(
        operation="continuation-probe",
        subject_id=review_id,
        input_sha256="b" * 64,
    )
    with pytest.raises(OXUnavailableError):
        service._jobs.reserve(key)


def test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries(
    tmp_path,
) -> None:
    client = q03hr.RevalidationNaturalClient()
    service, store, jobs, repository_path, base, target = q03hr.make_revalidation_service(
        tmp_path,
        client,
    )
    review_id = q03hr.establish_initial_review(service, store, jobs, base, target)
    revalidation_id = q03hr.prepare_revalidation(
        service,
        repository_path,
        review_id,
        target,
    )
    calls_before = len(client.calls)
    client.fail_next = True

    first = service.transmit_blind_revalidation(revalidation_id)
    assert first["state"] == ReviewState.TRANSMITTING.value
    q03hr.wait_for_revalidation_state(store, revalidation_id, ReviewState.OUTCOME_UNKNOWN)
    q03hr.wait_for_lane_release(jobs)
    assert len(client.calls) == calls_before + 1
    first_attempt = first["attempt_id"]
    attempts = store.get_revalidation(revalidation_id)["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == first_attempt
    assert attempts[0]["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value

    with pytest.raises(OXApprovalError):
        service.retry_revalidation(revalidation_id, renewed_approval=False)
    assert len(client.calls) == calls_before + 1
    assert len(store.get_revalidation(revalidation_id)["attempts"]) == 1

    retry = service.retry_revalidation(revalidation_id, renewed_approval=True)
    assert retry["state"] == ReviewState.TRANSMITTING.value
    assert retry["launch_accepted"] is True
    q03hr.wait_for_revalidation_state(store, revalidation_id, ReviewState.BLIND_REVALIDATED)
    q03hr.wait_for_lane_release(jobs)

    assert len(client.calls) == calls_before + 2
    final_attempts = store.get_revalidation(revalidation_id)["attempts"]
    assert len(final_attempts) == 2
    assert final_attempts[0]["attempt_id"] == first_attempt
    assert final_attempts[1]["attempt_id"] == retry["attempt_id"]
    assert final_attempts[1]["phase"] == "blind"
    assert final_attempts[1]["outcome"] == AttemptOutcome.COMPLETED.value
    assert all(
        attempt["runtime_session_id"] == jobs.runtime_session_id
        for attempt in final_attempts
    )
    assert all(call["json_mode"] is False for call in client.calls[-2:])
