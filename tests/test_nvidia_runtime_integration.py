from byte_mcp import server

_EXPECTED_TOOLS = {
    "fetch",
    "list_directory",
    "list_roots",
    "nvidia_get_review",
    "nvidia_query",
    "nvidia_review",
    "search",
    "vscode_active_context",
    "wolfram_query",
}


def test_nvidia_runtime_extends_current_surface_by_exactly_three_tools() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == _EXPECTED_TOOLS
