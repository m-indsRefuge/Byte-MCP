from byte_mcp import server

_EXPECTED_TOOLS = {
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_review",
    "nvidia_get_review",
}


def test_nvidia_runtime_extends_current_surface_by_exactly_two_tools() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == _EXPECTED_TOOLS
