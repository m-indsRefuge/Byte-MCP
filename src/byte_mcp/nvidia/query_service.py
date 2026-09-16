"""Exactly-once governed NVIDIA query execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from byte_mcp.nvidia.chat import (
    NvidiaChatResult,
    execute_prepared_nvidia_chat,
)
from byte_mcp.nvidia.errors import (
    NvidiaChatError,
    NvidiaErrorCode,
    NvidiaPlatformError,
)
from byte_mcp.nvidia.query_protocol import prepare_nvidia_query_request
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
) -> NvidiaPlatformError:
    return NvidiaPlatformError(
        code=code,
        message=message,
        provider_started=provider_started,
        safe_to_invoke_fresh=True,
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
) -> NvidiaQueryResult:
    """Execute one fresh governed query with no retry or fallback."""
    prepared = prepare_nvidia_query_request(
        prompt,
        model=model,
        system_prompt=system_prompt,
    )

    loader = settings_loader or NvidiaHostedSettings.load
    settings = loader()
    if not isinstance(settings, NvidiaHostedSettings):
        raise _platform_error(
            code=NvidiaErrorCode.CREDENTIAL_UNAVAILABLE,
            message="NVIDIA hosted settings are invalid",
            provider_started=False,
        )
    if settings.api_key is None:
        raise _platform_error(
            code=NvidiaErrorCode.CREDENTIAL_UNAVAILABLE,
            message="NVIDIA API key is not configured",
            provider_started=False,
        )

    started_at = now()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise NvidiaPlatformError(
            code=NvidiaErrorCode.INVALID_REQUEST,
            message="query clock is invalid",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )

    context = ProviderTransmissionContext(
        provider_started_at=started_at.astimezone(UTC).isoformat(),
        expected_request_sha256=prepared.request.request_sha256,
    )
    execute = executor or execute_prepared_nvidia_chat

    try:
        result = await execute(prepared.request, context, settings)
    except NvidiaChatError as error:
        raise _platform_error(
            code=_chat_error_code(error),
            message="NVIDIA query failed",
            provider_started=_started(error.attempt_outcome),
        ) from error
    except ProviderTransportError as error:
        raise _platform_error(
            code=NvidiaErrorCode.TRANSPORT_FAILED,
            message="NVIDIA transport failed",
            provider_started=_started(error.attempt_outcome),
        ) from error

    if (
        result.model_id != prepared.provider_model_id
        or result.request_sha256 != prepared.request.request_sha256
        or result.payload_sha256 != prepared.request.payload_sha256
    ):
        raise _platform_error(
            code=NvidiaErrorCode.RESPONSE_INVALID,
            message="NVIDIA response identity is invalid",
            provider_started=True,
        )

    response = result.content
    if not isinstance(response, str) or not response:
        raise _platform_error(
            code=NvidiaErrorCode.RESPONSE_INVALID,
            message="NVIDIA response content is invalid",
            provider_started=True,
        )
    if len(response) > MAX_QUERY_RESPONSE_CHARS:
        raise _platform_error(
            code=NvidiaErrorCode.RESPONSE_TOO_LARGE,
            message="NVIDIA response is too large",
            provider_started=True,
        )

    return NvidiaQueryResult(
        model=prepared.model,
        provider_model_id=prepared.provider_model_id,
        response=response,
        request_sha256=prepared.request.request_sha256,
        finish_reason=result.finish_reason,
        response_id=result.response_id,
        usage=_usage_view(result.usage),
    )
