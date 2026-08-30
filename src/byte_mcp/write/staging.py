"""Protected staging, UTF-8 profiles, and deterministic directory manifests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..errors import WriteIntegrityError, WriteLimitError, WritePathError
from ..security import is_denied_relative
from .paths import assert_safe_existing_entry

_UTF8_BOM = b"\xef\xbb\xbf"
_PRIVATE_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


@dataclass(frozen=True, slots=True)
class TextFileProfile:
    """Encoding details that must survive replacement of an existing text file."""

    has_utf8_bom: bool
    newline: str | None


@dataclass(frozen=True, slots=True)
class StagedBlob:
    """Digest-bound private staged content."""

    blob_id: str
    transaction_id: str
    operation_index: int
    sha256: str
    byte_count: int
    absolute: Path


@dataclass(frozen=True, slots=True)
class DirectoryManifestEntry:
    """One canonical directory-manifest row."""

    relative_path: str
    entry_type: str
    byte_count: int
    sha256: str | None


@dataclass(frozen=True, slots=True)
class DirectoryManifest:
    """Bounded deterministic evidence for an existing directory tree."""

    entries: tuple[DirectoryManifestEntry, ...]
    entry_count: int
    byte_count: int
    digest: str


def read_utf8_profile(data: bytes) -> tuple[str, TextFileProfile]:
    """Decode supported text without normalizing its original newline bytes."""
    if not isinstance(data, bytes):
        raise WriteIntegrityError("text content must be supplied as bytes")
    has_utf8_bom = data.startswith(_UTF8_BOM)
    payload = data[len(_UTF8_BOM) :] if has_utf8_bom else data
    if b"\x00" in payload:
        raise WriteIntegrityError("text content contains a NUL byte")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WriteIntegrityError("content is not valid UTF-8 text") from exc
    return text, TextFileProfile(has_utf8_bom, _detect_newline(text))


def encode_with_profile(text: str, profile: TextFileProfile) -> bytes:
    """Encode replacement text while preserving an existing file's text profile."""
    if not isinstance(text, str) or "\x00" in text:
        raise WriteIntegrityError("replacement content must be NUL-free text")
    normalized = text
    if profile.newline is not None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\n", profile.newline)
    encoded = normalized.encode("utf-8")
    return (_UTF8_BOM + encoded) if profile.has_utf8_bom else encoded


class StagingStore:
    """Private digest-bound storage for bytes prepared by a transaction."""

    def __init__(self, state_dir: Path) -> None:
        self._root = state_dir / "staging"
        self._root.mkdir(parents=True, exist_ok=True)

    def stage_bytes(self, transaction_id: str, operation_index: int, data: bytes) -> StagedBlob:
        _validate_private_component(transaction_id, prefix="TX-")
        invalid_index = (
            isinstance(operation_index, bool)
            or not isinstance(operation_index, int)
            or operation_index < 0
        )
        if invalid_index:
            raise WriteIntegrityError("staging operation index must be a non-negative integer")
        if not isinstance(data, bytes):
            raise WriteIntegrityError("staged content must be bytes")

        blob_id = f"OP-{operation_index:04d}"
        transaction_dir = self._root / transaction_id
        transaction_dir.mkdir(parents=True, exist_ok=True)
        absolute = transaction_dir / f"{blob_id}.blob"
        _atomic_write_bytes(absolute, data)
        return StagedBlob(
            blob_id=blob_id,
            transaction_id=transaction_id,
            operation_index=operation_index,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_count=len(data),
            absolute=absolute,
        )

    def verify(self, staged: StagedBlob) -> None:
        try:
            assert_safe_existing_entry(staged.absolute)
            data = staged.absolute.read_bytes()
        except (OSError, WritePathError) as exc:
            raise WriteIntegrityError("staged content cannot be inspected safely") from exc
        if len(data) != staged.byte_count or hashlib.sha256(data).hexdigest() != staged.sha256:
            raise WriteIntegrityError("staged content failed integrity verification")

    def read_bytes(self, staged: StagedBlob) -> bytes:
        self.verify(staged)
        try:
            return staged.absolute.read_bytes()
        except OSError as exc:
            raise WriteIntegrityError("staged content cannot be read safely") from exc


