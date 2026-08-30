"""Durable, content-free transaction journals for Write V1."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import WriteIntegrityError, WriteStaleStateError, WriteTransactionError


class TransactionStatus(str, Enum):
    """Durable transaction lifecycle states."""

    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    PREPARED = "PREPARED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class ProjectWriteState(str, Enum):
    """Whether controlled writes may proceed for one project."""

    NORMAL = "NORMAL"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """Immutable snapshot of one durable transaction journal."""

    transaction_id: str
    project: str
    status: TransactionStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object]
    steps: tuple[dict[str, object], ...]
    result: dict[str, object] | None


_ALLOWED_TRANSITIONS: dict[TransactionStatus, frozenset[TransactionStatus]] = {
    TransactionStatus.REQUESTED: frozenset(
        {TransactionStatus.VALIDATING, TransactionStatus.REJECTED}
    ),
    TransactionStatus.VALIDATING: frozenset(
        {TransactionStatus.PREPARED, TransactionStatus.REJECTED, TransactionStatus.FAILED}
    ),
    TransactionStatus.PREPARED: frozenset(
        {TransactionStatus.COMMITTING, TransactionStatus.EXPIRED, TransactionStatus.FAILED}
    ),
    TransactionStatus.COMMITTING: frozenset(
        {
            TransactionStatus.COMMITTED,
            TransactionStatus.ROLLING_BACK,
            TransactionStatus.FAILED,
        }
    ),
    TransactionStatus.ROLLING_BACK: frozenset(
        {TransactionStatus.ROLLED_BACK, TransactionStatus.FAILED}
    ),
    TransactionStatus.COMMITTED: frozenset(),
    TransactionStatus.REJECTED: frozenset(),
    TransactionStatus.EXPIRED: frozenset(),
    TransactionStatus.ROLLED_BACK: frozenset(),
    TransactionStatus.FAILED: frozenset(),
}

_INCOMPLETE_STATUSES = frozenset(
    {
        TransactionStatus.PREPARED,
        TransactionStatus.COMMITTING,
        TransactionStatus.ROLLING_BACK,
        TransactionStatus.FAILED,
    }
)

_DENIED_CONTENT_KEYS = frozenset(
    {
        "content",
        "source_content",
        "replacement_content",
        "expected_text",
        "replacement_text",
        "edits",
        "patch",
        "patch_body",
        "authorization",
        "authorization_header",
    }
)


class TransactionJournal:
    """Atomic JSON journal store keyed by opaque transaction IDs."""

    def __init__(self, state_dir: Path) -> None:
        self._root = state_dir / "journal"
        self._root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        project: str,
        metadata: dict[str, object] | None = None,
        *,
        now: datetime | None = None,
    ) -> TransactionRecord:
        """Create a new REQUESTED transaction with content-free metadata."""
        project = _validate_project(project)
        metadata_copy = _validate_safe_mapping(metadata or {}, "metadata")
        timestamp = _utc(now or datetime.now(UTC))
        transaction_id = f"TX-{uuid.uuid4().hex}"
        record = TransactionRecord(
            transaction_id=transaction_id,
            project=project,
            status=TransactionStatus.REQUESTED,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=metadata_copy,
            steps=(),
            result=None,
        )
        path = self._path(transaction_id)
        if path.exists():
            raise WriteIntegrityError("transaction identifier collision")
        self._write(record)
        return _clone_record(record)

    def read(self, transaction_id: str) -> TransactionRecord:
        """Read and integrity-check exactly one transaction journal."""
        path = self._path(transaction_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WriteTransactionError("unknown transaction ID") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise WriteIntegrityError("transaction journal cannot be read safely") from exc

        try:
            envelope = json.loads(raw, object_pairs_hook=_reject_duplicate_members)
        except json.JSONDecodeError as exc:
            raise WriteIntegrityError("transaction journal is malformed") from exc
        except WriteIntegrityError:
            raise

        if not isinstance(envelope, dict) or set(envelope) != {"journal", "journal_sha256"}:
            raise WriteIntegrityError("transaction journal envelope is malformed")
        payload = envelope["journal"]
        expected_digest = envelope["journal_sha256"]
        if not isinstance(payload, dict) or not isinstance(expected_digest, str):
            raise WriteIntegrityError("transaction journal envelope is malformed")
        actual_digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
        if actual_digest != expected_digest:
            raise WriteIntegrityError("transaction journal failed integrity verification")
        record = _payload_record(payload)
        if record.transaction_id != transaction_id:
            raise WriteIntegrityError("transaction journal ID does not match its storage key")
        return _clone_record(record)

    def transition(
        self,
        transaction_id: str,
        expected_status: TransactionStatus,
        new_status: TransactionStatus,
        *,
        metadata_updates: dict[str, object] | None = None,
        result: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> TransactionRecord:
        """Atomically transition a journal when the durable expected state still matches."""
        expected = _require_status(expected_status)
        target = _require_status(new_status)
        current = self.read(transaction_id)
        if current.status is not expected:
            raise WriteStaleStateError("transaction state no longer matches the expected state")
        if target not in _ALLOWED_TRANSITIONS[current.status]:
            raise WriteTransactionError(
                f"illegal transaction transition {current.status.value} -> {target.value}"
            )

        metadata = dict(current.metadata)
        if metadata_updates is not None:
            metadata.update(_validate_safe_mapping(metadata_updates, "metadata"))
        safe_result = None if result is None else _validate_safe_mapping(result, "result")
        timestamp = _utc(now or datetime.now(UTC))
        if timestamp < current.updated_at:
            raise WriteIntegrityError("transaction timestamp cannot move backwards")
        updated = TransactionRecord(
            transaction_id=current.transaction_id,
            project=current.project,
            status=target,
            created_at=current.created_at,
            updated_at=timestamp,
            metadata=metadata,
            steps=current.steps,
            result=safe_result,
        )
        self._write(updated)
        return _clone_record(updated)

    def append_step(
        self,
        transaction_id: str,
        expected_status: TransactionStatus,
        step: dict[str, object],
        *,
        now: datetime | None = None,
    ) -> TransactionRecord:
        """Append one safe recovery/reconciliation step under an expected durable state."""
        expected = _require_status(expected_status)
        current = self.read(transaction_id)
        if current.status is not expected:
            raise WriteStaleStateError("transaction state no longer matches the expected state")
        safe_step = _validate_safe_mapping(step, "step")
        timestamp = _utc(now or datetime.now(UTC))
        if timestamp < current.updated_at:
            raise WriteIntegrityError("transaction timestamp cannot move backwards")
        updated = TransactionRecord(
            transaction_id=current.transaction_id,
            project=current.project,
            status=current.status,
            created_at=current.created_at,
            updated_at=timestamp,
            metadata=dict(current.metadata),
            steps=(*current.steps, safe_step),
            result=None if current.result is None else dict(current.result),
        )
        self._write(updated)
        return _clone_record(updated)

    def incomplete(self) -> tuple[TransactionRecord, ...]:
        """Return durable transactions whose evidence must remain protected."""
        records: list[TransactionRecord] = []
        try:
            paths = sorted(self._root.glob("TX-*.json"), key=lambda path: path.name)
        except OSError as exc:
            raise WriteIntegrityError("transaction journal store cannot be enumerated") from exc
        for path in paths:
            transaction_id = path.name.removesuffix(".json")
            record = self.read(transaction_id)
            if record.status in _INCOMPLETE_STATUSES:
                records.append(record)
        records.sort(key=lambda record: (record.created_at, record.transaction_id))
        return tuple(records)

    def _path(self, transaction_id: str) -> Path:
        _validate_transaction_id(transaction_id)
        return self._root / f"{transaction_id}.json"

    def _write(self, record: TransactionRecord) -> None:
        payload = _record_payload(record)
        _validate_safe_value(payload, "journal")
        canonical = _canonical_json(payload)
        envelope = {
            "journal": payload,
            "journal_sha256": hashlib.sha256(canonical).hexdigest(),
        }
        path = self._path(record.transaction_id)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(_canonical_json(envelope))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(self._root)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise WriteIntegrityError("transaction journal could not be persisted") from exc


def _record_payload(record: TransactionRecord) -> dict[str, object]:
    return {
        "transaction_id": record.transaction_id,
        "project": record.project,
        "status": record.status.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "metadata": dict(record.metadata),
        "steps": [dict(step) for step in record.steps],
        "result": None if record.result is None else dict(record.result),
    }


def _payload_record(payload: dict[str, Any]) -> TransactionRecord:
    required = {
        "transaction_id",
        "project",
        "status",
        "created_at",
        "updated_at",
        "metadata",
        "steps",
        "result",
    }
    if set(payload) != required:
        raise WriteIntegrityError("transaction journal fields are incomplete or unsupported")
    _validate_safe_value(payload, "journal")
    try:
        transaction_id = str(payload["transaction_id"])
        _validate_transaction_id(transaction_id)
        project = _validate_project(payload["project"])
        status = TransactionStatus(str(payload["status"]))
        created_at = _utc(datetime.fromisoformat(str(payload["created_at"])))
        updated_at = _utc(datetime.fromisoformat(str(payload["updated_at"])))
    except (TypeError, ValueError) as exc:
        raise WriteIntegrityError("transaction journal values are malformed") from exc
    if updated_at < created_at:
        raise WriteIntegrityError("transaction journal timestamps are inconsistent")

    metadata_raw = payload["metadata"]
    steps_raw = payload["steps"]
    result_raw = payload["result"]
    if not isinstance(metadata_raw, dict) or not isinstance(steps_raw, list):
        raise WriteIntegrityError("transaction journal metadata or steps are malformed")
    if result_raw is not None and not isinstance(result_raw, dict):
        raise WriteIntegrityError("transaction journal result is malformed")
    metadata = _validate_safe_mapping(metadata_raw, "metadata")
    steps = tuple(_validate_safe_mapping(step, "step") for step in steps_raw)
    result = None if result_raw is None else _validate_safe_mapping(result_raw, "result")
    return TransactionRecord(
        transaction_id=transaction_id,
        project=project,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        metadata=metadata,
        steps=steps,
        result=result,
    )


def _validate_safe_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WriteIntegrityError(f"transaction journal {label} must be an object")
    _validate_safe_value(value, label)
    return json.loads(json.dumps(value, ensure_ascii=False))


def _validate_safe_value(value: object, label: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise WriteIntegrityError(f"transaction journal {label} keys must be strings")
            if key.casefold() in _DENIED_CONTENT_KEYS:
                raise WriteIntegrityError(
                    f"transaction journal must not persist content body field {key!r}"
                )
            _validate_safe_value(nested, label)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _validate_safe_value(nested, label)
        return
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise WriteIntegrityError("transaction journal contains a non-finite number")
        return
    raise WriteIntegrityError(f"transaction journal {label} contains a non-JSON value")


def _validate_transaction_id(value: str) -> None:
    if not isinstance(value, str) or len(value) != 35 or not value.startswith("TX-"):
        raise WriteTransactionError("transaction ID is malformed")
    if any(character not in "0123456789abcdef" for character in value[3:]):
        raise WriteTransactionError("transaction ID is malformed")


def _validate_project(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise WriteIntegrityError("transaction project is malformed")
    if any(character in value for character in "/\\\x00\r\n"):
        raise WriteIntegrityError("transaction project is malformed")
    return value


def _require_status(value: TransactionStatus) -> TransactionStatus:
    if not isinstance(value, TransactionStatus):
        raise WriteTransactionError("transaction status is malformed")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WriteIntegrityError("transaction timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WriteIntegrityError("transaction journal contains duplicate JSON members")
        result[key] = value
    return result


def _clone_record(record: TransactionRecord) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=record.transaction_id,
        project=record.project,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        metadata=dict(record.metadata),
        steps=tuple(dict(step) for step in record.steps),
        result=None if record.result is None else dict(record.result),
    )


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
        raise WriteIntegrityError("transaction journal directory could not be flushed") from exc
