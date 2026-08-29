from pathlib import Path

import pytest

from byte_mcp.errors import AccessDeniedError, NotFoundError
from byte_mcp.security import (
    is_denied_relative,
    resolve_under_root,
)


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(AccessDeniedError):
        resolve_under_root(tmp_path, "../outside.txt")


def test_rejects_env_files() -> None:
    assert is_denied_relative(Path("project/.env"))


def test_rejects_secret_named_files_with_normal_extensions() -> None:
    assert is_denied_relative(Path("project/secrets.json"))
    assert is_denied_relative(Path("project/CREDENTIALS.yaml"))
    assert is_denied_relative(Path("project/secret.txt"))


def test_rejects_sensitive_suffixes_in_multi_suffix_names() -> None:
    assert is_denied_relative(Path("project/database.key.bak"))
    assert is_denied_relative(Path("project/client.pem.txt"))


def test_allows_similar_but_non_secret_names() -> None:
    assert not is_denied_relative(Path("project/secretary.txt"))
    assert not is_denied_relative(Path("project/credentials-old.yaml"))


def test_missing_path_is_normalized_to_domain_error(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError, match="cannot be resolved"):
        resolve_under_root(tmp_path, "missing.txt")


def test_allows_normal_relative_file(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    target.write_text("ok", encoding="utf-8")
    assert resolve_under_root(
        tmp_path,
        "report.txt",
    ) == target.resolve()
