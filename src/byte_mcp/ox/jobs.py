"""In-process ownership for the single OX provider lane."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from byte_mcp.errors import OXUnavailableError

_OPERATION = re.compile(r"[a-z][a-z0-9-]{0,63}")
_SUBJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REVIEW_ID = re.compile(r"OX-\d{6}")
_ATTEMPT_ID = re.compile(r"OX-\d{6}-A\d{3}")
_REVALIDATION_ID = re.compile(r"OX-\d{6}-RV\d{3}")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _require_match(value: object, pattern: re.Pattern[str], message: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value


@dataclass(frozen=True, slots=True)
class OXOperationKey:
    operation: str
    subject_id: str
    input_sha256: str

    def __post_init__(self) -> None:
        _require_match(self.operation, _OPERATION, "operation is invalid")
        _require_match(self.subject_id, _SUBJECT_ID, "subject identity is invalid")
        _require_match(self.input_sha256, _DIGEST, "input digest is invalid")


@dataclass(frozen=True, slots=True)
class OXLaunchDescriptor:
    operation_key: OXOperationKey
    review_id: str
    attempt_id: str
    manifest_sha256: str
    phase: str
    revalidation_id: str | None
    messages: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operation_key, OXOperationKey):
            raise ValueError("operation key is invalid")
        _require_match(self.review_id, _REVIEW_ID, "review identity is invalid")
        _require_match(self.attempt_id, _ATTEMPT_ID, "attempt identity is invalid")
        if not self.attempt_id.startswith(f"{self.review_id}-A"):
            raise ValueError("attempt identity is invalid")
        _require_match(self.manifest_sha256, _DIGEST, "manifest digest is invalid")
        _require_match(self.phase, _OPERATION, "phase is invalid")
        if self.revalidation_id is not None:
            _require_match(
                self.revalidation_id,
                _REVALIDATION_ID,
                "revalidation identity is invalid",
            )
            if not self.revalidation_id.startswith(f"{self.review_id}-RV"):
                raise ValueError("revalidation identity is invalid")
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, Mapping) for message in self.messages
        ):
            raise ValueError("launch messages are invalid")
        object.__setattr__(
            self,
            "messages",
            tuple(_freeze(message) for message in self.messages),
        )


@dataclass(frozen=True, slots=True)
class OXActiveLaunch:
    descriptor: OXLaunchDescriptor
    receipt: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, OXLaunchDescriptor):
            raise ValueError("launch descriptor is invalid")
        if not isinstance(self.receipt, Mapping):
            raise ValueError("launch receipt is invalid")
        object.__setattr__(self, "receipt", _freeze(self.receipt))


@dataclass(frozen=True, slots=True)
class OXLaneLease:
    operation_key: OXOperationKey
    _token: int = field(repr=False)


class OXProviderJobManager:
    """Own one non-queued provider lane for one Byte-MCP runtime session."""

    def __init__(self) -> None:
        self._runtime_session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._lease: OXLaneLease | None = None
        self._lease_counter = 0
        self._active: OXActiveLaunch | None = None
        self._submitted_attempt_ids: set[str] = set()
        self._faulted = False

    @property
    def runtime_session_id(self) -> str:
        return self._runtime_session_id

    def reserve(self, operation_key: OXOperationKey) -> OXLaneLease | OXActiveLaunch:
        if not isinstance(operation_key, OXOperationKey):
            raise ValueError("operation key is invalid")
        with self._lock:
            self._require_open()
            if self._active is not None:
                if self._active.descriptor.operation_key == operation_key:
                    return self._copy_active(self._active)
                raise OXUnavailableError("OX provider lane is busy")
            if self._lease is not None:
                raise OXUnavailableError("OX provider lane is busy")
            self._lease_counter += 1
            lease = OXLaneLease(
                operation_key=operation_key,
                _token=self._lease_counter,
            )
            self._lease = lease
            return lease

    def submit(
        self,
        lease: OXLaneLease,
        descriptor: OXLaunchDescriptor,
        receipt: Mapping[str, object],
        worker: Callable[[OXLaunchDescriptor], None],
        on_submission_failure: Callable[[OXLaunchDescriptor], None],
        on_worker_crash: Callable[[OXLaunchDescriptor], None],
    ) -> None:
        if (
            not callable(worker)
            or not callable(on_submission_failure)
            or not callable(on_worker_crash)
        ):
            raise ValueError("provider job callback is invalid")
        if not isinstance(descriptor, OXLaunchDescriptor):
            raise ValueError("launch descriptor is invalid")
        if not isinstance(receipt, Mapping):
            raise ValueError("launch receipt is invalid")

        with self._lock:
            self._require_open()
            self._require_matching_lease(lease)
            if descriptor.operation_key != lease.operation_key:
                raise OXUnavailableError("OX provider lease does not match launch")
            if descriptor.attempt_id in self._submitted_attempt_ids:
                raise OXUnavailableError("OX provider attempt was already submitted")
            active = OXActiveLaunch(descriptor=descriptor, receipt=receipt)
            self._submitted_attempt_ids.add(descriptor.attempt_id)
            self._active = active
            self._lease = None

        thread = threading.Thread(
            target=self._run_worker,
            args=(active.descriptor, worker, on_worker_crash),
            daemon=True,
            name=f"byte-mcp-ox-{descriptor.attempt_id}",
        )
        try:
            thread.start()
        except Exception:
            try:
                on_submission_failure(active.descriptor)
            except Exception:
                self._fault_active(active)
                raise
            self._release_active(active)
            raise OXUnavailableError("unable to start OX provider job") from None

    def abandon(self, lease: OXLaneLease) -> None:
        with self._lock:
            self._require_open()
            self._require_matching_lease(lease)
            self._lease = None

    def fault_closed(self, lease: OXLaneLease) -> None:
        with self._lock:
            self._require_matching_lease(lease)
            self._lease = None
            self._faulted = True

    def snapshot(self) -> OXActiveLaunch | None:
        with self._lock:
            if self._active is None:
                return None
            return self._copy_active(self._active)

    def _run_worker(
        self,
        descriptor: OXLaunchDescriptor,
        worker: Callable[[OXLaunchDescriptor], None],
        on_worker_crash: Callable[[OXLaunchDescriptor], None],
    ) -> None:
        active = self._active_for_attempt(descriptor.attempt_id)
        if active is None:
            return
        try:
            worker(descriptor)
        except Exception:
            try:
                on_worker_crash(descriptor)
            except Exception:
                self._fault_active(active)
                return
        self._release_active(active)

    def _active_for_attempt(self, attempt_id: str) -> OXActiveLaunch | None:
        with self._lock:
            active = self._active
            if active is None or active.descriptor.attempt_id != attempt_id:
                return None
            return active

    def _release_active(self, active: OXActiveLaunch) -> None:
        with self._lock:
            if self._active is active:
                self._active = None

    def _fault_active(self, active: OXActiveLaunch) -> None:
        with self._lock:
            if self._active is active:
                self._active = None
            self._faulted = True

    def _require_matching_lease(self, lease: OXLaneLease) -> None:
        if not isinstance(lease, OXLaneLease) or self._lease != lease:
            raise OXUnavailableError("OX provider lease is not active")

    def _require_open(self) -> None:
        if self._faulted:
            raise OXUnavailableError("OX provider lane is unavailable")

    @staticmethod
    def _copy_active(active: OXActiveLaunch) -> OXActiveLaunch:
        return OXActiveLaunch(descriptor=active.descriptor, receipt=active.receipt)
