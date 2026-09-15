from pathlib import Path

import pytest

from byte_mcp.errors import WolframConfigurationError
from byte_mcp.wolfram.settings import WolframSettings


def test_missing_appid_disables_only_wolfram(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))

    settings = WolframSettings.load(tmp_path)

    assert settings.app_id is None
    assert settings.endpoint == "https://www.wolframalpha.com/api/v1/llm-api"
    assert settings.max_input_chars == 8_000
    assert settings.default_max_chars == 6_800
    assert settings.max_response_chars == 6_800
    assert settings.soft_monthly_limit == 1_800


def test_settings_repr_never_contains_appid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "SENTINEL-WOLFRAM-SECRET")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))

    settings = WolframSettings.load(tmp_path)

    assert "SENTINEL-WOLFRAM-SECRET" not in repr(settings)
    assert "app_id_configured=True" in repr(settings)


def test_blank_appid_normalizes_to_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "  ")
    settings = WolframSettings.load(tmp_path)
    assert settings.app_id is None


def test_soft_limit_can_be_lowered_but_not_raised(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "7")
    assert WolframSettings.load(tmp_path).soft_monthly_limit == 7

    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "1801")
    with pytest.raises(WolframConfigurationError, match="between 1 and 1800"):
        WolframSettings.load(tmp_path)


def test_max_chars_is_clamped_to_fixed_bounds(tmp_path: Path) -> None:
    settings = WolframSettings(
        repo_root=tmp_path,
        usage_file=tmp_path / "usage.json",
        app_id=None,
    )
    assert settings.apply_max_chars(None) == 6800
    assert settings.apply_max_chars(100) == 250
    assert settings.apply_max_chars(99999) == 6800
