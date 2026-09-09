from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from byte_mcp.nvidia import (
    NVIDIA_CHAT_ENDPOINT_PATH,
    NVIDIA_CHAT_TARGET_ORIGIN,
    NVIDIA_PROVIDER,
    NvidiaChatMessage,
    prepare_nvidia_chat_request,
)

MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_prepare_chat_request_builds_exact_non_streaming_text_body() -> None:
    prepared = prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[NvidiaChatMessage(role="user", content="hello")],
    )

    assert prepared.provider_id == NVIDIA_PROVIDER.provider_id
    assert prepared.method == "POST"
    assert prepared.target_origin == NVIDIA_CHAT_TARGET_ORIGIN
    assert prepared.endpoint_path == NVIDIA_CHAT_ENDPOINT_PATH
    assert prepared.model_id == MODEL_ID
    assert json.loads(prepared.body_bytes) == {
        "max_tokens": 1024,
        "messages": [{"content": "hello", "role": "user"}],
        "model": MODEL_ID,
        "n": 1,
        "stream": False,
        "temperature": 0.2,
        "top_p": 0.95,
    }


def test_chat_message_is_immutable() -> None:
    message = NvidiaChatMessage(role="user", content="hello")
    with pytest.raises(FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("role", ["system", "user", "assistant"])
def test_prepare_chat_request_accepts_only_frozen_text_roles(role: str) -> None:
    prepared = prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[{"role": role, "content": ""}],
    )
    body = json.loads(prepared.body_bytes)
    assert body["messages"] == [{"content": "", "role": role}]


@pytest.mark.parametrize("role", ["tool", "function", "developer", "USER", ""])
def test_prepare_chat_request_rejects_unsupported_roles(role: str) -> None:
    with pytest.raises(ValueError, match="role"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": role, "content": "hello"}],
        )


def test_prepare_chat_request_rejects_empty_message_sequence() -> None:
    with pytest.raises(ValueError, match="messages"):
        prepare_nvidia_chat_request(model_id=MODEL_ID, messages=[])


@pytest.mark.parametrize("messages", ["hello", b"hello", {"role": "user", "content": "hello"}])
def test_prepare_chat_request_rejects_non_sequence_message_container(messages: object) -> None:
    with pytest.raises(ValueError, match="messages"):
        prepare_nvidia_chat_request(model_id=MODEL_ID, messages=messages)  # type: ignore[arg-type]


def test_prepare_chat_request_rejects_unknown_message_fields() -> None:
    with pytest.raises(ValueError, match="fields"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": "hello", "name": "extra"}],
        )


@pytest.mark.parametrize("content", [None, 1, True, ["text"]])
def test_prepare_chat_request_requires_string_content(content: object) -> None:
    with pytest.raises(ValueError, match="content"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": content}],
        )


@pytest.mark.parametrize("temperature", [-0.01, 2.01, True, float("nan"), float("inf")])
def test_prepare_chat_request_rejects_invalid_temperature(temperature: object) -> None:
    with pytest.raises(ValueError, match="temperature"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": "hello"}],
            temperature=temperature,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("top_p", [0, -0.01, 1.01, True, float("nan"), float("inf")])
def test_prepare_chat_request_rejects_invalid_top_p(top_p: object) -> None:
    with pytest.raises(ValueError, match="top_p"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": "hello"}],
            top_p=top_p,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("max_tokens", [0, -1, 65_537, True, 1.5])
def test_prepare_chat_request_rejects_invalid_max_tokens(max_tokens: object) -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        prepare_nvidia_chat_request(
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=max_tokens,  # type: ignore[arg-type]
        )


def test_prepare_chat_request_accepts_numeric_boundary_values() -> None:
    prepared = prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        top_p=1,
        max_tokens=65_536,
    )
    body = json.loads(prepared.body_bytes)
    assert body["temperature"] == 0
    assert body["top_p"] == 1
    assert body["max_tokens"] == 65_536


def test_prepare_chat_request_rejects_invalid_model_id() -> None:
    with pytest.raises(ValueError, match="model_id"):
        prepare_nvidia_chat_request(
            model_id="invalid-model-id",
            messages=[{"role": "user", "content": "hello"}],
        )


def test_prepare_chat_request_does_not_add_excluded_fields() -> None:
    prepared = prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[{"role": "user", "content": "hello"}],
    )
    body = json.loads(prepared.body_bytes)
    excluded = {
        "tools",
        "tool_choice",
        "response_format",
        "chat_template_kwargs",
        "reasoning_budget",
        "reasoning_effort",
        "images",
        "audio",
        "video",
        "seed",
        "stop",
        "provider",
    }
    assert excluded.isdisjoint(body)
