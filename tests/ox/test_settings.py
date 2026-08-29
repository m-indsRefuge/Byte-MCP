import pytest

from byte_mcp.ox.settings import OXSettings


def test_missing_key_is_allowed_in_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    settings = OXSettings.load(tmp_path)
    assert settings.api_key is None


def test_settings_repr_redacts_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "SENTINEL-SECRET")
    settings = OXSettings.load(tmp_path)
    assert "SENTINEL-SECRET" not in repr(settings)
    assert repr(settings) == "OXSettings(api_key_configured=True)"


def test_settings_selects_platform_evidence_root(monkeypatch, tmp_path):
    monkeypatch.delenv("BYTE_MCP_OX_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr("byte_mcp.ox.settings.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert OXSettings.load(tmp_path).evidence_root == tmp_path / "local" / "Byte-MCP" / "ox"


@pytest.mark.parametrize(
    ("name", "value"),
    [("BYTE_MCP_OX_MAX_BUNDLE_BYTES", "16383"), ("BYTE_MCP_OX_MAX_OUTPUT_TOKENS", "1023")],
)
def test_settings_rejects_values_below_integer_bounds(monkeypatch, tmp_path, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        OXSettings.load(tmp_path)


def test_settings_strips_blank_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "  ")
    assert OXSettings.load(tmp_path).api_key is None
