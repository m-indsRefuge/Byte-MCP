from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields

import httpx
import pytest

from byte_mcp.providers import (
    MAX_RESPONSE_BODY_BYTES,
    ProviderAttemptOutcome,
    ProviderAuthorization,
    ProviderTimeoutPolicy,
    ProviderTransmissionContext,
    ProviderTransportError,
    ProviderTransportFailureKind,
    ProviderTransportObservation,
    ProviderTransportResponse,
    execute_once,
    prepare_provider_request,
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


def _prepared_request():
    return prepare_provider_request(
        provider_id="nvidia-api-catalog",
        method="POST",
        target_origin="https://integrate.api.nvidia.com",
        endpoint_path="/v1/chat/completions",
        model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
        body={"messages": [{"content": "hello", "role": "user"}], "stream": False},
    )


def _transmission_context(prepared=None) -> ProviderTransmissionContext:
    request = _prepared_request() if prepared is None else prepared
    return ProviderTransmissionContext(
        provider_started_at=STARTED_AT,
        expected_request_sha256=request.request_sha256,
    )


def _authorization() -> ProviderAuthorization:
    return ProviderAuthorization(authorization_header_value="Bearer test-only-token")


def _timeout_policy(**overrides: float) -> ProviderTimeoutPolicy:
    values: dict[str, float] = {
        "connect_seconds": 1.0,
        "write_seconds": 1.0,
        "read_seconds": 1.0,
        "pool_seconds": 1.0,
        "absolute_deadline_seconds": 1.0,
    }
    values.update(overrides)
    return ProviderTimeoutPolicy(**values)


def _execute(*, prepared=None, context=None, authorization=None, policy=None, transport=None):
    request = _prepared_request() if prepared is None else prepared
    transmission_context = _transmission_context(request) if context is None else context
    auth = _authorization() if authorization is None else authorization
    timeout_policy = _timeout_policy() if policy is None else policy
    return asyncio.run(
        execute_once(
            request,
            transmission_context,
            auth,
            timeout_policy,
            transport=transport,
        )
    )


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


def test_execute_once_sends_exact_prepared_bytes_and_fixed_semantic_headers_once() -> None:
    prepared = _prepared_request()
    seen: dict[str, object] = {}
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = await request.aread()
        seen["authorization"] = request.headers["Authorization"]
        seen["content_type"] = request.headers["Content-Type"]
        seen["accept"] = request.headers["Accept"]
        return httpx.Response(200, content=b'{"ok":true}')

    response = _execute(prepared=prepared, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert seen == {
        "method": "POST",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "body": prepared.body_bytes,
        "authorization": "Bearer test-only-token",
        "content_type": "application/json",
        "accept": "application/json",
    }
    assert response.outcome is ProviderAttemptOutcome.COMPLETED
    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
    assert response.observation.response_headers_received is True
    assert response.observation.http_status_code == 200
    assert response.observation.decoded_body_bytes_received == len(response.body)
    assert response.observation.trust_env_enabled is True


def test_execute_once_rejects_request_hash_mismatch_without_transport_call() -> None:
    prepared = _prepared_request()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"unexpected")

    mismatched = ProviderTransmissionContext(
        provider_started_at=STARTED_AT,
        expected_request_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="request_sha256"):
        _execute(
            prepared=prepared,
            context=mismatched,
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


@pytest.mark.parametrize("status_code", [302, 400, 429, 500])
def test_execute_once_complete_non_2xx_response_is_rejected_without_following_redirects(
    status_code: int,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        headers = {"Location": "https://example.invalid/redirect"} if status_code == 302 else {}
        return httpx.Response(status_code, headers=headers, content=b"complete-response")

    response = _execute(transport=httpx.MockTransport(handler))

    assert calls == 1
    assert response.outcome is ProviderAttemptOutcome.REJECTED
    assert response.status_code == status_code
    assert response.body == b"complete-response"


class _RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, exception_type: type[httpx.TransportError]) -> None:
        self.exception_type = exception_type
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise self.exception_type("RAW SECRET TRANSPORT MESSAGE", request=request)


@pytest.mark.parametrize(
    ("exception_type", "expected_outcome", "expected_kind"),
    [
        (
            httpx.ConnectTimeout,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_TIMEOUT,
        ),
        (
            httpx.ConnectError,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_ERROR,
        ),
        (
            httpx.PoolTimeout,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.POOL_TIMEOUT,
        ),
        (
            httpx.WriteTimeout,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_TIMEOUT,
        ),
        (
            httpx.WriteError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_ERROR,
        ),
        (
            httpx.ReadTimeout,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_TIMEOUT,
        ),
        (
            httpx.ReadError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_ERROR,
        ),
        (
            httpx.RemoteProtocolError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        ),
        (
            httpx.ProxyError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.HTTP_TRANSPORT_ERROR,
        ),
    ],
)
def test_execute_once_maps_transport_failures_without_retry_or_raw_exception_retention(
    exception_type: type[httpx.TransportError],
    expected_outcome: ProviderAttemptOutcome,
    expected_kind: ProviderTransportFailureKind,
) -> None:
    transport = _RaisingTransport(exception_type)

    with pytest.raises(ProviderTransportError) as captured:
        _execute(transport=transport)

    error = captured.value
    assert transport.calls == 1
    assert error.attempt_outcome is expected_outcome
    assert error.transport_failure_kind is expected_kind
    assert error.transport_observation.transport_failure_kind is expected_kind
    assert "RAW SECRET TRANSPORT MESSAGE" not in str(error)
    assert "RAW SECRET TRANSPORT MESSAGE" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_execute_once_absolute_deadline_is_outcome_unknown_without_retry() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b"too-late")

    with pytest.raises(ProviderTransportError) as captured:
        _execute(
            policy=_timeout_policy(absolute_deadline_seconds=0.01),
            transport=httpx.MockTransport(handler),
        )

    assert calls == 1
    assert captured.value.attempt_outcome is ProviderAttemptOutcome.OUTCOME_UNKNOWN
    assert (
        captured.value.transport_failure_kind
        is ProviderTransportFailureKind.ABSOLUTE_DEADLINE
    )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_execute_once_response_body_limit_is_outcome_unknown_without_retry() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BODY_BYTES + 1))

    with pytest.raises(ProviderTransportError) as captured:
        _execute(transport=httpx.MockTransport(handler))

    assert calls == 1
    assert captured.value.attempt_outcome is ProviderAttemptOutcome.OUTCOME_UNKNOWN
    assert (
        captured.value.transport_failure_kind
        is ProviderTransportFailureKind.HTTP_TRANSPORT_ERROR
    )
    assert captured.value.transport_observation.response_headers_received is True
    assert captured.value.transport_observation.http_status_code == 200
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
