import hashlib
import json
import threading

import pytest

from byte_mcp.errors import OXApprovalError, OXEvidenceError, OXFindingValidationError
from byte_mcp.ox.jobs import OXProviderJobManager
from byte_mcp.ox.models import ReviewState
from byte_mcp.ox.natural_service import OXReviewService
from byte_mcp.ox.protocol import build_initial_messages
from byte_mcp.ox.settings import OXSettings
from tests.ox import q03h_initial_support as q03h
from tests.ox.helpers import commit_files, create_repository
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


def _complete_initial(service, store, review_id: str) -> dict[str, object]:
    launch = service.transmit_review(review_id)
    assert launch["state"] == ReviewState.TRANSMITTING.value
    q03h.wait_for_state(store, review_id, ReviewState.REVIEWED)
    return service.transmit_review(review_id)


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

    result = _complete_initial(service, store, proposal["review_id"])

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert result["state"] == ReviewState.REVIEWED.value
    assert result["review_text"]
    assert "findings" not in result
    assert store.get_review(proposal["review_id"])["attempts"][-1]["outcome"] == "COMPLETED"


def test_q03g_initial_natural_review_returns_receipt_metadata(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = _complete_initial(service, store, proposal["review_id"])

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
    assert result["replayed"] is True
    assert result["provider_request_performed"] is False

    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["attempt_id"] == f"{proposal['review_id']}-A001"
    assert attempt["manifest_sha256"] == proposal["manifest_sha256"]
    assert attempt["outcome"] == "COMPLETED"


def test_q03g_replayed_initial_approval_after_reviewed_uses_local_receipt_without_resend(
    tmp_path,
) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = _complete_initial(service, store, proposal["review_id"])
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


def test_q03g_replayed_receipt_reflects_current_findings_recorded_state(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]

    _complete_initial(service, store, review_id)
    service.record_findings(review_id, [])
    calls_before = len(client.calls)

    replayed = service.transmit_review(review_id)

    assert len(client.calls) == calls_before
    assert replayed["state"] == ReviewState.REVIEWED.value
    assert replayed["findings_recorded"] is True
    assert replayed["replayed"] is True
    assert replayed["provider_request_performed"] is False


def test_q03g_initial_approval_replay_while_transmitting_never_resends(tmp_path) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first_result = service.transmit_review(proposal["review_id"])
    assert client.entered.wait(timeout=5)
    replayed = service.transmit_review(proposal["review_id"])

    assert first_result["state"] == ReviewState.TRANSMITTING.value
    assert replayed["review_id"] == proposal["review_id"]
    assert replayed["attempt_id"] == f"{proposal['review_id']}-A001"
    assert replayed["state"] == ReviewState.TRANSMITTING.value
    assert replayed["review_text"] is None
    assert replayed["findings_recorded"] is False
    assert replayed["replayed"] is True
    assert replayed["provider_request_performed"] is False
    assert len(client.calls) == 0

    client.release.set()
    q03h.wait_for_state(store, proposal["review_id"], ReviewState.REVIEWED)
    assert len(client.calls) == 1
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == f"{proposal['review_id']}-A001"


def test_q03g_findings_view_reports_recorded_state(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    _complete_initial(service, store, review_id)

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
    review = _complete_initial(service, store, proposal["review_id"])
    calls_before = len(client.calls)

    result = service.record_findings(proposal["review_id"], [])

    assert len(client.calls) == calls_before
    assert result["protocol_version"] == "byte-derived-findings-v1"
    assert result["review_id"] == proposal["review_id"]
    assert result["source_attempt_id"] == f"{proposal['review_id']}-A001"
    assert result["source_response_sha256"] == hashlib.sha256(
        review["review_text"].encode("utf-8")
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
    review = _complete_initial(service, store, proposal["review_id"])
    calls_before = len(client.calls)

    result = service.record_findings(proposal["review_id"], [derived_finding()])

    assert len(client.calls) == calls_before
    assert result["protocol_version"] == "byte-derived-findings-v1"
    assert result["review_id"] == proposal["review_id"]
    assert result["source_attempt_id"] == f"{proposal['review_id']}-A001"
    assert result["source_response_sha256"] == hashlib.sha256(
        review["review_text"].encode("utf-8")
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
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    _complete_initial(service, store, proposal["review_id"])
    calls_before = len(client.calls)
    malformed = derived_finding()
    malformed["severity"] = "urgent"

    with pytest.raises(OXFindingValidationError):
        service.record_findings(proposal["review_id"], [malformed])

    assert len(client.calls) == calls_before


def test_natural_blind_and_targeted_revalidation_preserve_byte_provenance(tmp_path) -> None:
    client = RecordingClient()
    service, store, repository_path, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    _complete_initial(service, store, review_id)
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
    service, store, repository_path, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    _complete_initial(service, store, review_id)
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


def test_q03h_ac04_same_active_operation_replays_without_duplicate_work(tmp_path) -> None:
    client = q03h.BlockingNaturalClient()
    service, store, _, base, target = q03h.make_natural_service(tmp_path, client)
    proposal = q03h.prepare(service, base, target)
    review_id = str(proposal["review_id"])

    first = service.transmit_review(review_id)
    assert client.entered.wait(timeout=5)
    before_attempts = list(store.get_review(review_id)["attempts"])
    before_calls = len(client.calls)

    replay = service.transmit_review(review_id)

    assert first["launch_accepted"] is True
    assert replay["launch_accepted"] is False
    assert replay["replayed"] is True
    assert replay["attempt_id"] == first["attempt_id"]
    assert store.get_review(review_id)["attempts"] == before_attempts
    assert len(client.calls) == before_calls == 1

    client.release.set()
    q03h.wait_for_state(store, review_id, ReviewState.REVIEWED)


def test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence(tmp_path) -> None:
    order: list[str] = []
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    q03h.write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, tmp_path / "evidence")
    store = q03h.RecordingEvidenceStore(settings.evidence_root, order)
    jobs = OXProviderJobManager()
    client = q03h.OrderedNaturalClient(order)
    service = OXReviewService(settings, store, client, q03h.OrderedAudit(order), jobs)
    proposal = q03h.prepare(service, base, target)
    review_id = str(proposal["review_id"])

    receipt = service.transmit_review(review_id)
    assert receipt["launch_accepted"] is True
    assert client.completed.wait(timeout=5)
    q03h.wait_for_state(store, review_id, ReviewState.REVIEWED)
    q03h.wait_for_lane_release(jobs)

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert client.calls[0]["attempt_id"] == receipt["attempt_id"]
    assert order.index("provider-start") < order.index("client.complete")
    assert order.index("client.complete") < order.index("raw-response")
    assert order.index("raw-response") < order.index("assistant-thread")
    assert order.index("assistant-thread") < order.index("outcome:COMPLETED")
    assert order.index("outcome:COMPLETED") < order.index("audit")
    attempt = store.get_review(review_id)["attempts"][-1]
    assert attempt["runtime_session_id"] == jobs.runtime_session_id
    assert "provider_started_at" in attempt
