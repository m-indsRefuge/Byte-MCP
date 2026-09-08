import pytest

from byte_mcp.nvidia.settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings


def test_missing_hosted_key_is_allowed(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NGC_API_KEY", raising=False)
    assert NvidiaHostedSettings.load().api_key is None


def test_ngc_key_is_not_used_as_hosted_fallback(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NGC_API_KEY", "NGC-SENTINEL")
    settings = NvidiaHostedSettings.load()
    assert settings.api_key is None
    assert "NGC-SENTINEL" not in repr(settings)


def test_settings_repr_redacts_hosted_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "NVIDIA-SENTINEL-SECRET")
    settings = NvidiaHostedSettings.load()
    assert repr(settings) == "NvidiaHostedSettings(api_key_configured=True)"
    assert "NVIDIA-SENTINEL-SECRET" not in repr(settings)


def test_blank_direct_key_is_rejected():
    with pytest.raises(ValueError):
        NvidiaHostedSettings(api_key=" ")


def test_hosted_origin_is_exact_and_not_environment_overridable(monkeypatch):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_BASE_URL", "https://example.invalid/v1")
    settings = NvidiaHostedSettings.load()
    assert settings.base_url == NVIDIA_HOSTED_BASE_URL
    assert settings.base_url == "https://integrate.api.nvidia.com/v1"


def test_constructor_rejects_arbitrary_hosted_origin():
    with pytest.raises(ValueError):
        NvidiaHostedSettings(api_key=None, base_url="https://example.invalid/v1")


@pytest.mark.parametrize("value", ["0", "61", "not-an-int"])
def test_catalog_timeout_is_bounded(monkeypatch, value):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        NvidiaHostedSettings.load()


def test_catalog_timeout_default(monkeypatch):
    monkeypatch.delenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", raising=False)
    assert NvidiaHostedSettings.load().catalog_timeout_seconds == 10
