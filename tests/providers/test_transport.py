from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderAuthorization,
    ProviderTimeoutPolicy,
    ProviderTransmissionContext,
    ProviderTransportError,
    ProviderTransportFailureKind,
    ProviderTransportObservation,
    ProviderTransportResponse,
)
from byte_mcp.providers.transport import _TransportTracker

STARTED_AT = "2026-09-08T12:00:00+00:00"
FINISHED_AT = "2026-09-08T12:00:01+00:00"
REQUEST_SHA256 = "a" * 64


def _observation(**overrides: object) -> ProviderTransportObservation:
    values: dict[str, object] = {
        "response_headers_received": True,
        "response_headers_at": "2026-09-08T12:00:00.100000+00:00",
        "response_headers_elapsed_ms": 100,
        "http_status_code": 200,
        "response_body_started": True,
        "first_body_at": "2026-09-08T12:00:00.200000+00:00",
        "first_body_elapsed_ms": 200,
        "last_body_at": "2026-09-08T12:00:00.900000+00:00",
        "last_body_elapsed_ms": 900,
        "decoded_body_bytes_received": 17,
        "provider_started_at": STARTED_AT,
        "provider_finished_at": FINISHED_AT,
        "elapsed_ms": 1_000,
        "transport_failure_kind": None,
        "trust_env_enabled": False,
        "proxy_environment_present": False,
    }
    values.update(overrides)
    return ProviderTransportObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "provider_started_at",
    ["2026-09-08T12:00:00", "not-a-timestamp"],
)
def test_transmission_context_rejects_non_timezone_aware_start(
    provider_started_at: str,
) -> None:
    with pytest.raises(ValueError):
        ProviderTransmissionContext(
            provider_started_at=provider_started_at,
            expected_request_sha256=REQUEST_SHA256,
        )


@pytest.mark.parametrize(
    "expected_request_sha256",
    ["A" * 64, "a" * 63, "g" * 64],
)
def test_transmission_context_requires_lowercase_sha256(
    expected_request_sha256: str,
) -> None:
    with pytest.raises(ValueError):
        ProviderTransmissionContext(
            provider_started_at=STARTED_AT,
            expected_request_sha256=expected_request_sha256,
        )


def test_authorization_is_immutable_bounded_and_redacted() -> None:
    authorization = ProviderAuthorization(authorization_header_value="Bearer super-secret-value")
    maximum = ProviderAuthorization(authorization_header_value="Bearer " + "x" * 8_185)

    assert "super-secret-value" not in repr(authorization)
    assert "configured" in repr(authorization)
    assert len(maximum.authorization_header_value) == 8_192
    with pytest.raises(FrozenInstanceError):
        authorization.authorization_header_value = "Bearer changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Bearer ",
        "Bearer  ",
        "Basic token",
        "Bearer secret\rvalue",
        "Bearer café",
        "Bearer " + "x" * 8_186,
    ],
)
def test_authorization_rejects_invalid_bearer_values(value: str) -> None:
    with pytest.raises(ValueError):
        ProviderAuthorization(authorization_header_value=value)


@pytest.mark.parametrize(
    "value",
    [0, -1, float("inf"), float("nan"), 600.01, True],
)
def test_timeout_policy_requires_finite_positive_bounded_values(value: object) -> None:
    values = {
        "connect_seconds": 10.0,
        "write_seconds": 30.0,
        "read_seconds": 300.0,
        "pool_seconds": 10.0,
        "absolute_deadline_seconds": 300.0,
    }
    values["read_seconds"] = value
    with pytest.raises(ValueError):
        ProviderTimeoutPolicy(**values)  # type: ignore[arg-type]


def test_timeout_policy_accepts_subsecond_and_maximum_values() -> None:
    policy = ProviderTimeoutPolicy(
        connect_seconds=0.001,
        write_seconds=600,
        read_seconds=600.0,
        pool_seconds=0.5,
        absolute_deadline_seconds=600,
    )
    assert policy.absolute_deadline_seconds == 600


def test_observation_contains_only_approved_metadata_fields() -> None:
    observation = _observation()

    assert {field.name for field in fields(observation)} == {
        "response_headers_received",
        "response_headers_at",
        "response_headers_elapsed_ms",
        "http_status_code",
        "response_body_started",
        "first_body_at",
        "first_body_elapsed_ms",
        "last_body_at",
        "last_body_elapsed_ms",
        "decoded_body_bytes_received",
        "provider_started_at",
        "provider_finished_at",
        "elapsed_ms",
        "transport_failure_kind",
        "trust_env_enabled",
        "proxy_environment_present",
    }
    with pytest.raises(FrozenInstanceError):
        observation.elapsed_ms = 2_000  # type: ignore[misc]


def test_response_repr_does_not_reveal_body() -> None:
    response = ProviderTransportResponse(
        outcome=ProviderAttemptOutcome.COMPLETED,
        status_code=200,
        body=b"response-secret",
        observation=_observation(),
    )

    assert "response-secret" not in repr(response)
    assert "body=" not in repr(response)


def test_transport_error_text_contains_only_safe_enum_metadata() -> None:
    observation = _observation(
        response_headers_received=False,
        response_headers_at=None,
        response_headers_elapsed_ms=None,
        http_status_code=None,
        response_body_started=False,
        first_body_at=None,
        first_body_elapsed_ms=None,
        last_body_at=None,
        last_body_elapsed_ms=None,
        decoded_body_bytes_received=0,
        transport_failure_kind=ProviderTransportFailureKind.CONNECT_ERROR,
    )
    error = ProviderTransportError(
        attempt_outcome=ProviderAttemptOutcome.NOT_SENT,
        transport_failure_kind=ProviderTransportFailureKind.CONNECT_ERROR,
        transport_observation=observation,
    )

    assert str(error) == "provider transport failed: NOT_SENT/CONNECT_ERROR"
    assert "response-secret" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "key",
    [
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ],
)
def test_tracker_records_only_recognized_proxy_environment_presence(key: str) -> None:
    tracker = _TransportTracker(
        ProviderTransmissionContext(STARTED_AT, REQUEST_SHA256),
        trust_env_enabled=False,
        environ={key: "http://proxy-secret.example"},
    )

    observation = tracker.finish(provider_finished_at=FINISHED_AT, elapsed_ms=1_000)
    assert observation.proxy_environment_present is True
    assert "proxy-secret" not in repr(observation)


def test_tracker_ignores_unrecognized_proxy_environment_names() -> None:
    tracker = _TransportTracker(
        ProviderTransmissionContext(STARTED_AT, REQUEST_SHA256),
        trust_env_enabled=False,
        environ={"NO_PROXY": "secret.example"},
    )

    observation = tracker.finish(provider_finished_at=FINISHED_AT, elapsed_ms=1_000)
    assert observation.proxy_environment_present is False
