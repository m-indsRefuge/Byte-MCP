"""Bounded NVIDIA hosted chat request and response handling."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from byte_mcp.providers import (
    PreparedProviderRequest,
    ProviderAttemptOutcome,
    ProviderAuthorization,
    ProviderTransmissionContext,
    ProviderTransportObservation,
    ProviderTransportResponse,
    execute_once,
    prepare_provider_request,
)

from .errors import NvidiaChatError, NvidiaChatFailureKind
from .registry import NVIDIA_PROVIDER
from .settings import NvidiaHostedSettings

NVIDIA_CHAT_TARGET_ORIGIN = "https://integrate.api.nvidia.com"
NVIDIA_CHAT_ENDPOINT_PATH = "/v1/chat/completions"
_ALLOWED_CHAT_ROLES = frozenset({"system", "user", "assistant"})
_FINISH_REASON = re.compile(r"[A-Za-z0-9._-]{0,64}\Z")
_MAX_USAGE_COUNTER = 2_147_483_647
_MAX_RESPONSE_ID_CHARS = 256


@dataclass(frozen=True, slots=True)
class NvidiaChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in _ALLOWED_CHAT_ROLES:
            raise ValueError("message role is invalid")
        if not isinstance(self.content, str):
            raise ValueError("message content must be a string")


@dataclass(frozen=True, slots=True)
class NvidiaChatUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaChatResult:
    model_id: str
    content: str = field(repr=False)
    finish_reason: str | None
    response_id: str | None
    usage: NvidiaChatUsage | None
    request_sha256: str
    payload_sha256: str
    transport_observation: ProviderTransportObservation

    def __repr__(self) -> str:
        return (
            "NvidiaChatResult("
            f"model_id={self.model_id!r}, content_chars={len(self.content)!r}, "
            f"finish_reason={self.finish_reason!r}, response_id={self.response_id!r}, "
            f"usage={self.usage!r}, request_sha256={self.request_sha256!r}, "
            f"payload_sha256={self.payload_sha256!r}, "
            f"transport_observation={self.transport_observation!r})"
        )


def _normalize_message(value: NvidiaChatMessage | Mapping[str, object]) -> NvidiaChatMessage:
    if isinstance(value, NvidiaChatMessage):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("message must be an NvidiaChatMessage or mapping")
    if set(value) != {"role", "content"}:
        raise ValueError("message fields must be exactly role and content")
    return NvidiaChatMessage(
        role=value["role"],  # type: ignore[arg-type]
        content=value["content"],  # type: ignore[arg-type]
    )


def _validate_float_parameter(
    value: object,
    *,
    name: str,
    low: float,
    high: float,
) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < low
        or value > high
    ):
        raise ValueError(f"{name} is invalid")
    return value


def prepare_nvidia_chat_request(
    *,
    model_id: str,
    messages: Sequence[NvidiaChatMessage | Mapping[str, object]],
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 1024,
) -> PreparedProviderRequest:
    """Prepare one credential-free, non-streaming NVIDIA chat request."""

    if (
        isinstance(messages, (str, bytes, bytearray, Mapping))
        or not isinstance(messages, Sequence)
        or not messages
    ):
        raise ValueError("messages must be a non-empty sequence")

    normalized_messages = tuple(_normalize_message(message) for message in messages)
    validated_temperature = _validate_float_parameter(
        temperature,
        name="temperature",
        low=0.0,
        high=2.0,
    )
    validated_top_p = _validate_float_parameter(
        top_p,
        name="top_p",
        low=0.0,
        high=1.0,
    )
    if validated_top_p <= 0:
        raise ValueError("top_p is invalid")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= 65_536
    ):
        raise ValueError("max_tokens is invalid")

    body = {
        "max_tokens": max_tokens,
        "messages": [
            {"content": message.content, "role": message.role}
            for message in normalized_messages
        ],
        "model": model_id,
        "n": 1,
        "stream": False,
        "temperature": validated_temperature,
        "top_p": validated_top_p,
    }
    return prepare_provider_request(
        provider_id=NVIDIA_PROVIDER.provider_id,
        method="POST",
        target_origin=NVIDIA_CHAT_TARGET_ORIGIN,
        endpoint_path=NVIDIA_CHAT_ENDPOINT_PATH,
        model_id=model_id,
        body=body,
    )


def _chat_error(
    prepared_request: PreparedProviderRequest,
    transport_response: ProviderTransportResponse,
    *,
    kind: NvidiaChatFailureKind,
) -> NvidiaChatError:
    return NvidiaChatError(
        kind=kind,
        attempt_outcome=transport_response.outcome,
        transport_observation=transport_response.observation,
        request_sha256=prepared_request.request_sha256,
    )


def _protocol_error(
    prepared_request: PreparedProviderRequest,
    transport_response: ProviderTransportResponse,
) -> NvidiaChatError:
    return _chat_error(
        prepared_request,
        transport_response,
        kind=NvidiaChatFailureKind.PROTOCOL,
    )


def classify_nvidia_chat_rejection(
    prepared_request: PreparedProviderRequest,
    transport_response: ProviderTransportResponse,
) -> NvidiaChatError:
    """Classify one fully received NVIDIA HTTP rejection using bounded status metadata."""

    if not isinstance(prepared_request, PreparedProviderRequest):
        raise ValueError("prepared_request is invalid")
    if not isinstance(transport_response, ProviderTransportResponse):
        raise ValueError("transport_response is invalid")
    if transport_response.outcome is not ProviderAttemptOutcome.REJECTED:
        raise ValueError("transport_response outcome must be REJECTED")

    status_code = transport_response.status_code
    if not 300 <= status_code <= 599:
        raise ValueError("REJECTED transport response must have a 3xx, 4xx, or 5xx status")
    if 300 <= status_code <= 399:
        kind = NvidiaChatFailureKind.REDIRECT_REJECTED
    elif status_code == 400 or status_code == 422:
        kind = NvidiaChatFailureKind.REQUEST
    elif status_code == 401:
        kind = NvidiaChatFailureKind.AUTHENTICATION
    elif status_code == 403:
        kind = NvidiaChatFailureKind.PERMISSION
    elif status_code == 404:
        kind = NvidiaChatFailureKind.MODEL_OR_ENDPOINT_UNAVAILABLE
    elif status_code == 413:
        kind = NvidiaChatFailureKind.REQUEST_TOO_LARGE
    elif status_code == 429:
        kind = NvidiaChatFailureKind.RATE_LIMIT
    elif 500 <= status_code <= 599:
        kind = NvidiaChatFailureKind.PROVIDER_UNAVAILABLE
    else:
        kind = NvidiaChatFailureKind.REQUEST
    return _chat_error(prepared_request, transport_response, kind=kind)


def _validated_usage(value: object) -> NvidiaChatUsage:
    if not isinstance(value, Mapping):
        raise ValueError("usage is invalid")

    counters: dict[str, int | None] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        counter = value.get(name)
        if counter is not None and (
            isinstance(counter, bool)
            or not isinstance(counter, int)
            or not 0 <= counter <= _MAX_USAGE_COUNTER
        ):
            raise ValueError("usage counter is invalid")
        counters[name] = counter
    return NvidiaChatUsage(**counters)  # type: ignore[arg-type]


def _validated_response_id(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > _MAX_RESPONSE_ID_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("response id is invalid")
    return value


def _validated_finish_reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _FINISH_REASON.fullmatch(value) is None:
        raise ValueError("finish_reason is invalid")
    return value


def parse_nvidia_chat_response(
    prepared_request: PreparedProviderRequest,
    transport_response: ProviderTransportResponse,
) -> NvidiaChatResult:
    """Parse one fully received successful NVIDIA chat response into bounded state."""

    if not isinstance(prepared_request, PreparedProviderRequest):
        raise ValueError("prepared_request is invalid")
    if not isinstance(transport_response, ProviderTransportResponse):
        raise ValueError("transport_response is invalid")
    if (
        transport_response.outcome is not ProviderAttemptOutcome.COMPLETED
        or not 200 <= transport_response.status_code <= 299
    ):
        raise ValueError("transport_response must be a COMPLETED 2xx response")

    try:
        decoded = transport_response.body.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    try:
        if not isinstance(payload, Mapping):
            raise ValueError("response is invalid")
        model_id = payload.get("model")
        if not isinstance(model_id, str) or model_id != prepared_request.model_id:
            raise ValueError("response model is invalid")

        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("choices are invalid")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ValueError("choice is invalid")
        index = choice.get("index")
        if isinstance(index, bool) or index != 0:
            raise ValueError("choice index is invalid")

        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ValueError("message is invalid")
        if message.get("role") != "assistant":
            raise ValueError("message role is invalid")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("message content is invalid")

        if "finish_reason" not in choice:
            raise ValueError("finish_reason is missing")
        finish_reason = _validated_finish_reason(choice.get("finish_reason"))
        response_id = _validated_response_id(payload.get("id"))
        usage = _validated_usage(payload["usage"]) if "usage" in payload else None
    except (KeyError, TypeError, ValueError):
        raise _protocol_error(prepared_request, transport_response) from None

    return NvidiaChatResult(
        model_id=model_id,
        content=content,
        finish_reason=finish_reason,
        response_id=response_id,
        usage=usage,
        request_sha256=prepared_request.request_sha256,
        payload_sha256=prepared_request.payload_sha256,
        transport_observation=transport_response.observation,
    )


def _not_sent_observation(
    transmission_context: ProviderTransmissionContext,
) -> ProviderTransportObservation:
    finished_at = datetime.now(UTC).isoformat()
    return ProviderTransportObservation(
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
        provider_started_at=transmission_context.provider_started_at,
        provider_finished_at=finished_at,
        elapsed_ms=0,
        transport_failure_kind=None,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


async def execute_prepared_nvidia_chat(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    settings: NvidiaHostedSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> NvidiaChatResult:
    """Execute one already-prepared NVIDIA hosted chat request with zero retry."""

    if not isinstance(prepared_request, PreparedProviderRequest):
        raise ValueError("prepared_request is invalid")
    if not isinstance(transmission_context, ProviderTransmissionContext):
        raise ValueError("transmission_context is invalid")
    if not isinstance(settings, NvidiaHostedSettings):
        raise ValueError("settings is invalid")

    if settings.api_key is None:
        raise NvidiaChatError(
            kind=NvidiaChatFailureKind.CONFIGURATION,
            attempt_outcome=ProviderAttemptOutcome.NOT_SENT,
            transport_observation=_not_sent_observation(transmission_context),
            request_sha256=prepared_request.request_sha256,
        )

    transport_response = await execute_once(
        prepared_request,
        transmission_context,
        ProviderAuthorization(f"Bearer {settings.api_key}"),
        settings.chat_timeout_policy,
        transport=transport,
    )
    if transport_response.outcome is ProviderAttemptOutcome.REJECTED:
        raise classify_nvidia_chat_rejection(prepared_request, transport_response)
    return parse_nvidia_chat_response(prepared_request, transport_response)
