from pathlib import Path

import pytest

from byte_mcp.errors import AccessDeniedError
from byte_mcp.security import (
    is_denied_relative,
    resolve_under_root,
)


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(AccessDeniedError):
        resolve_under_root(tmp_path, "../outside.txt")


def test_rejects_env_files() -> None:
    assert is_denied_relative(Path("project/.env"))


def test_allows_normal_relative_file(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    target.write_text("ok", encoding="utf-8")
    assert resolve_under_root(
        tmp_path,
        "report.txt",
    ) == target.resolve()
