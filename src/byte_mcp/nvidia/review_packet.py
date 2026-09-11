"""Deterministic Git-object review packets for NVIDIA routine reviews."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from types import MappingProxyType

from .review_registry import NvidiaReviewGitRepository, NvidiaReviewSubsystemDefinition

_MAX_OBJECTIVE_BYTES = 4_096
_MAX_VERIFICATION_RECORDS = 32
_MAX_VERIFICATION_STREAM_CHARS = 16_384
_MAX_CHANGED_TARGET_FILES = 200
_MAX_CHANGED_TARGET_FILE_BYTES = 524_288
_MAX_PACKET_BYTES = 3_145_728
_VERIFICATION_FIELDS = frozenset(
    {
        "id",
        "kind",
        "command",
        "exit_code",
        "stdout",
        "stderr",
        "recorded_at",
        "provenance",
    }
)
_VERIFICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class NvidiaReviewArtifact:
    logical_path: str
    categories: tuple[str, ...]
    byte_length: int
    sha256: str
    provider_text: str


@dataclass(frozen=True, slots=True)
class NvidiaReviewManifestEntry:
    logical_path: str
    categories: tuple[str, ...]
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class NvidiaReviewManifest:
    repository_alias: str
    subsystem_id: str
    base_commit: str
    target_commit: str
    entries: tuple[NvidiaReviewManifestEntry, ...]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedNvidiaReviewPacket:
    repository_alias: str
    subsystem_id: str
    base_commit: str
    target_commit: str
    objective: str
    diff: NvidiaReviewArtifact
    artifacts: tuple[NvidiaReviewArtifact, ...]
    verification: tuple[Mapping[str, object], ...]
    manifest: NvidiaReviewManifest
    serialized_packet: bytes
    total_bytes: int


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            _json_value(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("review packet data must be canonical JSON") from error
    return encoded.encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _artifact(logical_path: str, categories: Sequence[str], raw: bytes) -> NvidiaReviewArtifact:
    try:
        provider_text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"review target must be UTF-8 text: {logical_path}") from error
    return NvidiaReviewArtifact(
        logical_path=logical_path,
        categories=tuple(sorted(set(categories))),
        byte_length=len(raw),
        sha256=_sha256_bytes(raw),
        provider_text=provider_text,
    )


def _artifact_payload(artifact: NvidiaReviewArtifact) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "logical_path": artifact.logical_path,
            "categories": artifact.categories,
            "byte_length": artifact.byte_length,
            "sha256": artifact.sha256,
            "provider_text": artifact.provider_text,
        }
    )


def _verification_payload(
    verification: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    if (
        isinstance(verification, (str, bytes, bytearray, Mapping))
        or not isinstance(verification, Sequence)
        or not 1 <= len(verification) <= _MAX_VERIFICATION_RECORDS
    ):
        raise ValueError("verification evidence count is invalid")

    seen_ids: set[str] = set()
    prepared: list[Mapping[str, object]] = []
    for record in verification:
        if not isinstance(record, Mapping) or set(record) != _VERIFICATION_FIELDS:
            raise ValueError("verification evidence fields are invalid")
        verification_id = record["id"]
        if (
            not isinstance(verification_id, str)
            or _VERIFICATION_ID.fullmatch(verification_id) is None
            or verification_id in seen_ids
        ):
            raise ValueError("verification evidence ID is invalid")
        seen_ids.add(verification_id)

        exit_code = record["exit_code"]
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ValueError("verification exit_code is invalid")
        for field in ("kind", "command", "recorded_at", "provenance"):
            if not isinstance(record[field], str):
                raise ValueError(f"verification {field} is invalid")
        for field in ("stdout", "stderr"):
            value = record[field]
            if not isinstance(value, str) or len(value) > _MAX_VERIFICATION_STREAM_CHARS:
                raise ValueError(f"verification {field} is invalid")

        payload = dict(record)
        payload["sha256"] = _sha256_bytes(_canonical_json(payload))
        prepared.append(MappingProxyType({key: _freeze(value) for key, value in payload.items()}))
    return tuple(prepared)


def _path_categories(path: str, subsystem: NvidiaReviewSubsystemDefinition) -> tuple[str, ...]:
    categories: list[str] = []
    for root in subsystem.source_roots:
        if path == root or path.startswith(f"{root}/"):
            categories.append("source")
            break
    for root in subsystem.test_roots:
        if path == root or path.startswith(f"{root}/"):
            categories.append("test")
            break
    if path in subsystem.boundary_files:
        categories.append("boundary")
    if path in subsystem.context_files:
        categories.append("context")
    return tuple(categories)


def _manifest_entry(artifact: NvidiaReviewArtifact) -> NvidiaReviewManifestEntry:
    return NvidiaReviewManifestEntry(
        logical_path=artifact.logical_path,
        categories=artifact.categories,
        byte_length=artifact.byte_length,
        sha256=artifact.sha256,
    )


def _json_manifest_entry(
    logical_path: str,
    categories: tuple[str, ...],
    value: object,
) -> NvidiaReviewManifestEntry:
    raw = _canonical_json(value)
    return NvidiaReviewManifestEntry(
        logical_path=logical_path,
        categories=categories,
        byte_length=len(raw),
        sha256=_sha256_bytes(raw),
    )


def prepare_review_packet(
    repository: NvidiaReviewGitRepository,
    subsystem: NvidiaReviewSubsystemDefinition,
    base_commit: str,
    target_commit: str,
    objective: str,
    verification: Sequence[Mapping[str, object]],
) -> PreparedNvidiaReviewPacket:
    """Prepare one bounded deterministic review packet from exact Git objects."""

    if not isinstance(repository, NvidiaReviewGitRepository):
        raise ValueError("repository is invalid")
    if not isinstance(subsystem, NvidiaReviewSubsystemDefinition):
        raise ValueError("subsystem is invalid")
    if (
        not isinstance(objective, str)
        or not objective
        or len(objective.encode("utf-8")) > _MAX_OBJECTIVE_BYTES
    ):
        raise ValueError("objective is invalid")

    base = repository.resolve_commit(base_commit)
    target = repository.resolve_commit(target_commit)
    verification_payload = _verification_payload(verification)
    diff = _artifact(
        "__nvidia_review__/base-to-target.diff",
        ("diff",),
        repository.diff(base, target),
    )

    scoped_changed = tuple(
        path
        for path in repository.changed_paths(base, target)
        if _path_categories(path, subsystem)
    )
    if len(scoped_changed) > _MAX_CHANGED_TARGET_FILES:
        raise ValueError("changed target files exceed maximum")

    artifacts: list[NvidiaReviewArtifact] = []
    for path in scoped_changed:
        try:
            raw = repository.read_target_text(target, path)
        except ValueError as error:
            if str(error).startswith("target file is missing:"):
                continue
            raise
        if len(raw) > _MAX_CHANGED_TARGET_FILE_BYTES:
            raise ValueError(f"changed target file exceeds maximum size: {path}")
        artifacts.append(_artifact(path, _path_categories(path, subsystem), raw))

    artifact_tuple = tuple(artifacts)
    entries = tuple(
        sorted(
            [
                _manifest_entry(diff),
                *(_manifest_entry(artifact) for artifact in artifact_tuple),
                *(
                    _json_manifest_entry(
                        f"__nvidia_review__/verification/{record['id']}.json",
                        ("verification",),
                        record,
                    )
                    for record in verification_payload
                ),
            ],
            key=lambda item: item.logical_path,
        )
    )
    manifest_payload = {
        "repository_alias": repository.definition.alias,
        "subsystem_id": subsystem.subsystem_id,
        "base_commit": base_commit,
        "target_commit": target_commit,
        "entries": tuple(asdict(entry) for entry in entries),
    }
    manifest = NvidiaReviewManifest(
        repository_alias=repository.definition.alias,
        subsystem_id=subsystem.subsystem_id,
        base_commit=base_commit,
        target_commit=target_commit,
        entries=entries,
        manifest_sha256=_sha256_bytes(_canonical_json(manifest_payload)),
    )
    packet = MappingProxyType(
        {
            "repository_alias": repository.definition.alias,
            "subsystem_id": subsystem.subsystem_id,
            "base_commit": base_commit,
            "target_commit": target_commit,
            "objective": objective,
            "diff": _artifact_payload(diff),
            "artifacts": tuple(_artifact_payload(artifact) for artifact in artifact_tuple),
            "verification": verification_payload,
            "manifest": MappingProxyType(
                {**manifest_payload, "manifest_sha256": manifest.manifest_sha256}
            ),
        }
    )
    serialized_packet = _canonical_json(packet)
    if len(serialized_packet) > _MAX_PACKET_BYTES:
        raise ValueError("serialized review packet exceeds maximum size")

    return PreparedNvidiaReviewPacket(
        repository_alias=repository.definition.alias,
        subsystem_id=subsystem.subsystem_id,
        base_commit=base_commit,
        target_commit=target_commit,
        objective=objective,
        diff=diff,
        artifacts=artifact_tuple,
        verification=verification_payload,
        manifest=manifest,
        serialized_packet=serialized_packet,
        total_bytes=len(serialized_packet),
    )
