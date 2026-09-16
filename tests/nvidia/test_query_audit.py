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
            model="nemotron-ultra",
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
    assert event["model_alias"] == "nemotron-ultra"
    assert event["provider_model_id"] == "nvidia/nemotron-3-ultra-550b-a55b"
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


def test_provider_rejection_preserves_http_status_in_safe_audit(tmp_path: Path) -> None:
    service = _module("byte_mcp.nvidia.query_service")
    settings = _module("byte_mcp.nvidia.settings")
    errors = _module("byte_mcp.nvidia.errors")
    providers = _module("byte_mcp.providers")
    audit_path = tmp_path / "audit.jsonl"
    timestamp = "2026-09-16T04:30:00+00:00"

    async def executor(request, context, _settings):
        observation = providers.ProviderTransportObservation(
            response_headers_received=True,
            response_headers_at=timestamp,
            response_headers_elapsed_ms=10,
            http_status_code=400,
            response_body_started=True,
            first_body_at=timestamp,
            first_body_elapsed_ms=11,
            last_body_at=timestamp,
            last_body_elapsed_ms=11,
            decoded_body_bytes_received=32,
            provider_started_at=context.provider_started_at,
            provider_finished_at=timestamp,
            elapsed_ms=12,
            transport_failure_kind=None,
            trust_env_enabled=True,
            proxy_environment_present=False,
        )
        raise errors.NvidiaChatError(
            kind=errors.NvidiaChatFailureKind.REQUEST,
            attempt_outcome=providers.ProviderAttemptOutcome.REJECTED,
            transport_observation=observation,
            request_sha256=request.request_sha256,
        )

    with pytest.raises(errors.NvidiaPlatformError) as caught:
        asyncio.run(
            service.execute_nvidia_query(
                "hello",
                model="lightning",
                settings_loader=lambda: settings.NvidiaHostedSettings(api_key=KEY_SECRET),
                executor=executor,
                audit=AuditLog(audit_path),
            )
        )

    assert caught.value.code is errors.NvidiaErrorCode.INVALID_REQUEST
    assert caught.value.provider_started is True
    assert caught.value.status_code == 400

    event = json.loads(audit_path.read_text(encoding="utf-8"))
    assert event["action"] == "nvidia_query"
    assert event["outcome"] == "error"
    assert event["provider_started"] is True
    assert event["error_code"] == "INVALID_REQUEST"
    assert event["status_code"] == 400
    assert PROMPT_SECRET not in json.dumps(event)
    assert RESPONSE_SECRET not in json.dumps(event)
    assert KEY_SECRET not in json.dumps(event)
