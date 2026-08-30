"""Path authority checks for controlled project mutations."""

from __future__ import annotations

import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..errors import WritePathError
from ..security import is_denied_relative

_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class ResolvedWritePath:
    """A mutation path normalized beneath the one writable projects root."""

    root_alias: str
    project: str
    project_relative: PurePosixPath
    root_relative: PurePosixPath
    absolute: Path
    exists: bool


def assert_safe_existing_entry(path: Path) -> None:
    """Reject an existing filesystem entry whose identity cannot be trusted."""
    try:
        entry_stat = path.lstat()
        if stat.S_ISLNK(entry_stat.st_mode) or path.is_symlink():
            raise WritePathError("symbolic links are not permitted in write paths")
        if _is_reparse_point(entry_stat):
            raise WritePathError("reparse points are not permitted in write paths")
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            raise WritePathError("junctions are not permitted in write paths")
        if stat.S_ISREG(entry_stat.st_mode) and entry_stat.st_nlink != 1:
            raise WritePathError("hard linked files are not permitted in write paths")
    except WritePathError:
        raise
    except OSError as exc:
        raise WritePathError("existing path entry cannot be inspected safely") from exc


def resolve_write_path(
    projects_root: Path,
    raw_path: str,
    protected_projects: tuple[str, ...],
    allow_missing_leaf: bool,
) -> ResolvedWritePath:
    """Resolve one canonical, project-scoped mutation path or fail closed."""
    parts = _parse_mutation_path(raw_path)
    root_alias, project, *project_parts = parts
    if root_alias != "projects":
        raise WritePathError("write paths must begin with the projects root alias")
    protected_project_names = frozenset(name.casefold() for name in protected_projects)
    if project.casefold() in protected_project_names:
        raise WritePathError("the requested project is protected from write mutations")

    root_relative = PurePosixPath(project, *project_parts)
    project_relative = PurePosixPath(*project_parts)
    if is_denied_relative(Path(*root_relative.parts)):
        raise WritePathError("the requested path is blocked by the secret-denial policy")

    canonical_root = _canonical_projects_root(projects_root)
    cursor = canonical_root
    exists = True
    for index, part in enumerate(root_relative.parts):
        _reject_casefold_alias(cursor, part)
        candidate = cursor / part
        try:
            candidate.lstat()
        except FileNotFoundError:
            exists = False
            if index != len(root_relative.parts) - 1:
                raise WritePathError("a write path parent does not exist") from None
            if not allow_missing_leaf:
                raise WritePathError("the requested write path does not exist") from None
            cursor = candidate
            break
        except OSError as exc:
            raise WritePathError("existing path entry cannot be inspected safely") from exc
        assert_safe_existing_entry(candidate)
        cursor = _contained_canonical_path(candidate, canonical_root)

    _validate_canonical_identity(
        cursor,
        canonical_root,
        root_relative,
        protected_project_names,
    )

    return ResolvedWritePath(
        root_alias=root_alias,
        project=project,
        project_relative=project_relative,
        root_relative=root_relative,
        absolute=cursor,
        exists=exists,
    )


def _parse_mutation_path(raw_path: str) -> tuple[str, ...]:
    if not isinstance(raw_path, str) or not raw_path:
        raise WritePathError("write path must be a non-empty forward-slash path")
    if "\\" in raw_path:
        raise WritePathError("write paths must use forward slashes")
    if raw_path.startswith("/"):
        raise WritePathError("absolute write paths are not permitted")

    raw_parts = raw_path.split("/")
    if any(part == "" for part in raw_parts):
        raise WritePathError("write paths cannot contain empty segments")
    for part in raw_parts:
        _validate_segment(part)

    parsed = PurePosixPath(raw_path)
    parts = parsed.parts
    if len(parts) < 2:
        raise WritePathError("write paths must identify one top-level project")
    return parts


def _validate_segment(segment: str) -> None:
    if segment in {".", ".."}:
        raise WritePathError("dot segments are not permitted in write paths")
    if segment.endswith((".", " ")):
        raise WritePathError("write path segments cannot end in a dot or space")
    if any(
        character in _WINDOWS_INVALID_CHARACTERS
        or unicodedata.category(character) == "Cc"
        for character in segment
    ):
        raise WritePathError("write path contains Windows-invalid characters")
    if segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES:
        raise WritePathError("write path contains a reserved Windows device name")


def _canonical_projects_root(projects_root: Path) -> Path:
    try:
        assert_safe_existing_entry(projects_root)
        root = projects_root.resolve(strict=True)
        if not root.is_dir():
            raise WritePathError("the projects root is not a directory")
        assert_safe_existing_entry(root)
        return root
    except WritePathError:
        raise
    except OSError as exc:
        raise WritePathError("the projects root cannot be inspected safely") from exc


def _contained_canonical_path(path: Path, canonical_root: Path) -> Path:
    try:
        canonical_path = path.resolve(strict=True)
    except OSError as exc:
        raise WritePathError("existing path entry cannot be resolved safely") from exc
    try:
        canonical_path.relative_to(canonical_root)
    except ValueError as exc:
        raise WritePathError("write path escaped the approved projects root") from exc
    return canonical_path


def _validate_canonical_identity(
    path: Path,
    canonical_root: Path,
    requested_relative: PurePosixPath,
    protected_project_names: frozenset[str],
) -> None:
    try:
        canonical_relative = path.relative_to(canonical_root)
    except ValueError as exc:
        raise WritePathError("write path escaped the approved projects root") from exc
    if not canonical_relative.parts:
        raise WritePathError("write paths must identify one top-level project")
    if canonical_relative.parts[0].casefold() in protected_project_names:
        raise WritePathError("the requested project is protected from write mutations")
    if is_denied_relative(canonical_relative):
        raise WritePathError("the requested path is blocked by the secret-denial policy")
    if PurePosixPath(*canonical_relative.parts) != requested_relative:
        raise WritePathError("write paths cannot use filesystem aliases")


def _reject_casefold_alias(parent: Path, requested_name: str) -> None:
    try:
        for sibling in parent.iterdir():
            if (
                sibling.name != requested_name
                and sibling.name.casefold() == requested_name.casefold()
            ):
                raise WritePathError("write path has a case-insensitive sibling collision")
    except WritePathError:
        raise
    except OSError as exc:
        raise WritePathError("write path siblings cannot be inspected safely") from exc


def _is_reparse_point(entry_stat: os.stat_result) -> bool:
    if os.name != "nt":
        return False
    try:
        attributes = entry_stat.st_file_attributes
    except AttributeError as exc:
        raise WritePathError("Windows reparse attributes cannot be inspected safely") from exc
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)
