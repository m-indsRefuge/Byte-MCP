from byte_mcp.ox.execution import execute_provider_attempt

from byte_mcp.errors import OXRateLimitError, OXTransportError
from byte_mcp.ox.models import AttemptOutcome, ProviderAttemptResult, ProviderResult


class SuccessClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            content="review",
            raw_response={
                "choices": [
                    {"message": {"role": "assistant", "content": "review"}}
                ]
            },
        )


class ErrorClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls += 1
        raise self.error


def test_execute_provider_attempt_returns_completed_without_retry() -> None:
    client = SuccessClient()

    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )

    assert client.calls == 1
    assert result.outcome is AttemptOutcome.COMPLETED
    assert isinstance(result.provider_result, ProviderResult)
    assert result.safe_error_type is None


def test_execute_provider_attempt_maps_unknown_transport_without_retry() -> None:
    client = ErrorClient(OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"))

    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )

    assert client.calls == 1
    assert result == ProviderAttemptResult(
        outcome=AttemptOutcome.OUTCOME_UNKNOWN,
        provider_result=None,
        safe_error_type="OXTransportError",
    )


def test_execute_provider_attempt_maps_rejected_provider_error() -> None:
    client = ErrorClient(OXRateLimitError(attempt_outcome="REJECTED"))

    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )

    assert client.calls == 1
    assert result == ProviderAttemptResult(
        outcome=AttemptOutcome.REJECTED,
        provider_result=None,
        safe_error_type="OXRateLimitError",
    )