def directory_manifest(
    path: Path,
    max_entries: int,
    max_bytes: int,
    require_text: bool,
) -> DirectoryManifest:
    """Compute bounded, case-stable evidence for one safe directory tree."""
    _validate_positive_limit(max_entries, "max_entries")
    _validate_positive_limit(max_bytes, "max_bytes")
    try:
        assert_safe_existing_entry(path)
        root_stat = path.lstat()
    except (OSError, WritePathError) as exc:
        if isinstance(exc, WritePathError):
            raise
        raise WritePathError("directory tree cannot be inspected safely") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise WritePathError("directory manifest source must be a directory")

    rows: list[DirectoryManifestEntry] = []
    total_bytes = 0

    def walk(current: Path) -> None:
        nonlocal total_bytes
        try:
            children = sorted(current.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        except OSError as exc:
            raise WritePathError("directory tree cannot be enumerated safely") from exc
        for child in children:
            try:
                relative = child.relative_to(path)
            except ValueError as exc:
                raise WritePathError("directory entry escaped the manifest root") from exc
            if is_denied_relative(relative):
                raise WritePathError("directory tree contains a secret-denied entry")
            assert_safe_existing_entry(child)
            try:
                child_stat = child.lstat()
            except OSError as exc:
                raise WritePathError("directory entry cannot be inspected safely") from exc
            relative_text = relative.as_posix()
            if stat.S_ISDIR(child_stat.st_mode):
                rows.append(DirectoryManifestEntry(relative_text, "directory", 0, None))
                _check_entry_limit(rows, max_entries)
                walk(child)
                continue
            if not stat.S_ISREG(child_stat.st_mode):
                raise WritePathError("directory tree contains an unsupported entry type")

            data = _read_stable_file(child)
            if require_text:
                read_utf8_profile(data)
            total_bytes += len(data)
            if total_bytes > max_bytes:
                raise WriteLimitError("directory tree exceeds the configured byte limit")
            rows.append(
                DirectoryManifestEntry(
                    relative_path=relative_text,
                    entry_type="file",
                    byte_count=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )
            _check_entry_limit(rows, max_entries)

    walk(path)
    rows.sort(key=lambda row: (row.relative_path.casefold(), row.relative_path))
    canonical_rows = [
        {
            "relative_path": row.relative_path,
            "entry_type": row.entry_type,
            "byte_count": row.byte_count,
            "sha256": row.sha256,
        }
        for row in rows
    ]
    canonical = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return DirectoryManifest(
        entries=tuple(rows),
        entry_count=len(rows),
        byte_count=total_bytes,
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _detect_newline(text: str) -> str | None:
    styles: set[str] = set()
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                styles.add("\r\n")
                index += 2
                continue
            styles.add("\r")
        elif character == "\n":
            styles.add("\n")
        index += 1
    return next(iter(styles)) if len(styles) == 1 else None


def _read_stable_file(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise WritePathError("directory tree contains an unsafe file entry")
            data = handle.read()
            after = os.fstat(handle.fileno())
    except WritePathError:
        raise
    except OSError as exc:
        raise WritePathError("directory file cannot be read safely") from exc
    if _stat_identity(before) != _stat_identity(after):
        raise WriteIntegrityError("directory file changed while it was being inspected")
    return data


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _validate_positive_limit(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WriteLimitError(f"{name} must be a positive integer")


def _check_entry_limit(rows: list[DirectoryManifestEntry], max_entries: int) -> None:
    if len(rows) > max_entries:
        raise WriteLimitError("directory tree exceeds the configured entry limit")


def _validate_private_component(value: str, prefix: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or len(value) > 160
        or any(character not in _PRIVATE_ID_CHARACTERS for character in value)
    ):
        raise WriteIntegrityError("private write-state identifier is malformed")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise WriteIntegrityError("private staged content could not be persisted") from exc


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
        raise WriteIntegrityError("private write-state directory could not be flushed") from exc
