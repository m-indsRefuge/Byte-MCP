import pytest

from byte_mcp import server
from byte_mcp.errors import WolframRequestError

EXPECTED_CORE = {"list_roots", "list_directory", "search", "fetch"}
FORBIDDEN = {
    "wolfram_review",
    "wolfram_continue",
    "wolfram_revalidate",
    "wolfram_get_review",
    "wolfram_compute",
    "http_request",
    "fetch_url",
}


def tools_by_name():
    return {
        tool.name: tool
        for tool in server.mcp._tool_manager.list_tools()  # noqa: SLF001
    }


def test_phase1_registers_only_one_wolfram_tool_and_correct_annotations() -> None:
    tools = tools_by_name()
    assert EXPECTED_CORE | {"wolfram_query"} <= set(tools)
    assert not (FORBIDDEN & set(tools))

    annotations = tools["wolfram_query"].annotations
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def test_wolfram_tool_argument_surface_is_exactly_bounded() -> None:
    tool = tools_by_name()["wolfram_query"]
    properties = set(tool.parameters["properties"])
    assert properties == {
        "input",
        "max_chars",
        "purpose",
        "route_reason",
        "source_finding_id",
    }
    forbidden = {
        "appid",
        "url",
        "endpoint",
        "headers",
        "method",
        "assumption",
        "options",
    }
    assert not (forbidden & properties)


def test_invalid_enum_is_rejected_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_runtime():
        nonlocal called
        called = True
        raise AssertionError("runtime must not be touched")

    monkeypatch.setattr(
        server,
        "wolfram_runtime",
        fail_runtime,
        raising=False,
    )

    with pytest.raises(WolframRequestError, match="purpose"):
        server.wolfram_query("2+2", purpose="NOT_A_PURPOSE")

    assert called is False
