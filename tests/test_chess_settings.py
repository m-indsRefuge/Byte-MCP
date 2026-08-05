from __future__ import annotations

from uuid import uuid4

import pytest

from byte_mcp.chess_settings import ChessSettings
from byte_mcp.errors import ByteMCPError


def _configure_required_environment(monkeypatch: pytest.MonkeyPatch) -> str:
    match_id = str(uuid4())
    monkeypatch.setenv("BYTE_MCP_CHESS_MATCH_ID", match_id)
    monkeypatch.delenv("BYTE_MCP_CHESS_ARENA_BASE_URL", raising=False)
    monkeypatch.delenv("BYTE_MCP_CHESS_HOST", raising=False)
    monkeypatch.delenv("BYTE_MCP_CHESS_PORT", raising=False)
    monkeypatch.delenv("BYTE_MCP_CHESS_ACTOR", raising=False)
    return match_id


def test_chess_settings_default_to_isolated_loopback_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match_id = _configure_required_environment(monkeypatch)

    settings = ChessSettings.load()

    assert str(settings.match_id) == match_id
    assert settings.actor == "byte"
    assert settings.arena_base_url == "http://127.0.0.1:8787/api/v1"
    assert settings.server_host == "127.0.0.1"
    assert settings.server_port == 8001
    assert settings.mcp_url == "http://127.0.0.1:8001/mcp"


def test_chess_settings_require_match_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTE_MCP_CHESS_MATCH_ID", raising=False)

    with pytest.raises(ByteMCPError, match="MATCH_ID is required"):
        ChessSettings.load()


def test_chess_settings_reject_non_loopback_arena(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "BYTE_MCP_CHESS_ARENA_BASE_URL",
        "https://example.com/api/v1",
    )

    with pytest.raises(ByteMCPError, match="must use http|loopback-only"):
        ChessSettings.load()


def test_chess_settings_reject_non_loopback_mcp_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv("BYTE_MCP_CHESS_HOST", "0.0.0.0")

    with pytest.raises(ByteMCPError, match="loopback-only"):
        ChessSettings.load()


def test_chess_settings_reject_unexpected_arena_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_required_environment(monkeypatch)
    monkeypatch.setenv(
        "BYTE_MCP_CHESS_ARENA_BASE_URL",
        "http://127.0.0.1:8787/admin",
    )

    with pytest.raises(ByteMCPError, match="must end with /api/v1"):
        ChessSettings.load()
