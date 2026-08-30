from pathlib import Path
import runpy

from byte_mcp import server


def test_operational_smoke_requires_full_combined_tool_surface() -> None:
    expected = set(server.mcp._tool_manager._tools)
    smoke_globals = runpy.run_path(str(Path("scripts/mcp_smoke_test.py")))
    smoke_expected = set(smoke_globals["EXPECTED_TOOLS"])

    assert smoke_expected == expected
