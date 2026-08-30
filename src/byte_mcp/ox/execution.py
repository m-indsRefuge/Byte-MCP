from collections.abc import Mapping, Sequence

from byte_mcp.errors import (
    OXAuthenticationError,
    OXContextLimitError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRequestError,
    OXTransportError,
)

from .models import AttemptOutcome, ProviderAttemptResult

_PROVIDER_ERRORS = (
    OXAuthenticationError,
    OXPermissionError,
    OXRequestError,
    OXContextLimitError,
    OXRateLimitError,
    OXQuotaError,
    OXProviderUnavailableError,
    OXTransportError,
    OXProtocolError,
)


def execute_provider_attempt(
    client,
    messages: Sequence[Mapping[str, object]],
    *,
    json_mode: bool,
    attempt_id: str,
) -> ProviderAttemptResult:
    """Execute exactly one OX provider call and classify its bounded outcome."""
    try:
        provider_result = client.complete(
            messages,
            json_mode=json_mode,
            attempt_id=attempt_id,
        )
    except _PROVIDER_ERRORS as exc:
        return ProviderAttemptResult(
            outcome=AttemptOutcome(exc.attempt_outcome),
            safe_error_type=type(exc).__name__,
        )
    return ProviderAttemptResult(
        outcome=AttemptOutcome.COMPLETED,
        provider_result=provider_result,
    )
