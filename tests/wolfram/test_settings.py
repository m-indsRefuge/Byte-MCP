from pathlib import Path

import pytest

from byte_mcp.errors import WolframConfigurationError
from byte_mcp.wolfram.settings import WolframSettings


def test_missing_appid_disables_only_wolfram(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert settings.app_id is None
    assert settings.endpoint == "https://www.wolframalpha.com/api/v1/llm-api"
    assert settings.max_input_chars == 8_000
    assert settings.default_max_chars == 6_800
    assert settings.max_response_chars == 6_800
    assert settings.soft_monthly_limit == 1_800


def test_settings_repr_never_contains_appid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "SENTINEL-WOLFRAM-SECRET")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert "SENTINEL-WOLFRAM-SECRET" not in repr(settings)
    assert "app_id_configured=True" in repr(settings)


def test_max_chars_is_clamped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert settings.apply_max_chars(None) == 6800
    assert settings.apply_max_chars(1) == 250
    assert settings.apply_max_chars(9000) == 6800


def test_endpoint_environment_override_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_ENDPOINT", "https://evil.example/")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert settings.endpoint == "https://www.wolframalpha.com/api/v1/llm-api"


def test_blank_appid_normalizes_to_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "   ")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    assert WolframSettings.load(tmp_path).app_id is None


def test_soft_limit_rejects_above_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "1801")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    with pytest.raises(WolframConfigurationError, match="between 1 and 1800"):
        WolframSettings.load(tmp_path)


@pytest.mark.parametrize("limit", [1, 10, 1800])
def test_soft_limit_accepts_operational_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int
) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", str(limit))
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    assert WolframSettings.load(tmp_path).soft_monthly_limit == limit
