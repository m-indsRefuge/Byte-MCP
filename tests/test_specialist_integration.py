from byte_mcp import server

_EXPECTED_TOOLS = {
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_query",
    "nvidia_review",
    "nvidia_get_review",
}


def test_combined_byte_mcp_surface_registers_current_non_ox_tools() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == _EXPECTED_TOOLS


def test_wolfram_tool_remains_read_only_and_open_world() -> None:
    registered = server.mcp._tool_manager._tools
    annotations = registered["wolfram_query"].annotations

    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True
