import ast
import asyncio
import importlib
import inspect
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

KEY = "NVIDIA-QUERY-SENTINEL"


def _service():
    return importlib.import_module("byte_mcp.nvidia.query_service")


def _settings():
    return importlib.import_module("byte_mcp.nvidia.settings")


def _errors():
    return importlib.import_module("byte_mcp.nvidia.errors")


def _success(request, *, content: str = "OK", model_id: str | None = None):
    return SimpleNamespace(
        model_id=request.model_id if model_id is None else model_id,
        content=content,
        finish_reason="stop",
        response_id="chatcmpl-query-test",
        usage=None,
        request_sha256=request.request_sha256,
        payload_sha256=request.payload_sha256,
    )


def test_missing_credential_fails_before_executor() -> None:
    service = _service()
    settings = _settings()
    errors = _errors()
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return settings.NvidiaHostedSettings(api_key=None)

    async def executor(*_args):
        calls["executor"] += 1
        raise AssertionError("executor must not run without a credential")

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                settings_loader=settings_loader,
                executor=executor,
            )
        )

    assert caught.value.code is errors.NvidiaErrorCode.CREDENTIAL_UNAVAILABLE
    assert caught.value.provider_started is False
    assert calls == {"settings": 1, "executor": 0}


def test_invalid_prompt_does_not_load_credentials_or_executor() -> None:
    service = _service()
    errors = _errors()
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        raise AssertionError("settings must not load")

    async def executor(*_args):
        calls["executor"] += 1
        raise AssertionError("executor must not run")

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(
            service.execute_nvidia_query(
                "",
                settings_loader=settings_loader,
                executor=executor,
            )
        )

    assert caught.value.code is errors.NvidiaErrorCode.INVALID_REQUEST
    assert calls == {"settings": 0, "executor": 0}


def test_success_executes_exactly_once_and_returns_bounded_result() -> None:
    service = _service()
    settings = _settings()
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return settings.NvidiaHostedSettings(api_key=KEY)

    async def executor(request, context, actual_settings):
        calls["executor"] += 1
        assert actual_settings.api_key == KEY
        assert context.expected_request_sha256 == request.request_sha256
        return _success(request)

    result = asyncio.run(
        service.execute_nvidia_query(
            "hello",
            settings_loader=settings_loader,
            executor=executor,
            now=lambda: datetime(2026, 9, 16, 1, 0, tzinfo=UTC),
        )
    )

    assert calls == {"settings": 1, "executor": 1}
    assert result.model == "deepseek-v4-pro"
    assert result.provider_model_id == "deepseek-ai/deepseek-v4-pro-0813"
    assert result.response == "OK"
    assert result.finish_reason == "stop"
    assert result.response_id == "chatcmpl-query-test"
    assert len(result.request_sha256) == 64
    assert result.usage is None
    assert result.to_dict()["response"] == "OK"
    assert "OK" not in repr(result)
    assert KEY not in repr(result)


def test_response_identity_mismatch_is_rejected() -> None:
    service = _service()
    settings = _settings()
    errors = _errors()

    async def executor(request, _context, _actual_settings):
        return _success(request, model_id="provider/wrong-model")

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                settings_loader=lambda: settings.NvidiaHostedSettings(api_key=KEY),
                executor=executor,
            )
        )

    assert caught.value.code is errors.NvidiaErrorCode.RESPONSE_INVALID
    assert caught.value.provider_started is True


def test_response_size_is_bounded() -> None:
    service = _service()
    settings = _settings()
    errors = _errors()

    async def executor(request, _context, _actual_settings):
        return _success(
            request,
            content="x" * (service.MAX_QUERY_RESPONSE_CHARS + 1),
        )

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                settings_loader=lambda: settings.NvidiaHostedSettings(api_key=KEY),
                executor=executor,
            )
        )

    assert caught.value.code is errors.NvidiaErrorCode.RESPONSE_TOO_LARGE
    assert caught.value.provider_started is True


def test_query_engine_has_no_retry_fallback_or_catalog_discovery() -> None:
    service = _service()
    source = inspect.getsource(service)
    tree = ast.parse(source)

    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr.lower())

    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    assert not any("retry" in name for name in identifiers)
    assert not any("fallback" in name for name in identifiers)
    assert not any("catalog" in name for name in identifiers)
    assert "/v1/models" not in source
