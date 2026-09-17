"""Deterministic current-filesystem snapshotting for clean-room OX reviews."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.models import (
    OXArtifact,
    OXReviewMode,
    OXReviewScope,
    OXSnapshot,
    OXSnapshotExclusion,
)
from byte_mcp.ox.scope import OXResolvedRepository
from byte_mcp.ox.settings import (
    OX_MAX_ARTIFACT_BYTES,
    OX_MAX_ARTIFACTS,
    OX_MAX_SNAPSHOT_CONTENT_BYTES,
    OX_SNAPSHOT_POLICY_VERSION,
)
from byte_mcp.security import is_link_or_junction

_TEXT_CLASSIFICATION = "text/utf-8"

_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".byte-mcp",
        ".cache",
        ".git",
        ".hg",
        ".idea",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        ".vs",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "env",
        "evidence",
        "htmlcov",
        "node_modules",
        "out",
        "ox-evidence",
        "site-packages",
        "target",
        "venv",
    }
)

_SENSITIVE_FILE_NAMES = frozenset(
    {
        "credential",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secret",
        "secrets",
    }
)

_SENSITIVE_SUFFIXES = frozenset({".key", ".kdbx", ".p12", ".pem", ".pfx"})
_DATABASE_SUFFIXES = frozenset({".db", ".db3", ".sqlite", ".sqlite3"})
_ARCHIVE_SUFFIXES = frozenset({".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".xz", ".zip"})
_BINARY_OR_MEDIA_SUFFIXES = frozenset(
    {
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".exe",
        ".gif",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".pdf",
        ".png",
        ".pyc",
        ".pyo",
        ".so",
        ".wasm",
        ".wav",
        ".webp",
    }
)


def _file_name_variants(name: str) -> set[str]:
    variants = {name.casefold()}
    current = Path(name)
    while current.suffix:
        current = Path(current.stem)
        variants.add(current.name.casefold())
    return variants


def _directory_exclusion_reason(name: str) -> str | None:
    if name.casefold() in _EXCLUDED_DIRECTORY_NAMES:
        return "excluded-directory"
    return None


def _file_exclusion_reason(name: str) -> str | None:
    lowered = name.casefold()
    suffix = Path(lowered).suffix

    if lowered == ".env" or lowered.startswith(".env."):
        return "sensitive-environment-file"
    if lowered == ".coverage" or lowered.startswith(".coverage."):
        return "coverage-output"
    if _file_name_variants(lowered) & _SENSITIVE_FILE_NAMES:
        return "sensitive-file"
    if suffix in _SENSITIVE_SUFFIXES:
        return "sensitive-key-material"
    if suffix in _DATABASE_SUFFIXES:
        return "database"
    if suffix in _ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in _BINARY_OR_MEDIA_SUFFIXES:
        return "binary-or-media"
    return None


def _logical_join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _has_git_metadata(directory: Path) -> bool:
    try:
        with os.scandir(directory) as entries:
            return any(entry.name == ".git" for entry in entries)
    except OSError as exc:
        raise OXBundleError("Repository material cannot be inspected safely.") from exc


@dataclass(slots=True)
class _SnapshotCollector:
    artifacts: dict[str, OXArtifact] = field(default_factory=dict)
    exclusions: dict[tuple[str, str], OXSnapshotExclusion] = field(default_factory=dict)
    total_content_bytes: int = 0

    def exclude(self, logical_path: str, reason: str) -> None:
        key = (logical_path, reason)
        self.exclusions.setdefault(
            key,
            OXSnapshotExclusion(logical_path=logical_path, reason=reason),
        )

    def include(self, logical_path: str, content: bytes) -> None:
        if logical_path in self.artifacts:
            return
        if len(self.artifacts) >= OX_MAX_ARTIFACTS:
            raise OXBundleError("Snapshot artifact count exceeds the configured hard limit.")
        new_total = self.total_content_bytes + len(content)
        if new_total > OX_MAX_SNAPSHOT_CONTENT_BYTES:
            raise OXBundleError("Snapshot content exceeds the configured hard limit.")

        digest = hashlib.sha256(content).hexdigest()
        self.artifacts[logical_path] = OXArtifact(
            logical_path=logical_path,
            content=content,
            byte_length=len(content),
            content_sha256=digest,
            classification=_TEXT_CLASSIFICATION,
            git_state=None,
        )
        self.total_content_bytes = new_total


def _collect_file(path: Path, logical_path: str, collector: _SnapshotCollector) -> None:
    exclusion_reason = _file_exclusion_reason(path.name)
    if exclusion_reason is not None:
        collector.exclude(logical_path, exclusion_reason)
        return

    if is_link_or_junction(path):
        collector.exclude(logical_path, "link-or-junction")
        return

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise OXBundleError("Repository file cannot be inspected safely.") from exc
    if size > OX_MAX_ARTIFACT_BYTES:
        collector.exclude(logical_path, "artifact-too-large")
        return

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise OXBundleError("Repository file cannot be frozen safely.") from exc
    if len(content) > OX_MAX_ARTIFACT_BYTES:
        collector.exclude(logical_path, "artifact-too-large")
        return
    if b"\x00" in content:
        collector.exclude(logical_path, "non-text-nul")
        return
    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        collector.exclude(logical_path, "non-text-utf8")
        return

    collector.include(logical_path, content)


def _walk_directory(
    directory: Path,
    logical_prefix: str,
    collector: _SnapshotCollector,
) -> None:
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        raise OXBundleError("Repository directory cannot be inspected safely.") from exc

    for entry in entries:
        path = Path(entry.path)
        logical_path = _logical_join(logical_prefix, entry.name)

        if is_link_or_junction(path):
            collector.exclude(logical_path, "link-or-junction")
            continue

        try:
            is_directory = entry.is_dir(follow_symlinks=False)
            is_file = entry.is_file(follow_symlinks=False)
        except OSError as exc:
            raise OXBundleError("Repository entry cannot be inspected safely.") from exc

        if is_directory:
            exclusion_reason = _directory_exclusion_reason(entry.name)
            if exclusion_reason is not None:
                collector.exclude(logical_path, exclusion_reason)
                continue
            if _has_git_metadata(path):
                collector.exclude(logical_path, "nested-repository")
                continue
            _walk_directory(path, logical_path, collector)
            continue

        if is_file:
            _collect_file(path, logical_path, collector)
            continue

        collector.exclude(logical_path, "unsupported-filesystem-entry")


def _validate_selected_path(repository_root: Path, logical_path: str) -> Path:
    candidate = repository_root
    for component in logical_path.split("/"):
        candidate = candidate / component
        if is_link_or_junction(candidate):
            raise OXBundleError("Directly selected links or junctions are not reviewable.")
        try:
            exists = candidate.exists()
        except OSError as exc:
            raise OXBundleError("Selected repository material cannot be inspected safely.") from exc
        if not exists:
            raise OXBundleError("Selected repository material is no longer available.")
    return candidate


def _collect_selection(
    repository_root: Path,
    logical_path: str,
    collector: _SnapshotCollector,
) -> None:
    selected = _validate_selected_path(repository_root, logical_path)
    try:
        is_directory = selected.is_dir()
        is_file = selected.is_file()
    except OSError as exc:
        raise OXBundleError("Selected repository material cannot be inspected safely.") from exc

    if is_directory:
        exclusion_reason = _directory_exclusion_reason(selected.name)
        if exclusion_reason is not None:
            collector.exclude(logical_path, exclusion_reason)
            return
        if _has_git_metadata(selected):
            collector.exclude(logical_path, "nested-repository")
            return
        _walk_directory(selected, logical_path, collector)
        return
    if is_file:
        _collect_file(selected, logical_path, collector)
        return
    raise OXBundleError("Selected repository material has an unsupported filesystem type.")


def _snapshot_identity(
    *,
    repository: str,
    mode: OXReviewMode,
    requested_paths: tuple[str, ...],
    artifacts: tuple[OXArtifact, ...],
    exclusions: tuple[OXSnapshotExclusion, ...],
) -> str:
    manifest = {
        "repository": repository,
        "mode": mode.value,
        "requested_paths": list(requested_paths),
        "policy_version": OX_SNAPSHOT_POLICY_VERSION,
        "artifacts": [
            {
                "logical_path": artifact.logical_path,
                "byte_length": artifact.byte_length,
                "content_sha256": artifact.content_sha256,
                "classification": artifact.classification,
                "git_state": artifact.git_state,
            }
            for artifact in artifacts
        ],
        "exclusions": [
            {
                "logical_path": exclusion.logical_path,
                "reason": exclusion.reason,
            }
            for exclusion in exclusions
        ],
    }
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def freeze_snapshot(
    repository: OXResolvedRepository,
    scope: OXReviewScope,
) -> OXSnapshot:
    """Freeze exact eligible current filesystem bytes for one approved review scope."""
    if not isinstance(repository, OXResolvedRepository):
        raise OXBundleError("Resolved repository is invalid.")
    if not isinstance(scope, OXReviewScope):
        raise OXBundleError("Review scope is invalid.")
    if repository.alias != scope.repository:
        raise OXBundleError("Repository and scope identity do not match.")
    if is_link_or_junction(repository.path):
        raise OXBundleError("Repository links or junctions are not reviewable.")
    try:
        if not repository.path.is_dir():
            raise OXBundleError("Resolved repository is unavailable.")
    except OSError as exc:
        raise OXBundleError("Resolved repository cannot be inspected safely.") from exc

    collector = _SnapshotCollector()
    if scope.mode is OXReviewMode.FULL_REPOSITORY:
        _walk_directory(repository.path, "", collector)
    else:
        for logical_path in scope.paths:
            _collect_selection(repository.path, logical_path, collector)

    artifacts = tuple(sorted(collector.artifacts.values(), key=lambda item: item.logical_path))
    exclusions = tuple(
        sorted(
            collector.exclusions.values(),
            key=lambda item: (item.logical_path, item.reason),
        )
    )
    snapshot_sha256 = _snapshot_identity(
        repository=scope.repository,
        mode=scope.mode,
        requested_paths=scope.paths,
        artifacts=artifacts,
        exclusions=exclusions,
    )
    return OXSnapshot(
        repository=scope.repository,
        mode=scope.mode,
        requested_paths=scope.paths,
        policy_version=OX_SNAPSHOT_POLICY_VERSION,
        artifacts=artifacts,
        exclusions=exclusions,
        total_content_bytes=collector.total_content_bytes,
        snapshot_sha256=snapshot_sha256,
    )
