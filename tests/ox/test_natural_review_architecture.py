import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from byte_mcp.errors import OXApprovalError, OXEvidenceError, OXFindingValidationError
from byte_mcp.ox.models import ReviewState
from byte_mcp.ox.natural_service import OXReviewService
from byte_mcp.ox.protocol import build_initial_messages
from tests.ox.helpers import commit_files
from tests.ox.test_review_service import RecordingClient, make_service, prepare, verification


def derived_finding() -> dict[str, object]:
    return {
        "category": "correctness",
        "severity": "high",
        "confidence": 0.95,
        "location": "src/alpha.py:1",
        "claim": "The implementation violates the stated contract.",
        "evidence": "OX identified the committed line and Byte verified the source reference.",
        "reproduction": "Inspect the committed line against the supplied contract.",
        "expected_behavior": "The committed implementation should satisfy the contract.",
        "observed_or_predicted_behavior": "The committed implementation does not satisfy it.",
        "disproof_condition": "Show the cited implementation is contract-compliant.",
        "recommended_investigation": "Reproduce the behavior against the committed evidence.",
    }


def make_natural_service(tmp_path, client: RecordingClient):
    base_service, store, repository_path, base, target, registry_path = make_service(
        tmp_path, client
    )
    service = OXReviewService(
        base_service._settings,
        store,
        client,
        base_service._audit,
    )
    return service, store, repository_path, base, target, registry_path


class BlockingNaturalClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("blocked provider fixture was not released")
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)

def test_initial_prompt_requests_natural_engineering_review() -> None:
    messages = build_initial_messages({"artifact": "value"}, objective="Review it.")

    system = messages[0]["content"]
    assert "independent" in system.lower()
    assert "falsifiable" in system.lower()
    assert "natural" in system.lower() or "markdown" in system.lower()
    assert "ox-findings-v1" not in system
    assert "Return only JSON" not in system


def test_initial_review_uses_natural_provider_response_without_findings_parse(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert result["state"] == ReviewState.REVIEWED.value
    assert result["response"]
    assert "findings" not in result
    assert store.get_review(proposal["review_id"])["attempts"][-1]["outcome"] == "COMPLETED"


def test_q03g_initial_natural_review_returns_receipt_metadata(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert result["review_id"] == proposal["review_id"]
    assert result["attempt_id"] == f"{proposal['review_id']}-A001"
    assert result["state"] == ReviewState.REVIEWED.value
    assert result["manifest_sha256"] == proposal["manifest_sha256"]
    assert result["review_text"] == store.read_thread(
        proposal["review_id"], "initial"
    )[-1]["content"]
    assert result["findings_recorded"] is False
    assert result["replayed"] is False
    assert result["provider_request_performed"] is True

    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["attempt_id"] == f"{proposal['review_id']}-A001"
    assert attempt["manifest_sha256"] == proposal["manifest_sha256"]
    assert attempt["outcome"] == "COMPLETED"


def test_q03g_replayed_initial_approval_after_reviewed_uses_local_receipt_without_resend(
    tmp_path,
) -> None:
    client = RecordingClient()
    service, _, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    assert first["state"] == ReviewState.REVIEWED.value
    assert len(client.calls) == 1

    replayed = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert replayed["review_id"] == proposal["review_id"]
    assert replayed["attempt_id"] == f"{proposal['review_id']}-A001"
    assert replayed["state"] == ReviewState.REVIEWED.value
    assert replayed["review_text"]
    assert replayed["replayed"] is True
    assert replayed["provider_request_performed"] is False


def test_q03g_initial_approval_replay_while_transmitting_never_resends(tmp_path) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.transmit_review, proposal["review_id"])
        assert client.entered.wait(timeout=5)

        try:
            replayed = service.transmit_review(proposal["review_id"])

            assert replayed["review_id"] == proposal["review_id"]
            assert replayed["attempt_id"] == f"{proposal['review_id']}-A001"
            assert replayed["state"] == ReviewState.TRANSMITTING.value
            assert replayed["review_text"] is None
            assert replayed["findings_recorded"] is False
            assert replayed["replayed"] is True
            assert replayed["provider_request_performed"] is False
            assert len(client.calls) == 0
        finally:
            client.release.set()
            first_result = first.result(timeout=5)

    assert first_result["state"] == ReviewState.REVIEWED.value
    assert len(client.calls) == 1
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == f"{proposal['review_id']}-A001"

def test_q03g_findings_view_reports_recorded_state(tmp_path) -> None:
    client = RecordingClient()
    service, _, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    service.transmit_review(review_id)

    before = service.get_review(review_id, view="findings")

    assert before == {
        "review_id": review_id,
        "recorded": False,
        "findings": [],
    }

    service.record_findings(review_id, [derived_finding()])

    after = service.get_review(review_id, view="findings")

    assert after["review_id"] == review_id
    assert after["recorded"] is True
    assert after["protocol_version"] == "byte-derived-findings-v1"
    assert len(after["findings"]) == 1

def test_q03g_record_findings_accepts_explicit_empty_set_without_provider_call(
    tmp_path,
) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review = service.transmit_review(proposal["review_id"])
    calls_before = len(client.calls)

    result = service.record_findings(proposal["review_id"], [])

    assert len(client.calls) == calls_before
    assert result["protocol_version"] == "byte-derived-findings-v1"
    assert result["review_id"] == proposal["review_id"]
    assert result["source_attempt_id"] == f"{proposal['review_id']}-A001"
    assert result["source_response_sha256"] == hashlib.sha256(
        review["response"].encode("utf-8")
    ).hexdigest()
    assert result["derivation_authority"] == "byte"
    assert result["derivation_provenance"] == "derived-from-ox-natural-review"
    assert result["findings"] == []
    assert store.findings_recorded(proposal["review_id"]) is True

    view = service.get_review(proposal["review_id"], view="findings")
    assert view["recorded"] is True
    assert view["protocol_version"] == "byte-derived-findings-v1"
    assert view["findings"] == []

    with pytest.raises(OXEvidenceError):
        service.record_findings(proposal["review_id"], [])

def test_record_findings_is_local_immutable_and_bound_to_exact_ox_response(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review = service.transmit_review(proposal["review_id"])
    calls_before = len(client.calls)

    result = service.record_findings(proposal["review_id"], [derived_finding()])

    assert len(client.calls) == calls_before
    assert result["protocol_version"] == "byte-derived-findings-v1"
    assert result["review_id"] == proposal["review_id"]
    assert result["source_attempt_id"] == f"{proposal['review_id']}-A001"
    assert result["source_response_sha256"] == hashlib.sha256(
        review["response"].encode("utf-8")
    ).hexdigest()
    assert result["derivation_authority"] == "byte"
    assert result["derivation_provenance"] == "derived-from-ox-natural-review"
    assert result["findings"][0]["finding_id"] == f"{proposal['review_id']}-F001"
    assert result["findings"][0]["status"] == "RAISED"
    assert store.read_findings(proposal["review_id"]) == result

    with pytest.raises(OXEvidenceError):
        service.record_findings(proposal["review_id"], [derived_finding()])


def test_record_findings_rejects_malformed_local_interpretation_without_provider_call(
    tmp_path,
) -> None:
    client = RecordingClient()
    service, _, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])
    calls_before = len(client.calls)
    malformed = derived_finding()
    malformed["severity"] = "urgent"

    with pytest.raises(OXFindingValidationError):
        service.record_findings(proposal["review_id"], [malformed])

    assert len(client.calls) == calls_before


