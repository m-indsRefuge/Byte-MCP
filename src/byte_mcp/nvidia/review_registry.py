"""Allow-listed Git repository access for NVIDIA routine reviews."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

from dulwich import patch
from dulwich.errors import NotGitRepository
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Commit
from dulwich.repo import Repo

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_REGULAR_FILE_MODES = {0o100644, 0o100755}
_UNSAFE_ENTRY_MODES = {0o120000, 0o160000}


@dataclass(frozen=True, slots=True)
class NvidiaReviewSubsystemDefinition:
    subsystem_id: str
    version: int
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    boundary_files: tuple[str, ...]
    context_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NvidiaReviewRepositoryDefinition:
    alias: str
    path: Path
    subsystems: Mapping[str, NvidiaReviewSubsystemDefinition]


def _validate_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must match {_IDENTIFIER.pattern}")
    return value


def _validate_logical_git_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("logical Git path must not be empty")
    if "\x00" in value or "\\" in value or value.startswith("/") or _DRIVE_PREFIX.match(value):
        raise ValueError(f"invalid logical Git path: {value!r}")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise ValueError(f"invalid logical Git path: {value!r}")
    return value


def _path_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_validate_logical_git_path(item) for item in value)


class NvidiaReviewRepositoryRegistry:
    def __init__(self, definitions: Mapping[str, NvidiaReviewRepositoryDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def load(cls, path: Path) -> NvidiaReviewRepositoryRegistry:
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unable to load NVIDIA review repository registry: {path}") from error
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("NVIDIA review repository registry must have version 1")
        repositories = document.get("repositories")
        if not isinstance(repositories, dict) or not repositories:
            raise ValueError("NVIDIA review repository registry must define repositories")

        definitions = {
            _validate_identifier(alias, "repository alias"): cls._definition(alias, configuration)
            for alias, configuration in repositories.items()
        }
        return cls(definitions)

    @staticmethod
    def _definition(alias: str, configuration: object) -> NvidiaReviewRepositoryDefinition:
        if not isinstance(configuration, dict):
            raise ValueError(f"repository {alias!r} must be an object")
        configured_path = configuration.get("path")
        if not isinstance(configured_path, str):
            raise ValueError(f"repository {alias!r} must have a path")
        repository_path = Path(configured_path)
        if not repository_path.is_absolute() or not repository_path.is_dir():
            raise ValueError("repository path must be an absolute existing Git repository")
        try:
            Repo(repository_path)
        except (NotGitRepository, OSError, ValueError) as error:
            raise ValueError("repository path must be an absolute existing Git repository") from error

        configured_subsystems = configuration.get("subsystems")
        if not isinstance(configured_subsystems, dict) or not configured_subsystems:
            raise ValueError(f"repository {alias!r} must define subsystems")
        subsystems = {
            _validate_identifier(subsystem_id, "subsystem ID"): NvidiaReviewRepositoryRegistry._subsystem(
                subsystem_id, definition
            )
            for subsystem_id, definition in configured_subsystems.items()
        }
        return NvidiaReviewRepositoryDefinition(
            alias,
            repository_path,
            MappingProxyType(subsystems),
        )

    @staticmethod
    def _subsystem(
        subsystem_id: str,
        definition: object,
    ) -> NvidiaReviewSubsystemDefinition:
        if not isinstance(definition, dict):
            raise ValueError(f"subsystem {subsystem_id!r} must be an object")
        version = definition.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError(f"subsystem {subsystem_id!r} version must be a positive integer")
        return NvidiaReviewSubsystemDefinition(
            subsystem_id=subsystem_id,
            version=version,
            source_roots=_path_list(definition.get("source_roots"), "source_roots"),
            test_roots=_path_list(definition.get("test_roots"), "test_roots"),
            boundary_files=_path_list(definition.get("boundary_files"), "boundary_files"),
            context_files=_path_list(definition.get("context_files"), "context_files"),
        )

    def get(self, alias: str) -> NvidiaReviewRepositoryDefinition:
        try:
            return self._definitions[alias]
        except KeyError as error:
            raise ValueError(f"unknown repository alias: {alias}") from error


class NvidiaReviewGitRepository:
    def __init__(self, definition: NvidiaReviewRepositoryDefinition, repo: Repo) -> None:
        self.definition = definition
        self.repo = repo

    @classmethod
    def open(cls, definition: NvidiaReviewRepositoryDefinition) -> NvidiaReviewGitRepository:
        return cls(definition, Repo(definition.path))

    def resolve_commit(self, commit_sha: str) -> Commit:
        if not isinstance(commit_sha, str) or _COMMIT_SHA.fullmatch(commit_sha) is None:
            raise ValueError("expected exact 40-hex commit SHA")
        try:
            candidate = self.repo.object_store[commit_sha.encode("ascii")]
        except KeyError as error:
            raise ValueError(f"commit not found: {commit_sha}") from error
        if not isinstance(candidate, Commit):
            raise ValueError(f"object is not a commit: {commit_sha}")
        return candidate

    def _tree_entries(self, commit: Commit):
        return iter_tree_contents(self.repo.object_store, commit.tree)

    @staticmethod
    def _entry_path(entry) -> str:
        try:
            return entry.path.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Git tree contains a non-UTF-8 path") from error

    @staticmethod
    def _require_regular_file(mode: int, path: str) -> None:
        if mode in _UNSAFE_ENTRY_MODES:
            raise ValueError(f"unsafe Git entry in review scope: {path}")
        if mode not in _REGULAR_FILE_MODES:
            raise ValueError(f"review artifact is not a regular file: {path}")

    def _entries_by_path(self, commit: Commit):
        return {self._entry_path(entry): entry for entry in self._tree_entries(commit)}

    def read_target_text(self, commit: Commit, path: str) -> bytes:
        logical_path = _validate_logical_git_path(path)
        entry = self._entries_by_path(commit).get(logical_path)
        if entry is None:
            raise ValueError(f"target file is missing: {logical_path}")
        self._require_regular_file(entry.mode, logical_path)
        return self.repo.object_store[entry.sha].data

    def changed_paths(self, base: Commit, target: Commit) -> tuple[str, ...]:
        base_entries = self._entries_by_path(base)
        target_entries = self._entries_by_path(target)
        changed: list[str] = []
        for path in sorted(set(base_entries) | set(target_entries)):
            old = base_entries.get(path)
            new = target_entries.get(path)
            old_identity = None if old is None else (old.mode, old.sha)
            new_identity = None if new is None else (new.mode, new.sha)
            if old_identity != new_identity:
                changed.append(path)
        return tuple(changed)

    def diff(self, base: Commit, target: Commit) -> bytes:
        output = BytesIO()
        patch.write_tree_diff(
            output,
            self.repo.object_store,
            base.tree,
            target.tree,
            diff_binary=False,
        )
        return output.getvalue()
