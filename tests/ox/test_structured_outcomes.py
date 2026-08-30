from byte_mcp.errors import OXRateLimitError, OXTransportError
from byte_mcp.ox.models import AttemptOutcome, ReviewState
from tests.ox.test_natural_review_architecture import make_natural_service
from tests.ox.test_review_service import prepare


class ProviderErrorClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def complete(self, messages, *, json_mode: bool, attempt_id: str):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "json_mode": json_mode,
                "attempt_id": attempt_id,
            }
        )
        raise self.error


def assert_terminal_result(
    result: dict[str, object],
    *,
    review_id: str,
    manifest_sha256: str,
    state: ReviewState,
    outcome: AttemptOutcome,
    safe_error_type: str,
) -> None:
    assert result == {
        "review_id": review_id,
        "attempt_id": f"{review_id}-A001",
        "state": state.value,
        "manifest_sha256": manifest_sha256,
        "attempt_outcome": outcome.value,
        "safe_error_type": safe_error_type,
        "response_available": False,
        "replayed": False,
    }


def test_natural_unknown_initial_attempt_returns_structured_terminal_result(tmp_path) -> None:
    client = ProviderErrorClient(OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"))
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert_terminal_result(
        result,
        review_id=proposal["review_id"],
        manifest_sha256=proposal["manifest_sha256"],
        state=ReviewState.OUTCOME_UNKNOWN,
        outcome=AttemptOutcome.OUTCOME_UNKNOWN,
        safe_error_type="OXTransportError",
    )
    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["safe_error_type"] == "OXTransportError"


def test_natural_rejected_initial_attempt_returns_structured_terminal_result(tmp_path) -> None:
    client = ProviderErrorClient(OXRateLimitError(attempt_outcome="REJECTED"))
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert_terminal_result(
        result,
        review_id=proposal["review_id"],
        manifest_sha256=proposal["manifest_sha256"],
        state=ReviewState.FAILED,
        outcome=AttemptOutcome.REJECTED,
        safe_error_type="OXRateLimitError",
    )
    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["safe_error_type"] == "OXRateLimitError"


def test_natural_not_sent_initial_attempt_returns_structured_terminal_result(tmp_path) -> None:
    client = ProviderErrorClient(OXTransportError(attempt_outcome="NOT_SENT"))
    service, store, _, base, target, _ = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert_terminal_result(
        result,
        review_id=proposal["review_id"],
        manifest_sha256=proposal["manifest_sha256"],
        state=ReviewState.FAILED,
        outcome=AttemptOutcome.NOT_SENT,
        safe_error_type="OXTransportError",
    )
    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["safe_error_type"] == "OXTransportError"
