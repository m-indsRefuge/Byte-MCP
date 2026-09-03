import json

import pytest

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.models import ReviewState
from byte_mcp.ox.settings import OXSettings
from tests.ox import q03h_revalidation_support as q03hr
from tests.ox.helpers import commit_files
from tests.ox.q03h_initial_support import wait_for_lane_release, wait_for_state
from tests.ox.test_review_followup import UnknownContinuationClient, UnknownTargetedClient
from tests.ox.test_review_service import make_service, prepare, verification
from tests.ox.test_security_invariants import (
    SECRET,
    BoundaryClient,
    establish_review,
)


def _complete_initial(service, store, review_id: str) -> None:
    launch = service.transmit_review(review_id)
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)


def test_targeted_revalidation_rejects_credential_from_persisted_context_before_provider(
    tmp_path,
) -> None:
    service, store, repository_path, _, target, _, review_id = establish_review(tmp_path)
    wait_for_lane_release(service._jobs)
    service.adjudicate(
        review_id,
        [
            {
                "finding_id": f"{review_id}-F001",
                "status": "CONFIRMED",
                "evidence": "Confirmed from committed evidence.",
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
    launch = service.transmit_blind_revalidation(proposal["revalidation_id"])
    assert launch["state"] == ReviewState.TRANSMITTING.value
    q03hr.wait_for_revalidation_state(
        store,
        proposal["revalidation_id"],
        ReviewState.BLIND_REVALIDATED,
    )
    wait_for_lane_release(service._jobs)

    store.append_adjudication(
        review_id,
        {
            "event_id": f"{review_id}-ADJ999",
            "finding_id": f"{review_id}-F001",
            "status": "CONFIRMED",
            "evidence": f"legacy credential leak: {SECRET}",
            "reasoning_summary": "synthetic tampered evidence",
            "recorded_at": "2026-08-29T19:50:00Z",
        },
    )
    boundary = BoundaryClient()
    service._client = boundary

    with pytest.raises(OXBundleError):
        service.run_targeted_revalidation(
            proposal["revalidation_id"], [f"{review_id}-F001"]
        )

    assert boundary.calls == 0


def test_get_review_rejects_configured_credential_from_tampered_local_evidence(tmp_path) -> None:
    service, store, _, _, _, _, review_id = establish_review(tmp_path)
    review_path = store._root / "reviews" / review_id / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["objective"] = f"legacy credential leak: {SECRET}"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(OXBundleError):
        service.get_review(review_id, view="summary")


def test_attempts_view_rejects_configured_credential_from_tampered_local_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    service, store, _, _, _, _, review_id = establish_review(tmp_path)
    wait_for_lane_release(service._jobs)
    original_get_review = store.get_review

    def tampered_get_review(subject_id: str) -> dict[str, object]:
        review = original_get_review(subject_id)
        attempts = review.get("attempts")
        assert isinstance(attempts, list) and attempts
        attempts[0]["transport_failure_kind"] = f"legacy credential leak: {SECRET}"
        return review

    monkeypatch.setattr(store, "get_review", tampered_get_review)
    boundary = BoundaryClient()
    service._client = boundary

    with pytest.raises(OXBundleError):
        service.get_review(review_id, view="attempts")

    assert boundary.calls == 0


def test_continuation_retry_rejects_credential_from_authentic_legacy_failed_history(
    tmp_path,
) -> None:
    client = UnknownContinuationClient()
    service, store, _, base, target, registry_path = make_service(tmp_path, client)
    proposal = prepare(service, base, target)
    _complete_initial(service, store, proposal["review_id"])

    launch = service.continue_message(
        proposal["review_id"], f"legacy continuation contained {SECRET}"
    )
    wait_for_state(store, proposal["review_id"], ReviewState.OUTCOME_UNKNOWN)
    wait_for_lane_release(service._jobs)
    failed_attempt = launch["attempt_id"]

    service._settings = OXSettings(SECRET, registry_path, store._root)
    boundary = BoundaryClient()
    service._client = boundary

    with pytest.raises(OXBundleError):
        service.retry_continuation(
            proposal["review_id"], failed_attempt, renewed_approval=True
        )

    assert boundary.calls == 0


def test_targeted_retry_rejects_credential_from_authentic_legacy_failed_history(
    tmp_path,
) -> None:
    client = UnknownTargetedClient()
    service, store, repository_path, base, target, registry_path = make_service(
        tmp_path, client
    )
    proposal = prepare(service, base, target)
    _complete_initial(service, store, proposal["review_id"])
    service.adjudicate(
        proposal["review_id"],
        [
            {
                "finding_id": f"{proposal['review_id']}-F001",
                "status": "CONFIRMED",
                "evidence": f"legacy adjudication contained {SECRET}",
                "reasoning_summary": "Needs remediation.",
            }
        ],
    )
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    revalidation = service.prepare_revalidation(
        proposal["review_id"],
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )
    blind = service.transmit_blind_revalidation(revalidation["revalidation_id"])
    assert blind["state"] == ReviewState.TRANSMITTING.value
    q03hr.wait_for_revalidation_state(
        store,
        revalidation["revalidation_id"],
        ReviewState.BLIND_REVALIDATED,
    )
    wait_for_lane_release(service._jobs)

    targeted = service.run_targeted_revalidation(
        revalidation["revalidation_id"], [f"{proposal['review_id']}-F001"]
    )
    assert targeted["state"] == ReviewState.TRANSMITTING.value
    q03hr.wait_for_revalidation_state(
        store,
        revalidation["revalidation_id"],
        ReviewState.OUTCOME_UNKNOWN,
    )
    wait_for_lane_release(service._jobs)

    service._settings = OXSettings(SECRET, registry_path, store._root)
    boundary = BoundaryClient()
    service._client = boundary

    with pytest.raises(OXBundleError):
        service.retry_revalidation(
            revalidation["revalidation_id"], renewed_approval=True
        )

    assert boundary.calls == 0
