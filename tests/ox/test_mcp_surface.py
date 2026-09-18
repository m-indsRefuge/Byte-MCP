from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from byte_mcp import server
from byte_mcp.errors import OXConfigurationError
from byte_mcp.ox.settings import OXSettings
from byte_mcp.settings import Settings

EXPECTED_NON_OX_TOOLS = {
    "bel02_git_diff",
    "bel02_git_status",
    "bel02_status",
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_query",
    "nvidia_review",
    "nvidia_get_review",
}
EXPECTED_OX_TOOLS = {"ox_review", "ox_get_review"}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=10_000_000,
        max_response_chars=60_000,
        max_search_files=20_000,
        content_search_max_bytes=1_000_000,
    )


def test_task11_preserves_exact_current_surface() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == EXPECTED_NON_OX_TOOLS | EXPECTED_OX_TOOLS
    assert {name for name in registered if name.startswith("ox_")} == EXPECTED_OX_TOOLS


def test_task11_ox_tool_annotations_are_exact() -> None:
    tools = server.mcp._tool_manager._tools
    review = tools["ox_review"].annotations
    get_review = tools["ox_get_review"].annotations

    assert review.readOnlyHint is False
    assert review.destructiveHint is False
    assert review.idempotentHint is False
    assert review.openWorldHint is True

    assert get_review.readOnlyHint is True
    assert get_review.destructiveHint is False
    assert get_review.idempotentHint is True
    assert get_review.openWorldHint is False


def test_server_reload_does_not_load_ox_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_load(cls) -> OXSettings:
        raise AssertionError("OX provider settings must remain lazy at server startup")

    monkeypatch.setattr(OXSettings, "load", classmethod(forbidden_load))

    reloaded = importlib.reload(server)

    assert set(reloaded.mcp._tool_manager._tools) == EXPECTED_NON_OX_TOOLS | EXPECTED_OX_TOOLS


def test_ox_runtime_uses_existing_projects_root_without_loading_provider_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_module = importlib.import_module("byte_mcp.ox.runtime")
    projects = tmp_path / "projects"
    repository = projects / "example"
    repository.mkdir(parents=True)
    evidence_root = tmp_path / "evidence"
    monkeypatch.setenv("BYTE_MCP_OX_EVIDENCE_DIR", str(evidence_root))

    def forbidden_load(cls) -> OXSettings:
        raise AssertionError("runtime construction must not load the provider credential")

    monkeypatch.setattr(runtime_module.OXSettings, "load", classmethod(forbidden_load))

    runtime = runtime_module.OXRuntime.load(
        _settings(tmp_path),
        {"projects": projects, "other": tmp_path},
    )
    ox_service = runtime.require_service()

    resolved = ox_service._scope_resolver.resolve_repository("example")
    assert resolved.path == repository.resolve()
    assert evidence_root.resolve().is_dir()


def test_ox_runtime_missing_projects_root_is_fail_isolated(tmp_path: Path) -> None:
    runtime_module = importlib.import_module("byte_mcp.ox.runtime")

    runtime = runtime_module.OXRuntime.load(
        _settings(tmp_path),
        {"not-projects": tmp_path},
    )

    with pytest.raises(OXConfigurationError, match="OX runtime is unavailable"):
        runtime.require_service()


def test_ox_review_delegates_one_synchronous_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeService:
        async def review(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {"review_id": "OX-000001", "state": "COMPLETED"}

    monkeypatch.setattr(server, "ox_service", lambda: FakeService())

    result = __import__("asyncio").run(
        server.ox_review(
            repository="example",
            mode="BOUNDED",
            objective="Review the changed subsystem.",
            paths=["src", "tests"],
        )
    )

    assert result == {"review_id": "OX-000001", "state": "COMPLETED"}
    assert calls == [
        {
            "repository": "example",
            "mode": "BOUNDED",
            "objective": "Review the changed subsystem.",
            "paths": ["src", "tests"],
        }
    ]


def test_ox_get_review_is_local_service_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        def get_review(self, review_id: str) -> dict[str, object]:
            assert review_id == "OX-000007"
            return {"review_id": review_id, "state": "READY"}

    monkeypatch.setattr(server, "ox_service", lambda: FakeService())

    assert server.ox_get_review("OX-000007") == {
        "review_id": "OX-000007",
        "state": "READY",
    }
