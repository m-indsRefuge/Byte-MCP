from pathlib import Path

import pytest

from byte_mcp.audit import AuditLog
from byte_mcp.service import FileService
from byte_mcp.settings import Settings
from byte_mcp.wolfram.domain import WolframAvailability
from byte_mcp.wolfram.runtime import WolframRuntime


def core_settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "core-audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=10_000,
        max_search_files=100,
        content_search_max_bytes=100_000,
    )


def test_missing_appid_returns_disabled_without_breaking_core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "wolfram-usage.json"))
    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.DISABLED
    assert runtime.service is None
    assert runtime.safe_error is None

    settings = core_settings(tmp_path)
    service = FileService(settings, roots={"projects": tmp_path})
    assert service.list_roots()["roots"] == [{"alias": "projects"}]


def test_invalid_wolfram_setting_returns_misconfigured_without_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sentinel = "SENTINEL-WOLFRAM-APPID"
    monkeypatch.setenv("WOLFRAM_APP_ID", sentinel)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "1801")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "wolfram-usage.json"))

    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.MISCONFIGURED
    assert runtime.service is None
    assert runtime.safe_error
    assert sentinel not in runtime.safe_error
    assert len(runtime.safe_error) <= 300

    settings = core_settings(tmp_path)
    assert FileService(settings, roots={"projects": tmp_path}).settings is settings


def test_available_runtime_constructs_without_provider_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-WOLFRAM-APPID")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "10")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "wolfram-usage.json"))

    runtime = WolframRuntime.load(tmp_path, AuditLog(tmp_path / "audit.jsonl"))

    assert runtime.availability is WolframAvailability.AVAILABLE
    assert runtime.service is not None
    assert runtime.safe_error is None
    assert not (tmp_path / "wolfram-usage.json").exists()
