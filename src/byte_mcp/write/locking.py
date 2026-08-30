"""OS-backed per-project writer locks for Write V1."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from ..errors import WriteIntegrityError, WriteLockError

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@dataclass(slots=True)
class HeldProjectWriteLock:
    """A held kernel lock whose file handle is the authority token."""

    project: str
    transaction_id: str
    owner_token: str
    _handle: BinaryIO = field(repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> None:
        """Release exactly this held kernel lock and close its handle."""
        if self._released:
            return
        try:
            self._handle.seek(0)
            _unlock_handle(self._handle)
        except OSError as exc:
            raise WriteLockError("project write lock could not be released") from exc
        finally:
            self._released = True
            self._handle.close()

    def __enter__(self) -> HeldProjectWriteLock:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


class ProjectWriteLock:
    """Kernel-backed writer-lock manager scoped by case-insensitive project identity."""

    def __init__(self, state_dir: Path) -> None:
        self._root = state_dir / "locks"
        self._root.mkdir(parents=True, exist_ok=True)

    def acquire(self, project: str, transaction_id: str) -> HeldProjectWriteLock:
        """Acquire the non-blocking exclusive lock for one project."""
        project = _validate_metadata_value(project, "project")
        transaction_id = _validate_metadata_value(transaction_id, "transaction ID")
        path = self._lock_path(project)
        try:
            handle = path.open("a+b")
        except OSError as exc:
            raise WriteLockError("project write lock file could not be opened") from exc

        locked = False
        try:
            _ensure_lock_byte(handle)
            handle.seek(0)
            _lock_handle(handle)
            locked = True
            owner_token = uuid.uuid4().hex
            metadata = {
                "project": project,
                "transaction_id": transaction_id,
                "pid": os.getpid(),
                "owner_token": owner_token,
            }
            encoded = json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            handle.seek(0)
            handle.truncate(0)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            return HeldProjectWriteLock(project, transaction_id, owner_token, handle)
        except (BlockingIOError, OSError) as exc:
            if locked:
                try:
                    handle.seek(0)
                    _unlock_handle(handle)
                except OSError:
                    pass
            handle.close()
            raise WriteLockError("project write lock is already held or unavailable") from exc
        except Exception:
            if locked:
                try:
                    handle.seek(0)
                    _unlock_handle(handle)
                except OSError:
                    pass
            handle.close()
            raise

    def _lock_path(self, project: str) -> Path:
        digest = hashlib.sha256(project.casefold().encode("utf-8")).hexdigest()
        return self._root / f"{digest}.lock"


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\x00")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)


def _lock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError from exc
    else:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError from exc


def _unlock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_metadata_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\r" in value or "\n" in value:
        raise WriteIntegrityError(f"project write lock {label} is malformed")
    if len(value) > 256:
        raise WriteIntegrityError(f"project write lock {label} is malformed")
    return value
