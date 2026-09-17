from byte_mcp import server

EXPECTED_NON_OX_TOOLS = {
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_query",
    "nvidia_review",
    "nvidia_get_review",
}


def test_task1_preserves_exact_current_non_ox_surface() -> None:
    registered = set(server.mcp._tool_manager._tools)

    assert registered == EXPECTED_NON_OX_TOOLS


def test_task1_has_no_registered_ox_tools() -> None:
    registered = server.mcp._tool_manager._tools

    assert not any(name.startswith("ox_") for name in registered)
