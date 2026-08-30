"""Verified recovery snapshots and retention for Write V1."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..errors import (
    WriteConflictError,
    WriteIntegrityError,
    WritePathError,
    WriteStaleStateError,
)
from .paths import assert_safe_existing_entry
from .policy import WritePolicy
from .staging import DirectoryManifest, directory_manifest


@dataclass(frozen=True, slots=True)
class RecoveryItem:
    """Digest-bound metadata for one recoverable filesystem snapshot."""

    recovery_id: str
    source_relative: str
    kind: str
    source_sha256: str | None
    source_directory_digest: str | None
    mode: int
    atime_ns: int
    mtime_ns: int
    byte_count: int
    entry_count: int
    transaction_id: str
    created_at: datetime
    require_text: bool


@dataclass(frozen=True, slots=True)
class PruneReport:
    """Deterministic result of applying recovery retention policy."""

    removed_ids: tuple[str, ...]
    bytes_before: int
    bytes_after: int
    limit_exceeded: bool


@dataclass(frozen=True, slots=True)
class _FileCopyEvidence:
    sha256: str
    byte_count: int
    mode: int
    atime_ns: int
    mtime_ns: int
    source_signature: tuple[int, int, int, int]


class RecoveryStore:
    """Private recovery storage for existing-state mutations."""

    def __init__(self, state_dir: Path) -> None:
        self._root = state_dir / "recovery"
        self._root.mkdir(parents=True, exist_ok=True)

    def snapshot_file(
        self,
        source: Path,
        *,
        source_relative: str,
        expected_sha256: str,
        transaction_id: str,
        created_at: datetime | None = None,
    ) -> RecoveryItem:
        """Copy and hash one existing file from the same stable source handle."""
        recovery_id = _new_recovery_id()
        temporary, final = self._new_item_paths(recovery_id)
        created = _require_utc_datetime(created_at or datetime.now(UTC))
        try:
            temporary.mkdir(parents=False)
            evidence = _copy_file_payload(source, temporary / "payload")
            if evidence.sha256 != expected_sha256:
                raise WriteStaleStateError("source SHA-256 no longer matches the prior read")
            _assert_source_unchanged(source, evidence.source_signature)
            item = RecoveryItem(
                recovery_id=recovery_id,
                source_relative=_validate_source_relative(source_relative),
                kind="file",
                source_sha256=evidence.sha256,
                source_directory_digest=None,
                mode=evidence.mode,
                atime_ns=evidence.atime_ns,
                mtime_ns=evidence.mtime_ns,
                byte_count=evidence.byte_count,
                entry_count=1,
                transaction_id=transaction_id,
                created_at=created,
                require_text=False,
            )
            _write_metadata(temporary / "metadata.json", item)
            os.replace(temporary, final)
            _fsync_directory(self._root)
            return item
        except Exception:
            _remove_private_tree(temporary)
            raise

    def snapshot_directory(
        self,
        source: Path,
        *,
        source_relative: str,
        transaction_id: str,
        max_entries: int,
        max_bytes: int,
        require_text: bool,
        created_at: datetime | None = None,
    ) -> RecoveryItem:
        """Copy a safe directory and prove copied and live tree digests agree."""
        before = directory_manifest(source, max_entries, max_bytes, require_text)
        source_stat = _safe_directory_stat(source)
        recovery_id = _new_recovery_id()
        temporary, final = self._new_item_paths(recovery_id)
        created = _require_utc_datetime(created_at or datetime.now(UTC))
        try:
            temporary.mkdir(parents=False)
            copied = _copy_directory_payload(
                source,
                temporary / "payload",
                max_entries=max_entries,
                max_bytes=max_bytes,
                require_text=require_text,
            )
            after = directory_manifest(source, max_entries, max_bytes, require_text)
            if before.digest != copied.digest or before.digest != after.digest:
                raise WriteStaleStateError("source directory changed while recovery was created")
            current_stat = _safe_directory_stat(source)
            if _directory_identity(source_stat) != _directory_identity(current_stat):
                raise WriteStaleStateError("source directory changed while recovery was created")
            item = RecoveryItem(
                recovery_id=recovery_id,
                source_relative=_validate_source_relative(source_relative),
                kind="directory",
                source_sha256=None,
                source_directory_digest=before.digest,
                mode=stat.S_IMODE(source_stat.st_mode),
                atime_ns=source_stat.st_atime_ns,
                mtime_ns=source_stat.st_mtime_ns,
                byte_count=before.byte_count,
                entry_count=before.entry_count,
                transaction_id=transaction_id,
                created_at=created,
                require_text=require_text,
            )
            _write_metadata(temporary / "metadata.json", item)
            os.replace(temporary, final)
            _fsync_directory(self._root)
            return item
        except Exception:
            _remove_private_tree(temporary)
            raise

    def verify(self, recovery_id: str) -> RecoveryItem:
        """Verify metadata and payload integrity before any recovery use."""
        item_dir = self._item_dir(recovery_id)
        item = _read_metadata(item_dir / "metadata.json", recovery_id)
        payload = item_dir / "payload"
        if item.kind == "file":
            sha256, byte_count = _hash_stable_file(payload)
            if sha256 != item.source_sha256 or byte_count != item.byte_count:
                raise WriteIntegrityError("recovery payload failed integrity verification")
        elif item.kind == "directory":
            manifest = directory_manifest(
                payload,
                max(1, item.entry_count),
                max(1, item.byte_count),
                item.require_text,
            )
            if (
                manifest.digest != item.source_directory_digest
                or manifest.entry_count != item.entry_count
                or manifest.byte_count != item.byte_count
            ):
                raise WriteIntegrityError("recovery directory failed integrity verification")
        else:
            raise WriteIntegrityError("recovery metadata contains an unsupported item kind")
        return item

    def materialize(self, recovery_id: str, destination: Path) -> None:
        """Materialize verified recovery bytes to an absent destination."""
        item = self.verify(recovery_id)
        _require_absent(destination)
        item_dir = self._item_dir(recovery_id)
        payload = item_dir / "payload"
        try:
            if item.kind == "file":
                _materialize_file(payload, destination, item)
            else:
                shutil.copytree(payload, destination, copy_function=shutil.copy2, symlinks=False)
                os.chmod(destination, item.mode)
                os.utime(destination, ns=(item.atime_ns, item.mtime_ns))
                restored = directory_manifest(
                    destination,
                    max(1, item.entry_count),
                    max(1, item.byte_count),
                    item.require_text,
                )
                if restored.digest != item.source_directory_digest:
                    raise WriteIntegrityError("materialized recovery directory failed verification")
        except Exception:
            _remove_materialized(destination)
            raise

    def prune(
        self,
        now: datetime,
        policy: WritePolicy,
        protected_recovery_ids: frozenset[str],
    ) -> PruneReport:
        """Prune unprotected recovery items by age, then by oldest-first size pressure."""
        current = _require_utc_datetime(now)
        items = self._verified_items()
        bytes_before = sum(item.byte_count for item in items)
        bytes_after = bytes_before
        removed: list[str] = []
        cutoff = current - timedelta(days=policy.recovery_retention_days)

        expired = sorted(
            (
                item
                for item in items
                if item.recovery_id not in protected_recovery_ids and item.created_at < cutoff
            ),
            key=_recovery_age_key,
        )
        removed_set: set[str] = set()
        for item in expired:
            self._remove_item(item.recovery_id)
            removed.append(item.recovery_id)
            removed_set.add(item.recovery_id)
            bytes_after -= item.byte_count

        if bytes_after > policy.recovery_max_bytes:
            remaining = sorted(
                (
                    item
                    for item in items
                    if item.recovery_id not in protected_recovery_ids
                    and item.recovery_id not in removed_set
                ),
                key=_recovery_age_key,
            )
            for item in remaining:
                if bytes_after <= policy.recovery_max_bytes:
                    break
                self._remove_item(item.recovery_id)
                removed.append(item.recovery_id)
                bytes_after -= item.byte_count

        return PruneReport(
            removed_ids=tuple(removed),
            bytes_before=bytes_before,
            bytes_after=bytes_after,
            limit_exceeded=bytes_after > policy.recovery_max_bytes,
        )

    def _new_item_paths(self, recovery_id: str) -> tuple[Path, Path]:
        final = self._root / recovery_id
        temporary = self._root / f".{recovery_id}.{uuid.uuid4().hex}.tmp"
        if final.exists():
            raise WriteIntegrityError("recovery identifier collision")
        return temporary, final

    def _item_dir(self, recovery_id: str) -> Path:
        _validate_recovery_id(recovery_id)
        item_dir = self._root / recovery_id
        try:
            assert_safe_existing_entry(item_dir)
        except (OSError, WritePathError) as exc:
            raise WriteIntegrityError("recovery item cannot be inspected safely") from exc
        if not item_dir.is_dir():
            raise WriteIntegrityError("recovery item is not a directory")
        return item_dir

    def _verified_items(self) -> list[RecoveryItem]:
        try:
            candidates = sorted(
                (entry for entry in self._root.iterdir() if entry.name.startswith("RCV-")),
                key=lambda entry: entry.name,
            )
        except OSError as exc:
            raise WriteIntegrityError("recovery store cannot be enumerated safely") from exc
        return [self.verify(candidate.name) for candidate in candidates]

    def _remove_item(self, recovery_id: str) -> None:
        item_dir = self._item_dir(recovery_id)
        try:
            shutil.rmtree(item_dir)
            _fsync_directory(self._root)
        except OSError as exc:
            raise WriteIntegrityError("recovery item could not be pruned safely") from exc


def _copy_file_payload(source: Path, destination: Path) -> _FileCopyEvidence:
    """Copy one source handle while hashing and proving it stayed stable."""
    assert_safe_existing_entry(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with source.open("rb") as source_handle:
            before = os.fstat(source_handle.fileno())
            _validate_open_file_stat(before)
            with temporary.open("xb") as destination_handle:
                while True:
                    block = source_handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    byte_count += len(block)
                    destination_handle.write(block)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            after = os.fstat(source_handle.fileno())
        if _file_identity(before) != _file_identity(after):
            raise WriteStaleStateError("source file changed while recovery was created")
        assert_safe_existing_entry(source)
        if _file_identity(source.lstat()) != _file_identity(after):
            raise WriteStaleStateError("source file changed while recovery was created")
        os.replace(temporary, destination)
        mode = stat.S_IMODE(before.st_mode)
        os.chmod(destination, mode)
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
        _fsync_directory(destination.parent)
        return _FileCopyEvidence(
            sha256=digest.hexdigest(),
            byte_count=byte_count,
            mode=mode,
            atime_ns=before.st_atime_ns,
            mtime_ns=before.st_mtime_ns,
            source_signature=_file_identity(after),
        )
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _copy_directory_payload(
    source: Path,
    destination: Path,
    *,
    max_entries: int,
    max_bytes: int,
    require_text: bool,
) -> DirectoryManifest:
    """Copy a previously validated safe tree without traversing links."""
    source_manifest = directory_manifest(source, max_entries, max_bytes, require_text)
    destination.mkdir(parents=False)
    try:
        for row in source_manifest.entries:
            source_entry = source / Path(*row.relative_path.split("/"))
            destination_entry = destination / Path(*row.relative_path.split("/"))
            assert_safe_existing_entry(source_entry)
            if row.entry_type == "directory":
                destination_entry.mkdir()
            else:
                evidence = _copy_file_payload(source_entry, destination_entry)
                if evidence.sha256 != row.sha256 or evidence.byte_count != row.byte_count:
                    raise WriteStaleStateError(
                        "source directory changed while recovery was created"
                    )
        directory_rows = [
            row for row in source_manifest.entries if row.entry_type == "directory"
        ]
        for row in reversed(directory_rows):
            source_entry = source / Path(*row.relative_path.split("/"))
            destination_entry = destination / Path(*row.relative_path.split("/"))
            assert_safe_existing_entry(source_entry)
            shutil.copystat(source_entry, destination_entry, follow_symlinks=False)
        assert_safe_existing_entry(source)
        shutil.copystat(source, destination, follow_symlinks=False)
        copied = directory_manifest(destination, max_entries, max_bytes, require_text)
        if copied.digest != source_manifest.digest:
            raise WriteStaleStateError("source directory changed while recovery was created")
        return copied
    except Exception:
        _remove_private_tree(destination)
        raise


def _assert_source_unchanged(source: Path, expected: tuple[int, int, int, int]) -> None:
    try:
        assert_safe_existing_entry(source)
        current = source.lstat()
    except (OSError, WritePathError) as exc:
        raise WriteStaleStateError("source file changed while recovery was created") from exc
    if _file_identity(current) != expected:
        raise WriteStaleStateError("source file changed while recovery was created")


def _hash_stable_file(path: Path) -> tuple[str, int]:
    try:
        assert_safe_existing_entry(path)
        digest = hashlib.sha256()
        byte_count = 0
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            _validate_open_file_stat(before)
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                byte_count += len(block)
            after = os.fstat(handle.fileno())
        if _file_identity(before) != _file_identity(after):
            raise WriteIntegrityError("recovery file changed while it was verified")
        return digest.hexdigest(), byte_count
    except WriteIntegrityError:
        raise
    except (OSError, WritePathError) as exc:
        raise WriteIntegrityError("recovery file cannot be inspected safely") from exc


def _materialize_file(payload: Path, destination: Path, item: RecoveryItem) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        digest = hashlib.sha256()
        byte_count = 0
        with payload.open("rb") as source_handle, temporary.open("xb") as destination_handle:
            while True:
                block = source_handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                byte_count += len(block)
                destination_handle.write(block)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        if digest.hexdigest() != item.source_sha256 or byte_count != item.byte_count:
            raise WriteIntegrityError("recovery payload changed during materialization")
        os.chmod(temporary, item.mode)
        os.utime(temporary, ns=(item.atime_ns, item.mtime_ns))
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_metadata(path: Path, item: RecoveryItem) -> None:
    metadata = _item_metadata(item)
    canonical = _canonical_json(metadata)
    envelope = {
        "metadata": metadata,
        "metadata_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    _atomic_write_bytes(path, _canonical_json(envelope))


def _read_metadata(path: Path, expected_recovery_id: str) -> RecoveryItem:
    try:
        assert_safe_existing_entry(path)
        raw = path.read_text(encoding="utf-8")
        envelope = json.loads(raw, object_pairs_hook=_reject_duplicate_members)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, WritePathError) as exc:
        raise WriteIntegrityError("recovery metadata cannot be read safely") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"metadata", "metadata_sha256"}:
        raise WriteIntegrityError("recovery metadata envelope is malformed")
    metadata = envelope["metadata"]
    expected_digest = envelope["metadata_sha256"]
    if not isinstance(metadata, dict) or not isinstance(expected_digest, str):
        raise WriteIntegrityError("recovery metadata envelope is malformed")
    if hashlib.sha256(_canonical_json(metadata)).hexdigest() != expected_digest:
        raise WriteIntegrityError("recovery metadata failed integrity verification")
    item = _metadata_item(metadata)
    if item.recovery_id != expected_recovery_id:
        raise WriteIntegrityError("recovery metadata identifier does not match its storage key")
    return item


def _item_metadata(item: RecoveryItem) -> dict[str, object]:
    return {
        "recovery_id": item.recovery_id,
        "source_relative": item.source_relative,
        "kind": item.kind,
        "source_sha256": item.source_sha256,
        "source_directory_digest": item.source_directory_digest,
        "mode": item.mode,
        "atime_ns": item.atime_ns,
        "mtime_ns": item.mtime_ns,
        "byte_count": item.byte_count,
        "entry_count": item.entry_count,
        "transaction_id": item.transaction_id,
        "created_at": item.created_at.isoformat(),
        "require_text": item.require_text,
    }


def _metadata_item(metadata: dict[str, Any]) -> RecoveryItem:
    required = {
        "recovery_id",
        "source_relative",
        "kind",
        "source_sha256",
        "source_directory_digest",
        "mode",
        "atime_ns",
        "mtime_ns",
        "byte_count",
        "entry_count",
        "transaction_id",
        "created_at",
        "require_text",
    }
    if set(metadata) != required:
        raise WriteIntegrityError("recovery metadata fields are incomplete or unsupported")
    try:
        item = RecoveryItem(
            recovery_id=str(metadata["recovery_id"]),
            source_relative=str(metadata["source_relative"]),
            kind=str(metadata["kind"]),
            source_sha256=_optional_string(metadata["source_sha256"]),
            source_directory_digest=_optional_string(metadata["source_directory_digest"]),
            mode=_integer(metadata["mode"], "mode"),
            atime_ns=_integer(metadata["atime_ns"], "atime_ns"),
            mtime_ns=_integer(metadata["mtime_ns"], "mtime_ns"),
            byte_count=_integer(metadata["byte_count"], "byte_count"),
            entry_count=_integer(metadata["entry_count"], "entry_count"),
            transaction_id=str(metadata["transaction_id"]),
            created_at=_require_utc_datetime(datetime.fromisoformat(str(metadata["created_at"]))),
            require_text=_boolean(metadata["require_text"], "require_text"),
        )
    except (ValueError, TypeError) as exc:
        raise WriteIntegrityError("recovery metadata values are malformed") from exc
    _validate_recovery_id(item.recovery_id)
    _validate_source_relative(item.source_relative)
    if item.kind not in {"file", "directory"}:
        raise WriteIntegrityError("recovery metadata contains an unsupported item kind")
    if item.kind == "file" and item.source_sha256 is None:
        raise WriteIntegrityError("file recovery metadata is missing its SHA-256")
    if item.kind == "directory" and item.source_directory_digest is None:
        raise WriteIntegrityError("directory recovery metadata is missing its digest")
    return item


def _safe_directory_stat(path: Path) -> os.stat_result:
    try:
        assert_safe_existing_entry(path)
        value = path.lstat()
    except (OSError, WritePathError) as exc:
        if isinstance(exc, WritePathError):
            raise
        raise WritePathError("source directory cannot be inspected safely") from exc
    if not stat.S_ISDIR(value.st_mode):
        raise WritePathError("recovery directory source must be a directory")
    return value


def _validate_open_file_stat(value: os.stat_result) -> None:
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise WritePathError("recovery source is not a safe regular file")


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mtime_ns


def _new_recovery_id() -> str:
    return f"RCV-{uuid.uuid4().hex}"


def _validate_recovery_id(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("RCV-") or len(value) != 36:
        raise WriteIntegrityError("recovery identifier is malformed")
    if any(character not in "0123456789abcdef" for character in value[4:]):
        raise WriteIntegrityError("recovery identifier is malformed")


def _validate_source_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise WriteIntegrityError("recovery source path is malformed")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WriteIntegrityError("recovery source path is malformed")
    return value


def _require_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WriteIntegrityError("recovery timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WriteIntegrityError("recovery metadata string field is malformed")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WriteIntegrityError(f"recovery metadata {name} is malformed")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise WriteIntegrityError(f"recovery metadata {name} is malformed")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WriteIntegrityError("recovery metadata contains duplicate JSON members")
        result[key] = value
    return result


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise WriteIntegrityError("recovery metadata could not be persisted") from exc


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise WriteIntegrityError("recovery state directory could not be flushed") from exc


def _require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise WriteIntegrityError("recovery destination cannot be inspected safely") from exc
    raise WriteConflictError("recovery destination must be absent")


def _remove_private_tree(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError:
        pass


def _remove_materialized(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _recovery_age_key(item: RecoveryItem) -> tuple[datetime, str]:
    return item.created_at, item.recovery_id
