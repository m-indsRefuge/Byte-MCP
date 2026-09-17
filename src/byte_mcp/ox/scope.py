"""Repository authority and bounded/full scope resolution for clean-room OX."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence

from byte_mcp.errors import (
    AccessDeniedError,
    NotFoundError,
    OXRepositoryError,
    OXScopeError,
)
from byte_mcp.ox.models import OXReviewMode, OXReviewScope
from byte_mcp.security import is_link_or_junction, resolve_under_root


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validate_repository_alias(repository: object) -> str:
    if not isinstance(repository, str) or not repository:
        raise OXRepositoryError("Repository alias is invalid.")
    if repository.strip() != repository or repository in {".", ".."}:
        raise OXRepositoryError("Repository alias is invalid.")
    if "/" in repository or "\\" in repository:
        raise OXRepositoryError("Repository must name one direct child of the projects root.")
    if _contains_control_characters(repository):
        raise OXRepositoryError("Repository alias is invalid.")
    if PureWindowsPath(repository).drive:
        raise OXRepositoryError("Drive-prefixed repository aliases are not allowed.")
    return repository


def _validate_bounded_path(logical_path: object) -> str:
    if (
        not isinstance(logical_path, str)
        or not logical_path
        or logical_path == "."
        or "\\" in logical_path
    ):
        raise OXScopeError("Bounded paths must be normalized repository-relative POSIX paths.")
    if _contains_control_characters(logical_path):
        raise OXScopeError("Bounded paths must not contain control characters.")
    if PureWindowsPath(logical_path).drive:
        raise OXScopeError("Drive-prefixed bounded paths are not allowed.")

    path = PurePosixPath(logical_path)
    if path.is_absolute() or logical_path.startswith("/"):
        raise OXScopeError("Absolute bounded paths are not allowed.")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise OXScopeError("Bounded paths must not contain traversal components.")
    if path.as_posix() != logical_path:
        raise OXScopeError("Bounded paths must be normalized repository-relative POSIX paths.")
    return logical_path


@dataclass(frozen=True, slots=True)
class OXResolvedRepository:
    alias: str
    path: Path = field(repr=False)


class OXScopeResolver:
    def __init__(self, projects_root: Path) -> None:
        try:
            resolved_root = Path(projects_root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OXRepositoryError("Configured projects root is unavailable.") from exc
        if not resolved_root.is_dir():
            raise OXRepositoryError("Configured projects root is not a directory.")
        self._projects_root = resolved_root

    def resolve_repository(self, repository: str) -> OXResolvedRepository:
        alias = _validate_repository_alias(repository)
        candidate = self._projects_root / alias

        try:
            exists = candidate.exists()
        except OSError as exc:
            raise OXRepositoryError("Repository cannot be inspected safely.") from exc
        if not exists:
            raise OXRepositoryError("Repository was not found beneath the projects root.")
        if is_link_or_junction(candidate):
            raise OXRepositoryError("Repository links and junctions are not traversed.")

        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OXRepositoryError("Repository cannot be resolved safely.") from exc

        try:
            relative = resolved.relative_to(self._projects_root)
        except ValueError as exc:
            raise OXRepositoryError("Repository escaped the configured projects root.") from exc
        if len(relative.parts) != 1 or not resolved.is_dir():
            raise OXRepositoryError("Repository must be one directory beneath the projects root.")

        return OXResolvedRepository(alias=alias, path=resolved)

    def resolve_scope(
        self,
        repository: str,
        mode: OXReviewMode,
        paths: Sequence[str],
        objective: str,
    ) -> tuple[OXResolvedRepository, OXReviewScope]:
        resolved_repository = self.resolve_repository(repository)
        if not isinstance(mode, OXReviewMode):
            raise OXScopeError("Review mode is invalid.")
        if isinstance(paths, (str, bytes)):
            raise OXScopeError("Scope paths must be a sequence of relative path strings.")
        try:
            requested_paths = tuple(paths)
        except TypeError as exc:
            raise OXScopeError("Scope paths must be a sequence of relative path strings.") from exc

        if mode is OXReviewMode.FULL_REPOSITORY:
            if requested_paths:
                raise OXScopeError("FULL_REPOSITORY reviews must not specify bounded paths.")
        elif not requested_paths:
            raise OXScopeError("BOUNDED reviews require at least one path.")

        for logical_path in requested_paths:
            normalized = _validate_bounded_path(logical_path)
            try:
                resolve_under_root(resolved_repository.path, normalized)
            except (AccessDeniedError, NotFoundError) as exc:
                raise OXScopeError(
                    f"Bounded path is unavailable or outside repository authority: {normalized}"
                ) from exc

        try:
            scope = OXReviewScope(
                repository=resolved_repository.alias,
                mode=mode,
                paths=requested_paths,
                objective=objective,
            )
        except ValueError as exc:
            raise OXScopeError("Review scope is invalid.") from exc

        return resolved_repository, scope
