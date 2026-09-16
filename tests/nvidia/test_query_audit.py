import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from byte_mcp.audit import AuditLog

PROMPT_SECRET = "NVIDIA-QUERY-PROMPT-SECRET-77A1"
RESPONSE_SECRET = "NVIDIA-QUERY-RESPONSE-SECRET-88B2"
KEY_SECRET = "NVIDIA-QUERY-KEY-SECRET-99C3"


def _module(name: str):
    import importlib
    import importlib.util

    spec = importlib.util.find_spec(name)
    assert spec is not None, f"{name} must exist"
    return importlib.import_module(name)


def _success(request):
    return SimpleNamespace(
        model_id=request.model_id,
        content=RESPONSE_SECRET,
        finish_reason="stop",
        response_id="chatcmpl-audit-test",
        usage=None,
        request_sha256=request.request_sha256,
        payload_sha256=request.payload_sha256,
    )


def test_success_audit_is_metadata_only(tmp_path: Path) -> None:
    service = _module("byte_mcp.nvidia.query_service")
    settings = _module("byte_mcp.nvidia.settings")
    audit_path = tmp_path / "audit.jsonl"

    async def executor(request, _context, _settings):
        return _success(request)

    result = asyncio.run(
        service.execute_nvidia_query(
            PROMPT_SECRET,
            model="deepseek-v4-pro",
            system_prompt="SYSTEM-SECRET-55D4",
            settings_loader=lambda: settings.NvidiaHostedSettings(api_key=KEY_SECRET),
            executor=executor,
            audit=AuditLog(audit_path),
        )
    )

    assert result.response == RESPONSE_SECRET
    raw = audit_path.read_text(encoding="utf-8")
    assert PROMPT_SECRET not in raw
    assert RESPONSE_SECRET not in raw
    assert KEY_SECRET not in raw
    assert "SYSTEM-SECRET-55D4" not in raw
    assert "Authorization" not in raw

    event = json.loads(raw)
    assert event["action"] == "nvidia_query"
    assert event["outcome"] == "allowed"
    assert event["surface"] == "query"
    assert event["model_alias"] == "deepseek-v4-pro"
    assert event["provider_model_id"] == "deepseek-ai/deepseek-v4-pro-0813"
    assert len(event["request_sha256"]) == 64
    assert event["provider_started"] is True
    assert event["finish_reason"] == "stop"
    assert event["request_bytes"] > 0
    assert event["response_bytes"] == len(RESPONSE_SECRET.encode("utf-8"))
    assert event["duration_ms"] >= 0


def test_invalid_alias_audit_does_not_persist_untrusted_alias(tmp_path: Path) -> None:
    service = _module("byte_mcp.nvidia.query_service")
    errors = _module("byte_mcp.nvidia.errors")
    audit_path = tmp_path / "audit.jsonl"
    untrusted_alias = "ALIAS-SECRET-SENTINEL-DO-NOT-PERSIST"

    with pytest.raises(errors.NvidiaPlatformError):
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                model=untrusted_alias,
                audit=AuditLog(audit_path),
            )
        )

    raw = audit_path.read_text(encoding="utf-8")
    assert untrusted_alias not in raw
    event = json.loads(raw)
    assert event["provider_started"] is False
    assert event["model_alias"] is None
    assert event["outcome"] == "error"


def test_audit_failure_after_provider_success_never_reinvokes_executor() -> None:
    service = _module("byte_mcp.nvidia.query_service")
    settings = _module("byte_mcp.nvidia.settings")
    calls = 0

    class FailingAudit:
        def record(self, *args, **kwargs) -> None:
            raise RuntimeError("synthetic audit failure")

    async def executor(request, _context, _settings):
        nonlocal calls
        calls += 1
        return _success(request)

    with pytest.raises(RuntimeError, match="audit failure"):
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                settings_loader=lambda: settings.NvidiaHostedSettings(api_key=KEY_SECRET),
                executor=executor,
                audit=FailingAudit(),
            )
        )

    assert calls == 1
