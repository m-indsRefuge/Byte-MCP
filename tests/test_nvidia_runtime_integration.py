from byte_mcp import server

_EXPECTED_TOOLS = {
    "bel02_git_diff",
    "bel02_git_status",
    "bel02_status",
    "fetch",
    "list_directory",
    "list_roots",
    "nvidia_get_review",
    "nvidia_query",
    "nvidia_review",
    "search",
    "wolfram_query",
}


def test_runtime_surface_preserves_nvidia_and_adds_bel02_tools() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == _EXPECTED_TOOLS


def test_bel02_runtime_surface_is_read_only_and_excludes_generic_execution() -> None:
    registered = server.mcp._tool_manager._tools

    for name in ("bel02_status", "bel02_git_status", "bel02_git_diff"):
        annotations = registered[name].annotations
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is False

    assert "bel02_run" not in registered
