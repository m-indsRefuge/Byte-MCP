import asyncio
import inspect
from types import SimpleNamespace

import pytest

from byte_mcp import server


def test_nvidia_query_public_signature_is_bounded() -> None:
    assert tuple(inspect.signature(server.nvidia_query).parameters) == (
        "prompt",
        "model",
        "system_prompt",
    )


def test_nvidia_query_delegates_to_query_engine(monkeypatch) -> None:
    calls = []
    audit = object()

    async def fake_execute(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return SimpleNamespace(
            to_dict=lambda: {
                "model": kwargs["model"] or "nemotron-ultra",
                "provider_model_id": "provider/model",
                "response": "OK",
                "request_sha256": "a" * 64,
                "finish_reason": "stop",
                "response_id": "response-id",
                "usage": None,
            }
        )

    monkeypatch.setattr(server, "_nvidia_query_executor", lambda: fake_execute)
    monkeypatch.setattr(server, "_nvidia_query_audit", lambda: audit)

    result = asyncio.run(
        server.nvidia_query(
            prompt="hello",
            model="lightning",
            system_prompt="be concise",
        )
    )

    assert result["model"] == "lightning"
    assert calls == [
        (
            "hello",
            {
                "model": "lightning",
                "system_prompt": "be concise",
                "audit": audit,
            },
        )
    ]


def test_nvidia_query_propagates_safe_typed_local_error(monkeypatch) -> None:
    errors = __import__(
        "byte_mcp.nvidia.errors",
        fromlist=["NvidiaPlatformError", "NvidiaErrorCode"],
    )
    calls = 0

    async def fake_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise errors.NvidiaPlatformError(
            code=errors.NvidiaErrorCode.MODEL_NOT_ALLOWED,
            message="model is not allowed",
            provider_started=False,
            safe_to_invoke_fresh=True,
        )

    monkeypatch.setattr(server, "_nvidia_query_executor", lambda: fake_execute)
    monkeypatch.setattr(server, "_nvidia_query_audit", lambda: object())

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(server.nvidia_query(prompt="hello", model="unknown"))

    assert caught.value.code is errors.NvidiaErrorCode.MODEL_NOT_ALLOWED
    assert caught.value.provider_started is False
    assert calls == 1


def test_exact_nvidia_mcp_surface_is_registered() -> None:
    names = {name for name in server.mcp._tool_manager._tools if "nvidia" in name}
    assert names == {"nvidia_query", "nvidia_review", "nvidia_get_review"}
