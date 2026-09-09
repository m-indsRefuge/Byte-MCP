"""Provider-neutral exactly-once HTTP transport and bounded metadata tracking."""

from __future__ import annotations

import asyncio
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic_ns

import httpx

from byte_mcp.errors import ByteMCPError

from .outcomes import ProviderAttemptOutcome, ProviderTransportFailureKind
from .requests import PreparedProviderRequest

MAX_RESPONSE_BODY_BYTES = 8_000_000
MAX_TIMEOUT_SECONDS = 600.0
_MAX_AUTHORIZATION_CHARS = 8_192
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_PROXY_ENV_KEYS = frozenset(
    {
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    }
)
_TRUST_ENV = True


def _require_aware_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed_ms(started_monotonic_ns: int) -> int:
    return max(0, (monotonic_ns() - started_monotonic_ns) // 1_000_000)


@dataclass(frozen=True, slots=True)
class ProviderTransmissionContext:
    provider_started_at: str
    expected_request_sha256: str

    def __post_init__(self) -> None:
        _require_aware_timestamp(self.provider_started_at, "provider_started_at")
        if not isinstance(self.expected_request_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.expected_request_sha256
        ):
            raise ValueError("expected_request_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True, repr=False)
class ProviderAuthorization:
    authorization_header_value: str = field(repr=False)

    def __post_init__(self) -> None:
        value = self.authorization_header_value
        bearer_value = value.removeprefix("Bearer ") if isinstance(value, str) else ""
        if (
            not isinstance(value, str)
            or not value.startswith("Bearer ")
            or len(value) > _MAX_AUTHORIZATION_CHARS
            or not value.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or not bearer_value
            or any(not 33 <= ord(character) <= 126 for character in bearer_value)
        ):
            raise ValueError("authorization header value must be a bounded Bearer value")

    def __repr__(self) -> str:
        return "ProviderAuthorization(configured=True)"


@dataclass(frozen=True, slots=True)
class ProviderTimeoutPolicy:
    connect_seconds: float
    write_seconds: float
    read_seconds: float
    pool_seconds: float
    absolute_deadline_seconds: float

    def __post_init__(self) -> None:
        for field_name in (
            "connect_seconds",
            "write_seconds",
            "read_seconds",
            "pool_seconds",
            "absolute_deadline_seconds",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
                or value > MAX_TIMEOUT_SECONDS
            ):
                raise ValueError(
                    f"{field_name} must be finite, positive, and at most "
                    f"{MAX_TIMEOUT_SECONDS} seconds"
                )


@dataclass(frozen=True, slots=True)
class ProviderTransportObservation:
    response_headers_received: bool
    response_headers_at: str | None
    response_headers_elapsed_ms: int | None
    http_status_code: int | None
    response_body_started: bool
    first_body_at: str | None
    first_body_elapsed_ms: int | None
    last_body_at: str | None
    last_body_elapsed_ms: int | None
    decoded_body_bytes_received: int
    provider_started_at: str
    provider_finished_at: str
    elapsed_ms: int
    transport_failure_kind: ProviderTransportFailureKind | None
    trust_env_enabled: bool
    proxy_environment_present: bool


@dataclass(frozen=True, slots=True, repr=False)
class ProviderTransportResponse:
    outcome: ProviderAttemptOutcome
    status_code: int
    body: bytes = field(repr=False)
    observation: ProviderTransportObservation

    def __repr__(self) -> str:
        return (
            "ProviderTransportResponse("
            f"outcome={self.outcome!r}, status_code={self.status_code!r}, "
            f"body_bytes={len(self.body)!r}, observation={self.observation!r})"
        )


class ProviderTransportError(ByteMCPError):
    def __init__(
        self,
        *,
        attempt_outcome: ProviderAttemptOutcome,
        transport_failure_kind: ProviderTransportFailureKind,
        transport_observation: ProviderTransportObservation,
    ) -> None:
        self.attempt_outcome = attempt_outcome
        self.transport_failure_kind = transport_failure_kind
        self.transport_observation = transport_observation
        super().__init__(
            f"provider transport failed: {attempt_outcome.value}/{transport_failure_kind.value}"
        )


class _ResponseBodyLimitExceeded(Exception):
    pass


class _TransportTracker:
    """Accumulate only bounded transport metadata for one provider call."""

    def __init__(
        self,
        transmission_context: ProviderTransmissionContext,
        *,
        trust_env_enabled: bool,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        environment = os.environ if environ is None else environ
        self._provider_started_at = transmission_context.provider_started_at
        self._trust_env_enabled = trust_env_enabled
        self._proxy_environment_present = any(key in environment for key in _PROXY_ENV_KEYS)
        self._response_headers_at: str | None = None
        self._response_headers_elapsed_ms: int | None = None
        self._http_status_code: int | None = None
        self._first_body_at: str | None = None
        self._first_body_elapsed_ms: int | None = None
        self._last_body_at: str | None = None
        self._last_body_elapsed_ms: int | None = None
        self._decoded_body_bytes_received = 0

    def record_response_headers(
        self, *, response_headers_at: str, elapsed_ms: int, status_code: int
    ) -> None:
        self._response_headers_at = response_headers_at
        self._response_headers_elapsed_ms = elapsed_ms
        self._http_status_code = status_code

    def record_body_chunk(self, *, observed_at: str, elapsed_ms: int, size: int) -> None:
        if self._first_body_at is None:
            self._first_body_at = observed_at
            self._first_body_elapsed_ms = elapsed_ms
        self._last_body_at = observed_at
        self._last_body_elapsed_ms = elapsed_ms
        self._decoded_body_bytes_received += size

    def finish(
        self,
        *,
        provider_finished_at: str,
        elapsed_ms: int,
        transport_failure_kind: ProviderTransportFailureKind | None = None,
    ) -> ProviderTransportObservation:
        return ProviderTransportObservation(
            response_headers_received=self._response_headers_at is not None,
            response_headers_at=self._response_headers_at,
            response_headers_elapsed_ms=self._response_headers_elapsed_ms,
            http_status_code=self._http_status_code,
            response_body_started=self._first_body_at is not None,
            first_body_at=self._first_body_at,
            first_body_elapsed_ms=self._first_body_elapsed_ms,
            last_body_at=self._last_body_at,
            last_body_elapsed_ms=self._last_body_elapsed_ms,
            decoded_body_bytes_received=self._decoded_body_bytes_received,
            provider_started_at=self._provider_started_at,
            provider_finished_at=provider_finished_at,
            elapsed_ms=elapsed_ms,
            transport_failure_kind=transport_failure_kind,
            trust_env_enabled=self._trust_env_enabled,
            proxy_environment_present=self._proxy_environment_present,
        )


async def execute_once(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    authorization: ProviderAuthorization,
    timeout_policy: ProviderTimeoutPolicy,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderTransportResponse:
    """Execute one prepared HTTP request with zero retry or fallback behavior."""

    if not isinstance(prepared_request, PreparedProviderRequest):
        raise ValueError("prepared_request is invalid")
    if not isinstance(transmission_context, ProviderTransmissionContext):
        raise ValueError("transmission_context is invalid")
    if not isinstance(authorization, ProviderAuthorization):
        raise ValueError("authorization is invalid")
    if not isinstance(timeout_policy, ProviderTimeoutPolicy):
        raise ValueError("timeout_policy is invalid")
    if transmission_context.expected_request_sha256 != prepared_request.request_sha256:
        raise ValueError("expected request_sha256 does not match prepared request_sha256")

    headers = {
        "Authorization": authorization.authorization_header_value,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    tracker = _TransportTracker(transmission_context, trust_env_enabled=_TRUST_ENV)
    started_monotonic_ns = monotonic_ns()
    failure: tuple[ProviderAttemptOutcome, ProviderTransportFailureKind] | None = None

    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                connect=timeout_policy.connect_seconds,
                read=timeout_policy.read_seconds,
                write=timeout_policy.write_seconds,
                pool=timeout_policy.pool_seconds,
            ),
            follow_redirects=False,
            trust_env=_TRUST_ENV,
        ) as client:
            async with asyncio.timeout(timeout_policy.absolute_deadline_seconds):
                body = bytearray()
                async with client.stream(
                    prepared_request.method,
                    prepared_request.target_origin + prepared_request.endpoint_path,
                    headers=headers,
                    content=prepared_request.body_bytes,
                ) as response:
                    tracker.record_response_headers(
                        response_headers_at=_utc_now(),
                        elapsed_ms=_elapsed_ms(started_monotonic_ns),
                        status_code=response.status_code,
                    )
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        tracker.record_body_chunk(
                            observed_at=_utc_now(),
                            elapsed_ms=_elapsed_ms(started_monotonic_ns),
                            size=len(chunk),
                        )
                        if len(body) + len(chunk) > MAX_RESPONSE_BODY_BYTES:
                            raise _ResponseBodyLimitExceeded
                        body.extend(chunk)

                observation = tracker.finish(
                    provider_finished_at=_utc_now(),
                    elapsed_ms=_elapsed_ms(started_monotonic_ns),
                )
                outcome = (
                    ProviderAttemptOutcome.COMPLETED
                    if 200 <= response.status_code < 300
                    else ProviderAttemptOutcome.REJECTED
                )
                return ProviderTransportResponse(
                    outcome=outcome,
                    status_code=response.status_code,
                    body=bytes(body),
                    observation=observation,
                )
    except TimeoutError:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.ABSOLUTE_DEADLINE,
        )
    except httpx.ConnectTimeout:
        failure = (
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_TIMEOUT,
        )
    except httpx.ConnectError:
        failure = (
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_ERROR,
        )
    except httpx.PoolTimeout:
        failure = (
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.POOL_TIMEOUT,
        )
    except httpx.ReadTimeout:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_TIMEOUT,
        )
    except httpx.ReadError:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_ERROR,
        )
    except httpx.WriteTimeout:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_TIMEOUT,
        )
    except httpx.WriteError:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_ERROR,
        )
    except httpx.RemoteProtocolError:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        )
    except _ResponseBodyLimitExceeded:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.HTTP_TRANSPORT_ERROR,
        )
    except httpx.HTTPError:
        failure = (
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.HTTP_TRANSPORT_ERROR,
        )

    if failure is None:
        raise RuntimeError("unreachable provider transport state")

    attempt_outcome, transport_failure_kind = failure
    observation = tracker.finish(
        provider_finished_at=_utc_now(),
        elapsed_ms=_elapsed_ms(started_monotonic_ns),
        transport_failure_kind=transport_failure_kind,
    )
    raise ProviderTransportError(
        attempt_outcome=attempt_outcome,
        transport_failure_kind=transport_failure_kind,
        transport_observation=observation,
    )
