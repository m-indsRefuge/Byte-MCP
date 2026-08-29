import inspect

from byte_mcp import server


def test_wolfram_phase1_tool_catalog_is_narrow() -> None:
    names = set(server.mcp._tool_manager._tools)
    assert "wolfram_query" in names
    for forbidden in (
        "wolfram_review",
        "wolfram_continue",
        "wolfram_revalidate",
        "wolfram_get_review",
        "wolfram_compute",
        "http_request",
        "fetch_url",
    ):
        assert forbidden not in names


def test_wolfram_query_argument_surface_has_no_generic_http_authority() -> None:
    parameters = set(inspect.signature(server.wolfram_query).parameters)
    assert parameters == {
        "input",
        "max_chars",
        "purpose",
        "route_reason",
        "source_finding_id",
    }
    assert parameters.isdisjoint(
        {"appid", "url", "endpoint", "headers", "method", "assumption"}
    )


def test_wolfram_query_annotation_marks_external_non_idempotent_read() -> None:
    tool = server.mcp._tool_manager._tools["wolfram_query"]
    annotations = tool.annotations
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True
