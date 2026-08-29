"""Durable, local-only append-only evidence for OX review attempts."""

import json
import os
import re
import shutil
import threading
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox.models import AttemptOutcome, ReviewState

_REVIEW_ID = re.compile(r"OX-(\d{6,})")
_ATTEMPT_ID = re.compile(r"(OX-\d{6,})-A(\d{3,})")
_REVALIDATION_ID = re.compile(r"(OX-\d{6,})-RV(\d{3,})")
_RESERVATION_ID = re.compile(r"\.OX-(\d{6,})\.reserve")
_RETRYABLE_OUTCOMES = frozenset(
    {
        AttemptOutcome.NOT_SENT.value,
        AttemptOutcome.REJECTED.value,
        AttemptOutcome.OUTCOME_UNKNOWN.value,
    }
)


class EvidenceStore:
    """Own immutable OX records and canonical append-only review history.

    The store is intentionally single-process. Locks make concurrent calls within
    one Byte-MCP process deterministic; multi-process shared roots are unsupported.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._reviews = self._root / "reviews"
        self._allocation_lock = threading.Lock()
        self._review_locks: dict[str, threading.Lock] = {}
        self._review_locks_lock = threading.Lock()

    def persist_prepared_review(
        self,
        *,
        identity: Mapping[str, object],
        manifest: Mapping[str, object],
        bundle: Mapping[str, object],
    ) -> str:
        requested_id = identity.get("review_id")
        if requested_id is not None and not isinstance(requested_id, str):
            raise OXEvidenceError("review identity is invalid")
        allocated = requested_id is None
        review_id = requested_id or self._allocate_review_id()
        if _REVIEW_ID.fullmatch(review_id) is None:
            raise OXEvidenceError("review identity is invalid")
        manifest_sha256 = manifest.get("manifest_sha256")
        if not _is_digest(manifest_sha256):
            raise OXEvidenceError("manifest digest is invalid")

        with self._lock_for(review_id):
            review_dir = self._review_dir(review_id)
            reservation = self._reservation_path(review_id)
            staging = self._staging_path(review_id)
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                if review_dir.exists():
                    raise OXEvidenceError("immutable review evidence already exists")
                if allocated and not reservation.is_file():
                    raise OXEvidenceError("review identity reservation is missing")
                if staging.exists():
                    raise OXEvidenceError("review preparation staging already exists")
                staging.mkdir(parents=True)
                (staging / "bundles").mkdir()
                payload = {**identity, "review_id": review_id, "state": ReviewState.PREPARED.value}
                self._write_immutable_json(staging / "review.json", payload)
                self._write_immutable_json(staging / "manifest.json", manifest)
                self._write_immutable_json(staging / "bundles" / "prepared.json", bundle)
                self._append_jsonl(
                    staging / "events.jsonl",
                    {
                        "event_type": "PREPARED",
                        "manifest_sha256": manifest_sha256,
                        "review_id": review_id,
                    },
                )
                with self._allocation_lock:
                    if review_dir.exists():
                        raise OXEvidenceError("immutable review evidence already exists")
                    os.replace(staging, review_dir)
                    reservation.unlink(missing_ok=True)
            except OXEvidenceError:
                self._remove_staging(staging)
                if allocated:
                    self._remove_reservation(reservation)
                raise
            except (OSError, TypeError, ValueError):
                self._remove_staging(staging)
                if allocated:
                    self._remove_reservation(reservation)
                raise OXEvidenceError("unable to persist prepared review evidence") from None
        return review_id

    def allocate_revalidation_id(self, review_id: str) -> str:
        self._require_review_id(review_id)
        with self._lock_for(review_id):
            try:
                review = self._reconstruct(review_id)
                self._reject_recovered_review(review)
                with self._allocation_lock:
                    revalidations = self._review_dir(review_id) / "revalidations"
                    revalidations.mkdir(exist_ok=True)
                    maximum = max(
                        (
                            int(match.group(2))
                            for path in revalidations.iterdir()
                            if (match := _REVALIDATION_ID.fullmatch(path.name))
                            and match.group(1) == review_id
                        ),
                        default=0,
                    )
                    result = f"{review_id}-RV{maximum + 1:03d}"
                    (revalidations / result).mkdir()
                    return result
            except OXEvidenceError:
                raise
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to allocate revalidation identity") from None

    def claim_initial_transmission(self, review_id: str, manifest_sha256: str) -> dict[str, str]:
        self._require_digest(manifest_sha256)
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            if review["state"] != ReviewState.PREPARED.value:
                raise OXEvidenceError("review is not prepared for transmission")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(review_id, manifest_sha256)

    def claim_retry_transmission(
        self, review_id: str, manifest_sha256: str, *, renewed_approval: bool
    ) -> dict[str, str]:
        self._require_digest(manifest_sha256)
        if not renewed_approval:
            raise OXEvidenceError("retry requires renewed approval")
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            attempts = review["attempts"]
            if not attempts or review["state"] not in {
                ReviewState.FAILED.value,
                ReviewState.OUTCOME_UNKNOWN.value,
            }:
                raise OXEvidenceError("review has no eligible attempt for retry")
            previous = attempts[-1]
            if previous.get("outcome") not in _RETRYABLE_OUTCOMES:
                raise OXEvidenceError("review has no eligible attempt for retry")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(review_id, manifest_sha256)

    def record_attempt_outcome(
        self, review_id: str, attempt_id: str, outcome: AttemptOutcome | str
    ) -> None:
        outcome_value = _enum_value(outcome)
        if outcome_value not in {item.value for item in AttemptOutcome}:
            raise OXEvidenceError("attempt outcome is invalid")
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            if not any(attempt["attempt_id"] == attempt_id for attempt in review["attempts"]):
                raise OXEvidenceError("attempt identity is unknown")
            if review["state"] != ReviewState.TRANSMITTING.value:
                raise OXEvidenceError("review is not transmitting")
            self._append_event(
                review_id,
                {
                    "attempt_id": attempt_id,
                    "event_type": "ATTEMPT_OUTCOME",
                    "outcome": outcome_value,
                },
            )

    def append_thread_message(
        self, review_id: str, thread_name: str, message: Mapping[str, object]
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", thread_name):
            raise OXEvidenceError("thread identity is invalid")
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append thread message") from None
            try:
                self._append_jsonl(
                    self._review_dir(review_id) / "threads" / f"{thread_name}.jsonl", message
                )
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append thread message") from None

    def persist_provider_response(
        self, review_id: str, attempt_id: str, response: Mapping[str, object]
    ) -> None:
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist provider response") from None
            try:
                self._write_immutable_json(
                    self._review_dir(review_id) / "responses" / f"{attempt_id}.json", response
                )
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist provider response") from None

    def persist_findings(self, review_id: str, findings: Mapping[str, object]) -> None:
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist findings") from None
            try:
                self._write_immutable_json(
                    self._review_dir(review_id) / "findings" / "findings.json", findings
                )
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist findings") from None

    def append_adjudication(self, review_id: str, event: Mapping[str, object]) -> None:
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append adjudication") from None
            try:
                self._append_jsonl(self._review_dir(review_id) / "adjudication.jsonl", event)
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append adjudication") from None

    def get_review(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            return self._reconstruct(review_id)

    def _allocate_review_id(self) -> str:
        with self._allocation_lock:
            try:
                self._reviews.mkdir(parents=True, exist_ok=True)
                maximum = max(
                    (
                        int(match.group(1))
                        for path in self._reviews.iterdir()
                        if (match := _REVIEW_ID.fullmatch(path.name))
                    ),
                    default=0,
                )
                maximum = max(
                    [
                        maximum,
                        *(
                            int(match.group(1))
                            for path in self._reviews.iterdir()
                            if (match := _RESERVATION_ID.fullmatch(path.name))
                        ),
                    ]
                )
                candidate = maximum + 1
                while True:
                    review_id = f"OX-{candidate:06d}"
                    reservation = self._reservation_path(review_id)
                    try:
                        with reservation.open("xb") as handle:
                            handle.write(review_id.encode("ascii"))
                            handle.flush()
                            os.fsync(handle.fileno())
                        return review_id
                    except FileExistsError:
                        candidate += 1
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("unable to allocate review identity") from None

    def _append_transmission_intent(self, review_id: str, manifest_sha256: str) -> dict[str, str]:
        attempt_id = self._allocate_attempt_id(review_id)
        attempt = {"attempt_id": attempt_id, "manifest_sha256": manifest_sha256}
        self._append_event(review_id, {**attempt, "event_type": "TRANSMISSION_INTENT"})
        return attempt

    def _allocate_attempt_id(self, review_id: str) -> str:
        with self._allocation_lock:
            review = self._reconstruct(review_id)
            maximum = max(
                (
                    int(match.group(2))
                    for attempt in review["attempts"]
                    if (match := _ATTEMPT_ID.fullmatch(str(attempt["attempt_id"])))
                    and match.group(1) == review_id
                ),
                default=0,
            )
            return f"{review_id}-A{maximum + 1:03d}"

    def _append_event(self, review_id: str, event: Mapping[str, object]) -> None:
        try:
            self._append_jsonl(self._review_dir(review_id) / "events.jsonl", event)
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to append review event") from None

    def _reconstruct(self, review_id: str) -> dict[str, object]:
        try:
            review_dir = self._require_review_dir(review_id)
            identity = self._read_json(review_dir / "review.json")
            manifest = self._read_json(review_dir / "manifest.json")
            events, warnings = self._read_jsonl(review_dir / "events.jsonl")
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to read review evidence") from None
        if (
            not isinstance(identity, dict)
            or not isinstance(manifest, dict)
            or identity.get("review_id") != review_id
            or not _is_digest(manifest.get("manifest_sha256"))
        ):
            raise OXEvidenceError("review evidence is malformed")
        manifest_digest = manifest["manifest_sha256"]
        if (
            not events
            or not isinstance(events[0], dict)
            or events[0].get("event_type") != "PREPARED"
        ):
            raise OXEvidenceError("review events are malformed")
        state = ReviewState.PREPARED.value
        attempts: list[dict[str, str]] = []
        prepared_seen = False
        for event in events:
            if not isinstance(event, dict):
                raise OXEvidenceError("review events are malformed")
            event_type = event.get("event_type")
            if event_type == "TRANSMISSION_INTENT":
                attempt_id = event.get("attempt_id")
                digest = event.get("manifest_sha256")
                if (
                    not isinstance(attempt_id, str)
                    or not _attempt_belongs_to_review(review_id, attempt_id)
                    or digest != manifest_digest
                ):
                    raise OXEvidenceError("review events are malformed")
                attempts.append({"attempt_id": attempt_id, "manifest_sha256": digest})
                state = ReviewState.TRANSMITTING.value
            elif event_type == "ATTEMPT_OUTCOME":
                attempt_id = event.get("attempt_id")
                outcome = event.get("outcome")
                if not isinstance(attempt_id, str) or not _attempt_belongs_to_review(
                    review_id, attempt_id
                ) or outcome not in {
                    item.value for item in AttemptOutcome
                }:
                    raise OXEvidenceError("review events are malformed")
                matching = next(
                    (attempt for attempt in attempts if attempt["attempt_id"] == attempt_id), None
                )
                if matching is None or "outcome" in matching:
                    raise OXEvidenceError("review events are malformed")
                matching["outcome"] = outcome
                state = {
                    AttemptOutcome.COMPLETED.value: ReviewState.REVIEWED.value,
                    AttemptOutcome.OUTCOME_UNKNOWN.value: ReviewState.OUTCOME_UNKNOWN.value,
                }.get(outcome, ReviewState.FAILED.value)
            elif event_type == "PREPARED":
                if prepared_seen:
                    raise OXEvidenceError("review events are malformed")
                if (
                    event.get("review_id") != review_id
                    or event.get("manifest_sha256") != manifest_digest
                ):
                    raise OXEvidenceError("review events are malformed")
                prepared_seen = True
            else:
                raise OXEvidenceError("review events are malformed")
        if not prepared_seen:
            raise OXEvidenceError("review events are malformed")
        return {
            "attempts": attempts,
            "identity": identity,
            "manifest": manifest,
            "recovery_warnings": warnings,
            "review_id": review_id,
            "state": state,
        }

    def _verify_manifest_digest(self, review_id: str, manifest_sha256: str) -> None:
        try:
            manifest = self._read_json(self._review_dir(review_id) / "manifest.json")
            if not isinstance(manifest, dict) or manifest.get("manifest_sha256") != manifest_sha256:
                raise OXEvidenceError("manifest digest does not match prepared review")
        except OXEvidenceError:
            raise
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to verify manifest digest") from None

    def _ensure_writable_review(self, review_id: str) -> None:
        self._reject_recovered_review(self._reconstruct(review_id))

    @staticmethod
    def _reject_recovered_review(review: Mapping[str, object]) -> None:
        if review["recovery_warnings"]:
            raise OXEvidenceError("review evidence requires recovery before mutation")

    def _lock_for(self, review_id: str) -> threading.Lock:
        self._require_review_id(review_id)
        with self._review_locks_lock:
            return self._review_locks.setdefault(review_id, threading.Lock())

    def _review_dir(self, review_id: str) -> Path:
        return self._reviews / review_id

    def _reservation_path(self, review_id: str) -> Path:
        return self._reviews / f".{review_id}.reserve"

    def _staging_path(self, review_id: str) -> Path:
        return self._root / ".ox-staging" / review_id

    @staticmethod
    def _remove_staging(staging: Path) -> None:
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _remove_reservation(reservation: Path) -> None:
        with suppress(OSError):
            reservation.unlink(missing_ok=True)

    def _require_review_dir(self, review_id: str) -> Path:
        self._require_review_id(review_id)
        review_dir = self._review_dir(review_id)
        if not review_dir.is_dir():
            raise OXEvidenceError("review evidence was not found")
        return review_dir

    @staticmethod
    def _require_review_id(review_id: str) -> None:
        if _REVIEW_ID.fullmatch(review_id) is None:
            raise OXEvidenceError("review identity is invalid")

    @staticmethod
    def _require_attempt_id(review_id: str, attempt_id: str) -> None:
        match = _ATTEMPT_ID.fullmatch(attempt_id)
        if match is None or match.group(1) != review_id:
            raise OXEvidenceError("attempt identity is invalid")

    @staticmethod
    def _require_digest(manifest_sha256: str) -> None:
        if not _is_digest(manifest_sha256):
            raise OXEvidenceError("manifest digest is invalid")

    @staticmethod
    def _write_immutable_json(path: Path, value: Mapping[str, object]) -> None:
        if path.exists():
            raise OXEvidenceError("immutable evidence already exists")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = _canonical_json(value)
            with NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                temporary_path.unlink(missing_ok=True)
                raise OXEvidenceError("immutable evidence already exists")
            os.replace(temporary_path, path)
        except OXEvidenceError:
            raise
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to persist immutable evidence") from None

    @staticmethod
    def _append_jsonl(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json(value) + b"\n"
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_json(path: Path) -> object:
        return json.loads(path.read_bytes().decode("utf-8"))

    @staticmethod
    def _read_jsonl(path: Path) -> tuple[list[object], list[str]]:
        if not path.exists():
            return [], []
        raw = path.read_bytes()
        lines = raw.splitlines()
        records: list[object] = []
        for index, line in enumerate(lines):
            if not line:
                raise OXEvidenceError("review events are malformed")
            try:
                records.append(json.loads(line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                is_trailing = index == len(lines) - 1 and not raw.endswith(b"\n")
                if is_trailing:
                    return records, ["ignored malformed trailing events record"]
                raise OXEvidenceError("review events are malformed") from None
        return records, []


def _canonical_json(value: Mapping[str, object]) -> bytes:
    serialized = json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return serialized.encode("utf-8")


def _enum_value(value: AttemptOutcome | str) -> str:
    return value.value if isinstance(value, AttemptOutcome) else value


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _attempt_belongs_to_review(review_id: str, attempt_id: str) -> bool:
    match = _ATTEMPT_ID.fullmatch(attempt_id)
    return match is not None and match.group(1) == review_id