def test_natural_blind_and_targeted_revalidation_preserve_byte_provenance(tmp_path) -> None:
    client = RecordingClient()
    service, _, repository_path, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    service.transmit_review(review_id)
    service.record_findings(review_id, [derived_finding()])
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    revalidation = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )

    with pytest.raises(OXApprovalError):
        service.run_targeted_revalidation(
            revalidation["revalidation_id"], [f"{review_id}-F001"]
        )

    blind = service.transmit_blind_revalidation(revalidation["revalidation_id"])
    blind_call = client.calls[-1]
    assert blind_call["json_mode"] is False
    assert blind["state"] == ReviewState.BLIND_REVALIDATED.value
    assert blind["response"]
    assert "findings" not in blind
    assert "derived-from-ox-natural-review" not in json.dumps(blind_call["messages"])

    targeted = service.run_targeted_revalidation(
        revalidation["revalidation_id"], [f"{review_id}-F001"]
    )
    targeted_call = client.calls[-1]
    targeted_payload = json.loads(targeted_call["messages"][-1]["content"])
    targeted_context = targeted_payload["review_packet"]["targeted_context"]
    provenance = targeted_context["byte_derived_findings_provenance"]
    assert targeted_call["json_mode"] is False
    assert targeted["state"] == ReviewState.REVALIDATED.value
    assert targeted["response"]
    assert "findings" not in targeted
    assert provenance["derivation_authority"] == "byte"
    assert provenance["derivation_provenance"] == "derived-from-ox-natural-review"
    assert len(targeted_context["byte_derived_findings"]) == 1


def test_targeted_revalidation_requires_byte_derived_findings_after_natural_blind(
    tmp_path,
) -> None:
    client = RecordingClient()
    service, _, repository_path, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    service.transmit_review(review_id)
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    revalidation = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )
    service.transmit_blind_revalidation(revalidation["revalidation_id"])
    calls_before = len(client.calls)

    with pytest.raises(OXApprovalError):
        service.run_targeted_revalidation(
            revalidation["revalidation_id"], [f"{review_id}-F001"]
        )

    assert len(client.calls) == calls_before
