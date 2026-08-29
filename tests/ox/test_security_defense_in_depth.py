import json

import pytest

from byte_mcp.errors import OXBundleError
from tests.ox.helpers import commit_files
from tests.ox.test_review_service import verification
from tests.ox.test_security_invariants import (
    SECRET,
    BoundaryClient,
    establish_review,
)


def test_targeted_revalidation_rejects_credential_from_persisted_context_before_provider(
    tmp_path,
) -> None:
    service, store, repository_path, _, target, _, review_id = establish_review(tmp_path)
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
    service.transmit_blind_revalidation(proposal["revalidation_id"])

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
    review["identity"]["objective"] = f"legacy credential leak: {SECRET}"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(OXBundleError):
        service.get_review(review_id, view="summary")
