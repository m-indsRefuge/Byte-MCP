"""Write-path authority contracts."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import byte_mcp.write.paths as write_paths
from byte_mcp.errors import WritePathError
from byte_mcp.write.paths import assert_safe_existing_entry, resolve_write_path

PROTECTED_PROJECTS = ("Byte-MCP",)


def resolve(
    projects_root: Path,
    raw_path: str,
    *,
    allow_missing_leaf: bool = True,
):
    """Resolve with the V1 test policy."""
    return resolve_write_path(
        projects_root,
        raw_path,
        protected_projects=PROTECTED_PROJECTS,
        allow_missing_leaf=allow_missing_leaf,
    )


def test_resolves_normal_existing_target(write_env) -> None:
    target = write_env.projects / "demo" / "src" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('ok')\n", encoding="utf-8")

    resolved = resolve(write_env.projects, "projects/demo/src/main.py")

    assert resolved.root_alias == "projects"
    assert resolved.project == "demo"
    assert str(resolved.project_relative) == "src/main.py"
    assert str(resolved.root_relative) == "demo/src/main.py"
    assert resolved.absolute == target.resolve()
    assert resolved.exists is True


def test_allows_missing_leaf_only_when_requested(write_env) -> None:
    project = write_env.projects / "demo"
    project.mkdir()

    with pytest.raises(WritePathError, match="does not exist"):
        resolve(write_env.projects, "projects/demo/new.py", allow_missing_leaf=False)

    resolved = resolve(write_env.projects, "projects/demo/new.py")

    assert resolved.project == "demo"
    assert resolved.absolute == project / "new.py"
    assert resolved.exists is False


def test_allows_new_top_level_project(write_env) -> None:
    resolved = resolve(write_env.projects, "projects/new-project")

    assert resolved.project == "new-project"
    assert str(resolved.project_relative) == "."
    assert resolved.exists is False


@pytest.mark.parametrize("raw_path", ["", "projects", "projects/"])
def test_denies_empty_or_root_only_path(write_env, raw_path: str) -> None:
    with pytest.raises(WritePathError):
        resolve(write_env.projects, raw_path)


@pytest.mark.parametrize(
    "raw_path",
    [
        "/tmp/escape.py",
        "C:/temp/escape.py",
        "Projects/demo/escape.py",
        "projects\\demo\\escape.py",
        "projects/demo/../escape.py",
        "projects/./demo/escape.py",
        "projects//demo/escape.py",
        "projects/demo/file:stream",
        "projects/demo/less<more.py",
        'projects/demo/quote".py',
        "projects/demo/pipe|.py",
        "projects/demo/query?.py",
        "projects/demo/star*.py",
        "projects/demo/control\x01.py",
    ],
)
def test_denies_noncanonical_or_windows_unsafe_syntax(write_env, raw_path: str) -> None:
    with pytest.raises(WritePathError):
        resolve(write_env.projects, raw_path)


@pytest.mark.parametrize(
    "raw_path",
    [
        "projects/demo/.env",
        "projects/demo/.git/config",
        "projects/demo/credentials.yaml",
        "projects/demo/client.pem.txt",
    ],
)
def test_denies_secret_and_repository_metadata_paths(write_env, raw_path: str) -> None:
    with pytest.raises(WritePathError, match="secret|blocked"):
        resolve(write_env.projects, raw_path)


def test_denies_protected_project_regardless_of_case(write_env) -> None:
    with pytest.raises(WritePathError, match="protected"):
        resolve(write_env.projects, "projects/bYtE-mCp/src/write.py")


@pytest.mark.parametrize(
    ("raw_path", "canonical_path", "message"),
    [
        ("projects/BYTEMC~1", "Byte-MCP", "protected"),
        ("projects/demo/SECRE~1.JSON", "demo/secrets.json", "alias|blocked|secret"),
    ],
)
def test_denies_windows_short_name_alias_of_protected_or_secret_identity(
    write_env,
    monkeypatch: pytest.MonkeyPatch,
    raw_path: str,
    canonical_path: str,
    message: str,
) -> None:
    canonical = write_env.projects / canonical_path
    canonical.parent.mkdir(parents=True, exist_ok=True)
    if canonical.suffix:
        canonical.write_text("sentinel\n", encoding="utf-8")
    else:
        canonical.mkdir()
    alias = write_env.projects.joinpath(*raw_path.split("/")[1:])
    original_lstat = Path.lstat
    original_resolve = Path.resolve

    def lstat_short_name(self: Path):
        if self == alias:
            return original_lstat(canonical)
        return original_lstat(self)

    def resolve_short_name(self: Path, strict: bool = False) -> Path:
        if self == alias:
            return original_resolve(canonical, strict=strict)
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "lstat", lstat_short_name)
    monkeypatch.setattr(Path, "resolve", resolve_short_name)

    with pytest.raises(WritePathError, match=message):
        resolve(write_env.projects, raw_path)


@pytest.mark.parametrize(
    "raw_path",
    [
        "projects/demo/CON",
        "projects/demo/nul.txt",
        "projects/demo/COM1.log",
        "projects/demo/LpT9.py",
        "projects/demo/trailing.txt ",
        "projects/demo/trailing.",
    ],
)
def test_denies_windows_device_and_trimmed_name_aliases(write_env, raw_path: str) -> None:
    with pytest.raises(WritePathError):
        resolve(write_env.projects, raw_path)


def test_denies_case_insensitive_sibling_collision(write_env) -> None:
    project = write_env.projects / "demo"
    project.mkdir()
    (project / "Readme.md").write_text("existing\n", encoding="utf-8")

    with pytest.raises(WritePathError, match="case-insensitive"):
        resolve(write_env.projects, "projects/demo/README.md")


def test_denies_symlink_traversal(write_env) -> None:
    outside = write_env.private / "outside"
    outside.mkdir()
    link = write_env.projects / "demo"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links unavailable")

    with pytest.raises(WritePathError, match="link|reparse"):
        resolve(write_env.projects, "projects/demo/escape.py")


def test_denies_junction_when_platform_reports_one(
    write_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = write_env.projects / "demo"
    project.mkdir()
    junction = project / "junction"
    junction.mkdir()

    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda self: self == junction,
        raising=False,
    )

    with pytest.raises(WritePathError, match="link|reparse|junction"):
        resolve(write_env.projects, "projects/demo/junction/file.py")


def test_denies_generic_windows_reparse_point_when_detectable(
    write_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reparse_flag = getattr(os.stat(write_env.projects), "st_file_attributes", None)
    if reparse_flag is None:
        pytest.skip("Windows file attributes unavailable")

    project = write_env.projects / "demo"
    project.mkdir()
    entry = project / "reparse"
    entry.mkdir()
    original_lstat = Path.lstat

    def lstat_with_reparse(self: Path):
        result = original_lstat(self)
        if self == entry:
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_nlink=result.st_nlink,
                st_file_attributes=reparse_flag | 0x400,
            )
        return result

    monkeypatch.setattr(Path, "lstat", lstat_with_reparse)

    with pytest.raises(WritePathError, match="reparse"):
        resolve(write_env.projects, "projects/demo/reparse/file.py")


def test_denies_missing_reparse_attributes_on_windows(
    write_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = write_env.projects / "entry.txt"
    entry.write_text("sentinel\n", encoding="utf-8")
    original_lstat = Path.lstat

    def lstat_without_attributes(self: Path):
        result = original_lstat(self)
        if self == entry:
            return SimpleNamespace(st_mode=result.st_mode, st_nlink=result.st_nlink)
        return result

    monkeypatch.setattr(write_paths.os, "name", "nt")
    monkeypatch.setattr(Path, "lstat", lstat_without_attributes)
    monkeypatch.setattr(Path, "is_junction", lambda self: False, raising=False)

    with pytest.raises(WritePathError, match="reparse|inspect"):
        assert_safe_existing_entry(entry)


def test_allows_missing_reparse_attributes_off_windows(
    write_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = write_env.projects / "entry.txt"
    entry.write_text("sentinel\n", encoding="utf-8")
    original_lstat = Path.lstat

    def lstat_without_attributes(self: Path):
        result = original_lstat(self)
        if self == entry:
            return SimpleNamespace(st_mode=result.st_mode, st_nlink=result.st_nlink)
        return result

    monkeypatch.setattr(write_paths.os, "name", "posix")
    monkeypatch.setattr(Path, "lstat", lstat_without_attributes)
    monkeypatch.setattr(Path, "is_junction", lambda self: False, raising=False)

    assert_safe_existing_entry(entry)


def test_denies_uninspectable_existing_entry(write_env, monkeypatch: pytest.MonkeyPatch) -> None:
    project = write_env.projects / "demo"
    project.mkdir()
    entry = project / "uninspectable"
    entry.mkdir()
    original_lstat = Path.lstat

    def lstat_uninspectable(self: Path):
        if self == entry:
            raise PermissionError("denied")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", lstat_uninspectable)

    with pytest.raises(WritePathError, match="inspect"):
        resolve(write_env.projects, "projects/demo/uninspectable/file.py")


def test_denies_hard_linked_file(write_env) -> None:
    outside = write_env.private / "outside.txt"
    outside.write_text("sentinel", encoding="utf-8")
    project = write_env.projects / "demo"
    project.mkdir()
    linked = project / "linked.txt"
    try:
        linked.hardlink_to(outside)
    except OSError:
        pytest.skip("hard links unavailable")

    with pytest.raises(WritePathError, match="hard link"):
        assert_safe_existing_entry(linked)
