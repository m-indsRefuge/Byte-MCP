from collections.abc import Mapping
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass, replace

import pytest

from byte_mcp.errors import (
    OXAuthenticationError,
    OXContextLimitError,
    OXFindingValidationError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRequestError,
    OXTransportError,
    OXTransportFailureKind,
)
from byte_mcp.ox.models import ProviderResult, ProviderTransportObservation, ProviderUsage

SENTINEL = "Q03JA-SENSITIVE-CONTENT"


def observation(
    *,
    kind: OXTransportFailureKind | None = None,
    status_code: int = 200,
) -> ProviderTransportObservation:
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at="2026-09-05T08:00:01+00:00",
        response_headers_elapsed_ms=1000,
        http_status_code=status_code,
        response_body_started=True,
        first_body_at="2026-09-05T08:00:02+00:00",
        first_body_elapsed_ms=2000,
        last_body_at="2026-09-05T08:00:03+00:00",
        last_body_elapsed_ms=3000,
        decoded_body_bytes_received=128,
        provider_finished_at="2026-09-05T08:00:04+00:00",
        elapsed_ms=4000,
        transport_failure_kind=kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def _assert_bounded_diagnostic_state(value: object) -> None:
    assert not isinstance(value, BaseException)
    if isinstance(value, str):
        assert SENTINEL not in value
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _assert_bounded_diagnostic_state(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_bounded_diagnostic_state(key)
            _assert_bounded_diagnostic_state(item)
    elif isinstance(value, tuple | list | set | frozenset):
        for item in value:
            _assert_bounded_diagnostic_state(item)


def test_q03ja_observation_has_exact_bounded_schema() -> None:
    value = observation()

    assert {field.name: field.type for field in fields(value)} == {
        "response_headers_received": bool,
        "response_headers_at": str | None,
        "response_headers_elapsed_ms": int | None,
        "http_status_code": int | None,
        "response_body_started": bool,
        "first_body_at": str | None,
        "first_body_elapsed_ms": int | None,
        "last_body_at": str | None,
        "last_body_elapsed_ms": int | None,
        "decoded_body_bytes_received": int,
        "provider_finished_at": str,
        "elapsed_ms": int,
        "transport_failure_kind": OXTransportFailureKind | None,
        "trust_env_enabled": bool,
        "proxy_environment_present": bool,
    }
    assert asdict(value) == {
        "response_headers_received": True,
        "response_headers_at": "2026-09-05T08:00:01+00:00",
        "response_headers_elapsed_ms": 1000,
        "http_status_code": 200,
        "response_body_started": True,
        "first_body_at": "2026-09-05T08:00:02+00:00",
        "first_body_elapsed_ms": 2000,
        "last_body_at": "2026-09-05T08:00:03+00:00",
        "last_body_elapsed_ms": 3000,
        "decoded_body_bytes_received": 128,
        "provider_finished_at": "2026-09-05T08:00:04+00:00",
        "elapsed_ms": 4000,
        "transport_failure_kind": None,
        "trust_env_enabled": True,
        "proxy_environment_present": False,
    }
    assert not hasattr(value, "__dict__")
    _assert_bounded_diagnostic_state(value)


def test_q03ja_observation_is_immutable_and_provider_result_can_carry_it() -> None:
    value = observation()
    result = ProviderResult("ok", transport_observation=value)

    assert result.transport_observation is value
    with pytest.raises(FrozenInstanceError):
        value.elapsed_ms = 5  # type: ignore[misc]


def test_q03ja_provider_result_preserves_all_legacy_positional_arguments() -> None:
    usage = ProviderUsage(7, 3, 10, 1)
    raw_response = {"id": "resp-123", "choices": []}
    result = ProviderResult("answer", usage, "resp-123", "zai/glm-5.3-flash", raw_response)

    assert result.content == "answer"
    assert result.usage is usage
    assert result.response_id == "resp-123"
    assert result.model == "zai/glm-5.3-flash"
    assert result.raw_response is raw_response
    assert result.transport_observation is None
    assert ProviderResult("answer").transport_observation is None


@pytest.mark.parametrize(
    ("error_type", "status_code", "outcome"),
    [
        (OXAuthenticationError, 401, "REJECTED"),
        (OXPermissionError, 403, "REJECTED"),
        (OXRequestError, 400, "REJECTED"),
        (OXContextLimitError, 400, "REJECTED"),
        (OXRateLimitError, 429, "REJECTED"),
        (OXQuotaError, 429, "REJECTED"),
        (OXProviderUnavailableError, 503, "REJECTED"),
        (OXProtocolError, 200, "COMPLETED"),
        (OXFindingValidationError, 200, "COMPLETED"),
    ],
)
def test_q03ja_provider_errors_carry_optional_observation(error_type, status_code, outcome) -> None:
    value = observation(status_code=status_code)
    error = error_type(attempt_outcome=outcome, transport_observation=value)
    legacy = error_type(attempt_outcome=outcome)

    assert error.transport_observation is value
    assert error.__dict__ == {"attempt_outcome": outcome, "transport_observation": value}
    assert error.args == ()
    assert legacy.__dict__ == {"attempt_outcome": outcome}
    assert legacy.args == ()
    _assert_bounded_diagnostic_state(error.__dict__)


def test_q03ja_transport_error_preserves_bounded_legacy_diagnostics() -> None:
    value = observation(kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR)
    error = OXTransportError(
        attempt_outcome="OUTCOME_UNKNOWN",
        transport_failure_kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        provider_started_at="2026-09-05T08:00:00+00:00",
        provider_finished_at=value.provider_finished_at,
        elapsed_ms=value.elapsed_ms,
        transport_observation=value,
    )

    assert error.transport_observation is value
    assert error.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
    assert error.__dict__ == {
        "attempt_outcome": "OUTCOME_UNKNOWN",
        "transport_failure_kind": OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        "provider_started_at": "2026-09-05T08:00:00+00:00",
        "provider_finished_at": "2026-09-05T08:00:04+00:00",
        "elapsed_ms": 4000,
        "transport_observation": value,
    }
    assert error.args == ()
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_bounded_diagnostic_state(error.__dict__)


@pytest.mark.parametrize("error_type", [OXProtocolError, OXTransportError])
@pytest.mark.parametrize("forbidden_field", ["headers", "body", "exception", "proxy_url"])
def test_q03ja_provider_errors_reject_unbounded_keywords(error_type, forbidden_field) -> None:
    with pytest.raises(TypeError):
        error_type(transport_observation=observation(), **{forbidden_field: SENTINEL})


@pytest.mark.parametrize("unsafe_value", [SENTINEL, RuntimeError(SENTINEL)])
def test_q03ja_privacy_walker_inspects_dataclass_slots(unsafe_value) -> None:
    # Deliberately invalid data proves the test walker reaches fields without __dict__.
    value = replace(observation(), response_headers_at=unsafe_value)

    with pytest.raises(AssertionError):
        _assert_bounded_diagnostic_state({"transport_observation": value})
