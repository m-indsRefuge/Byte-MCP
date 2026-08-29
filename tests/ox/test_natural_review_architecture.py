import hashlib
import json

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
    targeted_serialized = json.dumps(targeted_call["messages"])
    assert targeted_call["json_mode"] is False
    assert targeted["state"] == ReviewState.REVALIDATED.value
    assert targeted["response"]
    assert "findings" not in targeted
    assert "derived-from-ox-natural-review" in targeted_serialized
    assert '"derivation_authority":"byte"' in targeted_serialized


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
