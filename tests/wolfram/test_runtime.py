from pathlib import Path

import pytest

from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframConfigurationError, WolframUnavailableError
from byte_mcp.wolfram.domain import WolframAvailability
from byte_mcp.wolfram.runtime import WolframRuntime


def test_missing_appid_yields_disabled_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))

    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.DISABLED
    with pytest.raises(WolframUnavailableError):
        runtime.require_service()


def test_wolfram_only_bad_setting_yields_misconfigured_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "test")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "9999")

    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.MISCONFIGURED
    with pytest.raises(WolframConfigurationError):
        runtime.require_service()


def test_configured_runtime_is_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "test")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "10")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))

    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.AVAILABLE
    assert runtime.require_service() is runtime.service
