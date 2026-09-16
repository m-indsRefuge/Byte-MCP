import importlib
import json

import pytest

DEEPSEEK = "deepseek-ai/deepseek-v4-pro-0813"
LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"


def _protocol():
    return importlib.import_module("byte_mcp.nvidia.query_protocol")


def _errors():
    return importlib.import_module("byte_mcp.nvidia.errors")


def test_default_query_request_uses_governed_deepseek_profile() -> None:
    protocol = _protocol()

    prepared = protocol.prepare_nvidia_query_request("Explain one invariant.")
    body = json.loads(prepared.request.body_bytes)

    assert prepared.model == "deepseek-v4-pro"
    assert prepared.provider_model_id == DEEPSEEK
    assert prepared.request.model_id == DEEPSEEK
    assert body == {
        "chat_template_kwargs": {"thinking": False},
        "max_tokens": 16_384,
        "messages": [{"role": "user", "content": "Explain one invariant."}],
        "model": DEEPSEEK,
        "n": 1,
        "seed": 42,
        "stream": False,
        "temperature": 1.0,
        "top_p": 0.95,
    }
    assert len(prepared.request.request_sha256) == 64


def test_lightning_query_request_uses_governed_profile_and_omits_seed() -> None:
    protocol = _protocol()

    prepared = protocol.prepare_nvidia_query_request(
        "Return OK.",
        model="lightning",
        system_prompt="Be concise.",
    )
    body = json.loads(prepared.request.body_bytes)

    assert prepared.model == "lightning"
    assert prepared.provider_model_id == LIGHTNING
    assert body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 4_096,
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Return OK."},
        ],
        "model": LIGHTNING,
        "n": 1,
        "stream": False,
        "temperature": 0.2,
        "top_p": 0.95,
    }


def test_query_request_identity_is_deterministic() -> None:
    protocol = _protocol()

    first = protocol.prepare_nvidia_query_request(
        "same prompt",
        model="deepseek-v4-pro",
    )
    second = protocol.prepare_nvidia_query_request(
        "same prompt",
        model="deepseek-v4-pro",
    )

    assert first.request.body_bytes == second.request.body_bytes
    assert first.request.payload_sha256 == second.request.payload_sha256
    assert first.request.request_sha256 == second.request.request_sha256


def test_raw_provider_id_is_rejected_locally() -> None:
    protocol = _protocol()
    errors = _errors()

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        protocol.prepare_nvidia_query_request(
            "hello",
            model=DEEPSEEK,
        )

    assert caught.value.code is errors.NvidiaErrorCode.MODEL_NOT_ALLOWED
    assert caught.value.provider_started is False


@pytest.mark.parametrize("prompt", ["", "   ", "x" * 32_001])
def test_prompt_is_bounded_before_request_construction(prompt: str) -> None:
    protocol = _protocol()
    errors = _errors()

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        protocol.prepare_nvidia_query_request(prompt)

    assert caught.value.code is errors.NvidiaErrorCode.INVALID_REQUEST
    assert caught.value.provider_started is False


def test_system_prompt_is_bounded_before_request_construction() -> None:
    protocol = _protocol()
    errors = _errors()

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        protocol.prepare_nvidia_query_request(
            "hello",
            system_prompt="x" * 16_001,
        )

    assert caught.value.code is errors.NvidiaErrorCode.INVALID_REQUEST
    assert caught.value.provider_started is False
