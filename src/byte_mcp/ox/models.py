"""Small immutable records for the clean-room OX lifecycle."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath

from byte_mcp.providers.requests import PreparedProviderRequest

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_ID_RE = re.compile(r"^OX-\d{6}$")
_MAX_OBJECTIVE_CHARS = 16_384
_MAX_CLASSIFICATION_CHARS = 128


def _require_nonempty_text(value: object, field_name: str, *, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(character) < 32 and character not in "\t\n" for character in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_logical_path(value: object, field_name: str = "logical_path") -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field_name} must be a normalized repository-relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field_name} must be a normalized repository-relative POSIX path")
    if path.as_posix() != value:
        raise ValueError(f"{field_name} must be a normalized repository-relative POSIX path")
    return value


class OXReviewMode(StrEnum):
    FULL_REPOSITORY = "FULL_REPOSITORY"
    BOUNDED = "BOUNDED"


class OXReviewState(StrEnum):
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class OXReviewScope:
    repository: str
    mode: OXReviewMode
    paths: tuple[str, ...]
    objective: str

    def __post_init__(self) -> None:
        _require_nonempty_text(self.repository, "repository", max_chars=128)
        if not isinstance(self.mode, OXReviewMode):
            raise ValueError("mode is invalid")
        if not isinstance(self.paths, tuple):
            raise ValueError("paths must be a tuple")
        _require_nonempty_text(self.objective, "objective", max_chars=_MAX_OBJECTIVE_CHARS)
        if self.mode is OXReviewMode.FULL_REPOSITORY and self.paths:
            raise ValueError("FULL_REPOSITORY scope must not contain paths")
        if self.mode is OXReviewMode.BOUNDED and not self.paths:
            raise ValueError("BOUNDED scope requires at least one path")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("paths must not contain duplicates")
        for path in self.paths:
            _require_logical_path(path, "path")


@dataclass(frozen=True, slots=True)
class OXSnapshotExclusion:
    logical_path: str
    reason: str

    def __post_init__(self) -> None:
        _require_logical_path(self.logical_path)
        _require_nonempty_text(self.reason, "reason", max_chars=128)


@dataclass(frozen=True, slots=True, repr=False)
class OXArtifact:
    logical_path: str
    content: bytes = field(repr=False)
    byte_length: int
    content_sha256: str
    classification: str
    git_state: str | None

    def __post_init__(self) -> None:
        _require_logical_path(self.logical_path)
        if not isinstance(self.content, bytes):
            raise ValueError("content must be bytes")
        if isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int):
            raise ValueError("byte_length is invalid")
        if self.byte_length != len(self.content):
            raise ValueError("byte_length does not match content")
        _require_sha256(self.content_sha256, "content_sha256")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 does not match content")
        _require_nonempty_text(
            self.classification,
            "classification",
            max_chars=_MAX_CLASSIFICATION_CHARS,
        )
        if self.git_state is not None:
            _require_nonempty_text(self.git_state, "git_state", max_chars=64)

    def __repr__(self) -> str:
        return (
            "OXArtifact("
            f"logical_path={self.logical_path!r}, byte_length={self.byte_length!r}, "
            f"content_sha256={self.content_sha256!r}, classification={self.classification!r}, "
            f"git_state={self.git_state!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OXSnapshot:
    repository: str
    mode: OXReviewMode
    requested_paths: tuple[str, ...]
    policy_version: str
    artifacts: tuple[OXArtifact, ...]
    exclusions: tuple[OXSnapshotExclusion, ...]
    total_content_bytes: int
    snapshot_sha256: str

    def __post_init__(self) -> None:
        _require_nonempty_text(self.repository, "repository", max_chars=128)
        if not isinstance(self.mode, OXReviewMode):
            raise ValueError("mode is invalid")
        if not isinstance(self.requested_paths, tuple):
            raise ValueError("requested_paths must be a tuple")
        for path in self.requested_paths:
            _require_logical_path(path, "requested_path")
        _require_nonempty_text(self.policy_version, "policy_version", max_chars=128)
        if not isinstance(self.artifacts, tuple) or not all(
            isinstance(artifact, OXArtifact) for artifact in self.artifacts
        ):
            raise ValueError("artifacts are invalid")
        if not isinstance(self.exclusions, tuple) or not all(
            isinstance(exclusion, OXSnapshotExclusion) for exclusion in self.exclusions
        ):
            raise ValueError("exclusions are invalid")
        expected_total = sum(artifact.byte_length for artifact in self.artifacts)
        if self.total_content_bytes != expected_total:
            raise ValueError("total_content_bytes does not match artifacts")
        _require_sha256(self.snapshot_sha256, "snapshot_sha256")

    def __repr__(self) -> str:
        return (
            "OXSnapshot("
            f"repository={self.repository!r}, mode={self.mode!r}, "
            f"requested_paths={self.requested_paths!r}, policy_version={self.policy_version!r}, "
            f"artifact_count={len(self.artifacts)!r}, exclusion_count={len(self.exclusions)!r}, "
            f"total_content_bytes={self.total_content_bytes!r}, "
            f"snapshot_sha256={self.snapshot_sha256!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OXPreparedReview:
    review_id: str
    scope: OXReviewScope
    snapshot: OXSnapshot
    packet_bytes: bytes = field(repr=False)
    packet_sha256: str
    prepared_request: PreparedProviderRequest = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.review_id, str) or _REVIEW_ID_RE.fullmatch(self.review_id) is None:
            raise ValueError("review_id is invalid")
        if not isinstance(self.scope, OXReviewScope):
            raise ValueError("scope is invalid")
        if not isinstance(self.snapshot, OXSnapshot):
            raise ValueError("snapshot is invalid")
        if (
            self.scope.repository != self.snapshot.repository
            or self.scope.mode is not self.snapshot.mode
        ):
            raise ValueError("scope and snapshot identity do not match")
        if self.scope.paths != self.snapshot.requested_paths:
            raise ValueError("scope paths and snapshot paths do not match")
        if not isinstance(self.packet_bytes, bytes) or not self.packet_bytes:
            raise ValueError("packet_bytes are invalid")
        _require_sha256(self.packet_sha256, "packet_sha256")
        if hashlib.sha256(self.packet_bytes).hexdigest() != self.packet_sha256:
            raise ValueError("packet_sha256 does not match packet_bytes")
        if not isinstance(self.prepared_request, PreparedProviderRequest):
            raise ValueError("prepared_request is invalid")

    def __repr__(self) -> str:
        return (
            "OXPreparedReview("
            f"review_id={self.review_id!r}, scope={self.scope!r}, snapshot={self.snapshot!r}, "
            f"packet_sha256={self.packet_sha256!r}, "
            f"request_sha256={self.prepared_request.request_sha256!r})"
        )
