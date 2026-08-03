from pathlib import Path

import pytest

from byte_mcp.errors import ByteMCPError
from byte_mcp.settings import Settings


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
