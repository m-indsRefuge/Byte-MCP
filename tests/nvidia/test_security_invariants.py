import importlib
import inspect

import httpx

from byte_mcp.nvidia.catalog import NvidiaCatalogClient
from byte_mcp.nvidia.registry import initial_model_registry
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers.models import ModelLifecycleState

KEY = "NVIDIA-SECURITY-SENTINEL"


def test_invalid_nvidia_environment_does_not_break_existing_provider_modules(monkeypatch):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", "invalid")
    for module_name in (
        "byte_mcp.service",
        "byte_mcp.ox.runtime",
        "byte_mcp.wolfram.runtime",
    ):
        module = importlib.import_module(module_name)
        importlib.reload(module)


def test_nvidia_client_repr_never_contains_key():
    client = NvidiaCatalogClient(NvidiaHostedSettings(api_key=KEY))
    assert KEY not in repr(client)


def test_catalog_snapshot_contains_no_request_or_header_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            headers={"x-secret": "HEADER-SENTINEL"},
            json={"data": [{"id": "nvidia/example-model"}]},
        )

    client = NvidiaCatalogClient(
        NvidiaHostedSettings(api_key=KEY),
        transport=httpx.MockTransport(handler),
    )
    rendered = repr(client.discover())
    assert KEY not in rendered
    assert "HEADER-SENTINEL" not in rendered
    assert "Authorization" not in rendered


def test_discovery_roster_has_no_qualified_or_enabled_state():
    registry = initial_model_registry()
    assert registry.by_state(ModelLifecycleState.QUALIFIED) == ()
    assert registry.by_state(ModelLifecycleState.ENABLED) == ()


def test_new_provider_modules_do_not_import_ox_or_wolfram_packages():
    for module_name in (
        "byte_mcp.providers.models",
        "byte_mcp.providers.outcomes",
        "byte_mcp.providers.registry",
        "byte_mcp.nvidia.errors",
        "byte_mcp.nvidia.settings",
        "byte_mcp.nvidia.catalog",
        "byte_mcp.nvidia.registry",
    ):
        source = inspect.getsource(importlib.import_module(module_name))
        assert "byte_mcp.ox" not in source
        assert "byte_mcp.wolfram" not in source


def test_server_has_no_nvidia_inference_registration():
    from byte_mcp import server

    assert not any("nvidia" in name for name in server.mcp._tool_manager._tools)


def test_provider_neutral_modules_do_not_import_nvidia():
    for name in ("models", "outcomes", "registry"):
        source = inspect.getsource(importlib.import_module("byte_mcp.providers." + name))
        assert "byte_mcp.nvidia" not in source


def test_blank_environment_key_is_missing(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "  ")
    monkeypatch.delenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", raising=False)
    assert NvidiaHostedSettings.load().api_key is None


def test_candidate_metadata_preserves_unknown_capabilities():
    for profile in initial_model_registry().all():
        assert profile.publisher == profile.model_id.split("/")[0]
        assert profile.hosted_status == "candidate"
        assert profile.context_window is None
        assert profile.supports_streaming is None
        assert profile.supports_tool_calling is None
        assert profile.supports_reasoning is None
        assert profile.reasoning_dialect is None
