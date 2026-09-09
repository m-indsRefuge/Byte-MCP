"""Provider-neutral transport contracts and metadata tracking."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from byte_mcp.errors import ByteMCPError

from .outcomes import ProviderAttemptOutcome, ProviderTransportFailureKind

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


def _require_aware_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")


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
