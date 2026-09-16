"""Exactly-once governed NVIDIA query execution."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from byte_mcp.nvidia.chat import NvidiaChatResult, execute_prepared_nvidia_chat
from byte_mcp.nvidia.errors import NvidiaChatError, NvidiaErrorCode, NvidiaPlatformError
from byte_mcp.nvidia.models import NVIDIA_DEFAULT_QUERY_MODEL, NVIDIA_MODELS
from byte_mcp.nvidia.query_audit import (
    NvidiaQueryAuditEvent,
    NvidiaQueryAuditRecorder,
    record_nvidia_query_audit,
)
from byte_mcp.nvidia.query_protocol import PreparedNvidiaQuery, prepare_nvidia_query_request
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers import (
    PreparedProviderRequest,
    ProviderAttemptOutcome,
    ProviderTransmissionContext,
    ProviderTransportError,
)

MAX_QUERY_RESPONSE_CHARS = 64_000


@dataclass(frozen=True, slots=True)
class NvidiaQueryResult:
    """Bounded user-visible result with response text excluded from repr."""

    model: str
    provider_model_id: str
    response: str
    request_sha256: str
    finish_reason: str | None
    response_id: str | None
    usage: Mapping[str, int] | None

    def __repr__(self) -> str:
        return (
            "NvidiaQueryResult("
            f"model={self.model!r}, "
            f"provider_model_id={self.provider_model_id!r}, "
            f"request_sha256={self.request_sha256!r}, "
            f"finish_reason={self.finish_reason!r}, "
            f"response_id={self.response_id!r}, "
            f"has_usage={self.usage is not None})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "provider_model_id": self.provider_model_id,
            "response": self.response,
            "request_sha256": self.request_sha256,
            "finish_reason": self.finish_reason,
            "response_id": self.response_id,
            "usage": None if self.usage is None else dict(self.usage),
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _started(attempt_outcome: ProviderAttemptOutcome) -> bool:
    return attempt_outcome is not ProviderAttemptOutcome.NOT_SENT


def _chat_error_code(error: NvidiaChatError) -> NvidiaErrorCode:
    kind = error.kind.value
    if kind in {"AUTHENTICATION", "PERMISSION"}:
        return NvidiaErrorCode.AUTHENTICATION_FAILED
    if kind == "RATE_LIMIT":
        return NvidiaErrorCode.RATE_LIMITED
    if kind in {"REQUEST", "REQUEST_TOO_LARGE"}:
        return NvidiaErrorCode.INVALID_REQUEST
    if kind == "PROTOCOL":
        return NvidiaErrorCode.RESPONSE_INVALID
    if kind == "CONFIGURATION":
        return NvidiaErrorCode.CREDENTIAL_UNAVAILABLE
    return NvidiaErrorCode.PROVIDER_REJECTED


def _platform_error(
    *,
    code: NvidiaErrorCode,
    message: str,
    provider_started: bool,
    status_code: int | None = None,
) -> NvidiaPlatformError:
    return NvidiaPlatformError(
        code=code,
        message=message,
        provider_started=provider_started,
        safe_to_invoke_fresh=True,
        status_code=status_code,
    )


def _usage_view(usage: object | None) -> Mapping[str, int] | None:
    if usage is None:
        return None
    fields = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _platform_error(
                code=NvidiaErrorCode.RESPONSE_INVALID,
                message="NVIDIA response metadata is invalid",
                provider_started=True,
            )
        fields[name] = value
    return MappingProxyType(fields)


def _safe_requested_alias(model: str | None) -> str | None:
    if model is None:
        return NVIDIA_DEFAULT_QUERY_MODEL
    if model in NVIDIA_MODELS:
        return model
    return None


def _duration_ms(started_ns: int) -> int:
    return max(0, int((time.monotonic_ns() - started_ns) / 1_000_000))


def _audit_event(
    audit: NvidiaQueryAuditRecorder | None,
    *,
    started_ns: int,
    prepared: PreparedNvidiaQuery | None,
    requested_model: str | None,
    provider_started: bool,
    outcome: str,
    error_code: str | None = None,
    status_code: int | None = None,
    finish_reason: str | None = None,
    response_bytes: int | None = None,
) -> None:
    record_nvidia_query_audit(
        audit,
        NvidiaQueryAuditEvent(
            surface="query",
            model_alias=(
                prepared.model if prepared is not None else _safe_requested_alias(requested_model)
            ),
            provider_model_id=(prepared.provider_model_id if prepared is not None else None),
            request_sha256=(prepared.request.request_sha256 if prepared is not None else None),
            provider_started=provider_started,
            status_code=status_code,
            finish_reason=finish_reason,
            request_bytes=(len(prepared.request.body_bytes) if prepared is not None else None),
            response_bytes=response_bytes,
            duration_ms=_duration_ms(started_ns),
            outcome=outcome,
            error_code=error_code,
        ),
    )


async def execute_nvidia_query(
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    settings_loader: Callable[[], NvidiaHostedSettings] | None = None,
    executor: Callable[
        [PreparedProviderRequest, ProviderTransmissionContext, NvidiaHostedSettings],
        Awaitable[NvidiaChatResult],
    ]
    | None = None,
    now: Callable[[], datetime] = _utc_now,
    audit: NvidiaQueryAuditRecorder | None = None,
) -> NvidiaQueryResult:
    """Execute one fresh governed query without replay or substitution."""
    started_ns = time.monotonic_ns()
    prepared: PreparedNvidiaQuery | None = None

    try:
        prepared = prepare_nvidia_query_request(prompt, model=model, system_prompt=system_prompt)
    except NvidiaPlatformError as error:
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=None,
            requested_model=model,
            provider_started=False,
            outcome="error",
            error_code=error.code.value,
            status_code=error.status_code,
        )
        raise

    loader = settings_loader or NvidiaHostedSettings.load
    settings = loader()
    if not isinstance(settings, NvidiaHostedSettings):
        error = _platform_error(
            code=NvidiaErrorCode.CREDENTIAL_UNAVAILABLE,
            message="NVIDIA hosted settings are invalid",
            provider_started=False,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=False,
            outcome="error",
            error_code=error.code.value,
        )
        raise error
    if settings.api_key is None:
        error = _platform_error(
            code=NvidiaErrorCode.CREDENTIAL_UNAVAILABLE,
            message="NVIDIA API key is not configured",
            provider_started=False,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=False,
            outcome="error",
            error_code=error.code.value,
        )
        raise error

    started_at = now()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        error = NvidiaPlatformError(
            code=NvidiaErrorCode.INVALID_REQUEST,
            message="query clock is invalid",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=False,
            outcome="error",
            error_code=error.code.value,
        )
        raise error

    context = ProviderTransmissionContext(
        provider_started_at=started_at.astimezone(UTC).isoformat(),
        expected_request_sha256=prepared.request.request_sha256,
    )
    execute = executor or execute_prepared_nvidia_chat

    try:
        result = await execute(prepared.request, context, settings)
    except NvidiaChatError as error:
        platform_error = _platform_error(
            code=_chat_error_code(error),
            message="NVIDIA query failed",
            provider_started=_started(error.attempt_outcome),
            status_code=error.transport_observation.http_status_code,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=platform_error.provider_started,
            outcome="error",
            error_code=platform_error.code.value,
            status_code=platform_error.status_code,
        )
        raise platform_error from error
    except ProviderTransportError as error:
        platform_error = _platform_error(
            code=NvidiaErrorCode.TRANSPORT_FAILED,
            message="NVIDIA transport failed",
            provider_started=_started(error.attempt_outcome),
            status_code=error.transport_observation.http_status_code,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=platform_error.provider_started,
            outcome="error",
            error_code=platform_error.code.value,
            status_code=platform_error.status_code,
        )
        raise platform_error from error

    if (
        result.model_id != prepared.provider_model_id
        or result.request_sha256 != prepared.request.request_sha256
        or result.payload_sha256 != prepared.request.payload_sha256
    ):
        error = _platform_error(
            code=NvidiaErrorCode.RESPONSE_INVALID,
            message="NVIDIA response identity is invalid",
            provider_started=True,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=True,
            outcome="error",
            error_code=error.code.value,
        )
        raise error

    response = result.content
    if not isinstance(response, str) or not response:
        error = _platform_error(
            code=NvidiaErrorCode.RESPONSE_INVALID,
            message="NVIDIA response content is invalid",
            provider_started=True,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=True,
            outcome="error",
            error_code=error.code.value,
        )
        raise error

    response_size = len(response.encode("utf-8"))
    if len(response) > MAX_QUERY_RESPONSE_CHARS:
        error = _platform_error(
            code=NvidiaErrorCode.RESPONSE_TOO_LARGE,
            message="NVIDIA response is too large",
            provider_started=True,
        )
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=True,
            outcome="error",
            error_code=error.code.value,
            response_bytes=response_size,
        )
        raise error

    try:
        usage = _usage_view(result.usage)
    except NvidiaPlatformError as error:
        _audit_event(
            audit,
            started_ns=started_ns,
            prepared=prepared,
            requested_model=model,
            provider_started=True,
            outcome="error",
            error_code=error.code.value,
            response_bytes=response_size,
        )
        raise

    query_result = NvidiaQueryResult(
        model=prepared.model,
        provider_model_id=prepared.provider_model_id,
        response=response,
        request_sha256=prepared.request.request_sha256,
        finish_reason=result.finish_reason,
        response_id=result.response_id,
        usage=usage,
    )
    _audit_event(
        audit,
        started_ns=started_ns,
        prepared=prepared,
        requested_model=model,
        provider_started=True,
        outcome="allowed",
        finish_reason=result.finish_reason,
        response_bytes=response_size,
    )
    return query_result
