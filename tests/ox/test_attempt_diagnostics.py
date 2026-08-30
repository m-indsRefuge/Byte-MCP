import pytest

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox.models import AttemptOutcome
from tests.ox.test_review_service import FailIfCalledClient, make_service, prepare


def test_attempt_event_round_trips_safe_error_type(tmp_path) -> None:
    service, store, _, base, target, _ = make_service(tmp_path, FailIfCalledClient())
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    attempt = store.claim_initial_transmission(review_id, proposal["manifest_sha256"])

    store.record_attempt_outcome(
        review_id,
        attempt["attempt_id"],
        AttemptOutcome.OUTCOME_UNKNOWN,
        safe_error_type="OXTransportError",
    )

    persisted = store.get_review(review_id)["attempts"][-1]
    assert persisted["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value
    assert persisted["safe_error_type"] == "OXTransportError"


def test_attempt_event_rejects_unbounded_safe_error_type(tmp_path) -> None:
    service, store, _, base, target, _ = make_service(tmp_path, FailIfCalledClient())
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]
    attempt = store.claim_initial_transmission(review_id, proposal["manifest_sha256"])

    with pytest.raises(OXEvidenceError):
        store.record_attempt_outcome(
            review_id,
            attempt["attempt_id"],
            AttemptOutcome.REJECTED,
            safe_error_type="OXRateLimitError: bearer secret",
        )
