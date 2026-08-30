import json
from pathlib import Path

import pytest

from byte_mcp.errors import ByteMCPError
from byte_mcp.settings import Settings, load_roots


def make_settings(tmp_path: Path, roots_file: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=roots_file,
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
    )


def test_mcp_url_uses_explicit_host_and_port(tmp_path: Path) -> None:
    settings = Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
        server_host="127.0.0.1",
        server_port=8123,
    )

    assert settings.mcp_url == "http://127.0.0.1:8123/mcp"


def test_load_rejects_non_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTE_MCP_HOST", "0.0.0.0")

    with pytest.raises(ByteMCPError, match="loopback-only"):
        Settings.load()


def test_load_rejects_invalid_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTE_MCP_TRANSPORT", "stdio")

    with pytest.raises(ByteMCPError, match="streamable-http"):
        Settings.load()


def test_load_rejects_privileged_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTE_MCP_PORT", "80")

    with pytest.raises(ByteMCPError, match="between 1024 and 65535"):
        Settings.load()


def test_load_roots_normalizes_invalid_utf8_config(tmp_path: Path) -> None:
    roots_file = tmp_path / "roots.json"
    roots_file.write_bytes(b"\xff\xfeinvalid")

    with pytest.raises(ByteMCPError, match="cannot be read as UTF-8"):
        load_roots(make_settings(tmp_path, roots_file))


def test_load_roots_normalizes_missing_root_path(tmp_path: Path) -> None:
    roots_file = tmp_path / "roots.json"
    roots_file.write_text(
        json.dumps({"roots": {"projects": str(tmp_path / "missing")}}),
        encoding="utf-8",
    )

    with pytest.raises(ByteMCPError, match="cannot be resolved"):
        load_roots(make_settings(tmp_path, roots_file))


def test_load_uses_default_write_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTE_MCP_WRITE_POLICY_FILE", raising=False)
    monkeypatch.delenv("BYTE_MCP_WRITE_STATE_DIR", raising=False)

    settings = Settings.load()

    assert settings.write_policy_file == (Path.home() / ".byte-mcp/write/policy.json").resolve()
    assert settings.write_state_dir == (Path.home() / ".byte-mcp/write/state").resolve()


def test_load_uses_write_path_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = tmp_path / "policy.json"
    state = tmp_path / "state"
    monkeypatch.setenv("BYTE_MCP_WRITE_POLICY_FILE", str(policy))
    monkeypatch.setenv("BYTE_MCP_WRITE_STATE_DIR", str(state))

    settings = Settings.load()

    assert settings.write_policy_file == policy.resolve()
    assert settings.write_state_dir == state.resolve()
