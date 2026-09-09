from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import httpx
import pytest

import byte_mcp.providers as providers_package
from byte_mcp.nvidia import (
    NvidiaChatError,
    NvidiaChatMessage,
    NvidiaHostedSettings,
    execute_prepared_nvidia_chat,
    initial_model_registry,
    prepare_nvidia_chat_request,
)
from byte_mcp.providers import ProviderTransmissionContext

_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
_KEY = "NVIDIA-SECURITY-SENTINEL"
_STARTED_AT = "2026-09-09T09:00:00+00:00"


def _prepared():
    return prepare_nvidia_chat_request(
        model_id=_MODEL,
        messages=(NvidiaChatMessage(role="user", content="Return exactly: OK"),),
        max_tokens=8,
    )


def _context(prepared):
    return ProviderTransmissionContext(
        provider_started_at=_STARTED_AT,
        expected_request_sha256=prepared.request_sha256,
    )


def _success_body(model_id: str = _MODEL) -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-security-test",
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode("utf-8")


def _execute(prepared, transport):
    return asyncio.run(
        execute_prepared_nvidia_chat(
            prepared,
            _context(prepared),
            NvidiaHostedSettings(api_key=_KEY),
            transport=transport,
        )
    )


def _import_targets(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * node.level
            targets.append(prefix + module)
    return tuple(targets)


def test_provider_neutral_modules_do_not_import_provider_adapters():
    provider_dir = Path(providers_package.__file__).resolve().parent
    forbidden = (
        "byte_mcp.nvidia",
        "byte_mcp.ox",
        "byte_mcp.wolfram",
        "..nvidia",
        "..ox",
        "..wolfram",
    )

    violations: list[str] = []
    for path in sorted(provider_dir.glob("*.py")):
        for target in _import_targets(path):
            if target.startswith(forbidden):
                violations.append(f"{path.name}: {target}")

    assert violations == []


def test_nvidia_chat_does_not_import_ox_or_wolfram():
    import byte_mcp.nvidia.chat as chat_module

    targets = _import_targets(Path(chat_module.__file__).resolve())
    assert not any(
        "ox" in target.split(".") or "wolfram" in target.split(".")
        for target in targets
    )


def test_server_has_no_nvidia_inference_registration():
    import byte_mcp.server as server_module

    server_path = Path(server_module.__file__).resolve()
    source = server_path.read_text(encoding="utf-8")
    imports = _import_targets(server_path)

    assert not any("nvidia" in target.lower() for target in imports)
    assert "execute_prepared_nvidia_chat" not in source
    assert "nvidia_chat" not in source.lower()


def test_transport_and_nvidia_adapter_have_no_retry_backoff_or_fallback_machinery():
    import byte_mcp.nvidia.chat as chat_module
    import byte_mcp.providers.transport as transport_module

    for module in (chat_module, transport_module):
        path = Path(module.__file__).resolve()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lowered = node.name.lower()
                assert "retry" not in lowered
                assert "backoff" not in lowered
                assert "fallback" not in lowered
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                lowered = name.lower()
                assert "retry" not in lowered
                assert "backoff" not in lowered
                assert "fallback" not in lowered


def test_secret_is_absent_from_prepared_result_error_and_observation_surfaces():
    prepared = _prepared()

    async def success(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_success_body(), request=request)

    result = _execute(prepared, httpx.MockTransport(success))
    observation = result.transport_observation
    for rendered in (
        repr(prepared),
        repr(NvidiaHostedSettings(api_key=_KEY)),
        repr(result),
        repr(observation),
    ):
        assert _KEY not in rendered

    observation_fields = {item.name for item in fields(observation)}
    assert "body" not in observation_fields
    assert "request_body" not in observation_fields
    assert "response_body" not in observation_fields
    assert "authorization" not in observation_fields
    assert "headers" not in observation_fields

    async def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="provider secret prose", request=request)

    with pytest.raises(NvidiaChatError) as caught:
        _execute(prepared, httpx.MockTransport(rejected))
    assert _KEY not in str(caught.value)
    assert _KEY not in repr(caught.value)
    assert "provider secret prose" not in str(caught.value)
    assert "provider secret prose" not in repr(caught.value)


def test_transmitted_bytes_are_exactly_the_prepared_bytes():
    prepared = _prepared()
    observed_bodies: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_bodies.append(request.content)
        return httpx.Response(200, content=_success_body(), request=request)

    _execute(prepared, httpx.MockTransport(handler))
    assert observed_bodies == [prepared.body_bytes]


def test_request_hash_mismatch_has_zero_network_calls():
    prepared = _prepared()
    calls = 0
    context = replace(_context(prepared), expected_request_sha256="0" * 64)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_success_body(), request=request)

    with pytest.raises(ValueError, match="request_sha256"):
        asyncio.run(
            execute_prepared_nvidia_chat(
                prepared,
                context,
                NvidiaHostedSettings(api_key=_KEY),
                transport=httpx.MockTransport(handler),
            )
        )
    assert calls == 0


@pytest.mark.parametrize(
    "tampered",
    [
        lambda prepared: replace(prepared, body_bytes=b'{"tampered":true}'),
        lambda prepared: replace(prepared, model_id="nvidia/tampered-model"),
        lambda prepared: replace(prepared, payload_sha256="0" * 64),
    ],
)
def test_tampered_prepared_request_identity_has_zero_network_calls(tampered):
    prepared = tampered(_prepared())
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_success_body(prepared.model_id), request=request)

    with pytest.raises(ValueError, match="prepared request"):
        _execute(prepared, httpx.MockTransport(handler))
    assert calls == 0


def test_catalog_and_registry_state_do_not_change_through_chat_execution():
    registry = initial_model_registry()
    before = registry.all()
    prepared = _prepared()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_success_body(), request=request)

    _execute(prepared, httpx.MockTransport(handler))
    assert registry.all() == before


def test_ngc_key_alone_never_satisfies_hosted_credential(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NGC_API_KEY", "NGC-ONLY-SENTINEL")
    assert NvidiaHostedSettings.load().api_key is None


def test_invalid_nvidia_configuration_does_not_break_core_ox_or_wolfram_imports():
    env = os.environ.copy()
    env["BYTE_MCP_NVIDIA_CHAT_READ_TIMEOUT_SECONDS"] = "9999"
    command = (
        "import byte_mcp.service; "
        "import byte_mcp.ox.runtime; "
        "import byte_mcp.wolfram.runtime"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
