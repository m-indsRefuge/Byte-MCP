"""Bounded NVIDIA hosted chat request preparation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from byte_mcp.providers import PreparedProviderRequest, prepare_provider_request

from .registry import NVIDIA_PROVIDER

NVIDIA_CHAT_TARGET_ORIGIN = "https://integrate.api.nvidia.com"
NVIDIA_CHAT_ENDPOINT_PATH = "/v1/chat/completions"
_ALLOWED_CHAT_ROLES = frozenset({"system", "user", "assistant"})


@dataclass(frozen=True, slots=True)
class NvidiaChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in _ALLOWED_CHAT_ROLES:
            raise ValueError("message role is invalid")
        if not isinstance(self.content, str):
            raise ValueError("message content must be a string")


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
