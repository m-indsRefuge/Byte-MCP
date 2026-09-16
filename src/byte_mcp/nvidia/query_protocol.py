"""Provider-free governed NVIDIA query request construction."""

from __future__ import annotations

from dataclasses import dataclass

from byte_mcp.nvidia.chat import NvidiaChatMessage, prepare_nvidia_chat_request
from byte_mcp.nvidia.errors import NvidiaErrorCode, NvidiaPlatformError
from byte_mcp.nvidia.models import resolve_query_model
from byte_mcp.providers import PreparedProviderRequest, prepare_provider_request

MAX_QUERY_PROMPT_CHARS = 32_000
MAX_QUERY_SYSTEM_PROMPT_CHARS = 16_000


@dataclass(frozen=True, slots=True)
class PreparedNvidiaQuery:
    """One canonical governed NVIDIA query request."""

    model: str
    provider_model_id: str
    request: PreparedProviderRequest


def _validate_text(value: object, *, field: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise NvidiaPlatformError(
            code=NvidiaErrorCode.INVALID_REQUEST,
            message=f"{field} is invalid",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )
    normalized = value.strip()
    if not normalized or len(value) > max_chars:
        raise NvidiaPlatformError(
            code=NvidiaErrorCode.INVALID_REQUEST,
            message=f"{field} is invalid",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )
    return value


def _resolve_query_model(alias: str | None):
    try:
        return resolve_query_model(alias)
    except ValueError as exc:
        message = str(exc)
        code = (
            NvidiaErrorCode.MODEL_NOT_ENABLED
            if "not enabled for query" in message
            else NvidiaErrorCode.MODEL_NOT_ALLOWED
        )
        raise NvidiaPlatformError(
            code=code,
            message=message,
            provider_started=False,
            safe_to_invoke_fresh=True,
        ) from exc


def prepare_nvidia_query_request(
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
) -> PreparedNvidiaQuery:
    """Prepare one deterministic provider request without loading credentials."""
    prompt_text = _validate_text(
        prompt,
        field="prompt",
        max_chars=MAX_QUERY_PROMPT_CHARS,
    )
    if system_prompt is None:
        system_text = None
    else:
        system_text = _validate_text(
            system_prompt,
            field="system_prompt",
            max_chars=MAX_QUERY_SYSTEM_PROMPT_CHARS,
        )

    definition = _resolve_query_model(model)
    profile = definition.query_profile
    if profile is None:
        raise NvidiaPlatformError(
            code=NvidiaErrorCode.MODEL_NOT_ENABLED,
            message="model is not enabled for query",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )

    messages: list[NvidiaChatMessage] = []
    if system_text is not None:
        messages.append(NvidiaChatMessage(role="system", content=system_text))
    messages.append(NvidiaChatMessage(role="user", content=prompt_text))
    message_tuple = tuple(messages)

    template = prepare_nvidia_chat_request(
        model_id=definition.provider_model_id,
        messages=message_tuple,
        max_tokens=8,
    )

    body: dict[str, object] = {
        "max_tokens": profile.max_tokens,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in message_tuple
        ],
        "model": definition.provider_model_id,
        "n": 1,
        "stream": False,
        "temperature": profile.temperature,
        "top_p": profile.top_p,
    }
    if profile.chat_template_kwargs:
        body["chat_template_kwargs"] = dict(profile.chat_template_kwargs)
    if profile.reasoning_effort is not None:
        body["reasoning_effort"] = profile.reasoning_effort
    if profile.seed is not None:
        body["seed"] = profile.seed

    request = prepare_provider_request(
        provider_id=template.provider_id,
        method=template.method,
        target_origin=template.target_origin,
        endpoint_path=template.endpoint_path,
        model_id=definition.provider_model_id,
        body=body,
    )

    return PreparedNvidiaQuery(
        model=definition.alias,
        provider_model_id=definition.provider_model_id,
        request=request,
    )
