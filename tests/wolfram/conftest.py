from pathlib import Path

import pytest

from byte_mcp.wolfram.settings import WolframSettings


@pytest.fixture
def wolfram_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WolframSettings:
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-WOLFRAM-APPID")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "10")
    return WolframSettings.load(tmp_path)
