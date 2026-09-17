from byte_mcp import server

_EXPECTED_TOOLS = {
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "vscode_active_context",
    "wolfram_query",
    "nvidia_query",
    "nvidia_review",
    "nvidia_get_review",
}


def test_production_lineage_surface_registers_core_nvidia_vscode_and_wolfram_tools() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == _EXPECTED_TOOLS


def test_vscode_active_context_is_local_read_only_tool() -> None:
    registered = server.mcp._tool_manager._tools
    annotations = registered["vscode_active_context"].annotations

    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def test_wolfram_tool_remains_read_only_and_open_world() -> None:
    registered = server.mcp._tool_manager._tools
    annotations = registered["wolfram_query"].annotations

    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True
