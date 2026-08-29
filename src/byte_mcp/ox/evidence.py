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

_REVIEW_ID = re.compile(r"OX-(\d{6})")
_ATTEMPT_ID = re.compile(r"(OX-\d{6})-A(\d{3})")
_REVALIDATION_ID = re.compile(r"(OX-\d{6})-RV(\d{3})")
_RESERVATION_ID = re.compile(r"\.OX-(\d{6})\.reserve")
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
                    if maximum >= 999:
                        raise OXEvidenceError("revalidation identity space is exhausted")
                    result = f"{review_id}-RV{maximum + 1:03d}"
                    (revalidations / result).mkdir()
                    return result
            except OXEvidenceError:
                raise
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to allocate revalidation identity") from None

    def persist_prepared_revalidation(
        self,
        review_id: str,
        revalidation_id: str,
        *,
        identity: Mapping[str, object],
        manifest: Mapping[str, object],
        bundle: Mapping[str, object],
    ) -> None:
        self._require_revalidation_id(review_id, revalidation_id)
        manifest_sha256 = manifest.get("manifest_sha256")
        if not _is_digest(manifest_sha256):
            raise OXEvidenceError("revalidation manifest digest is invalid")
        with self._lock_for(review_id):
            self._reject_recovered_review(self._reconstruct(review_id))
            directory = self._revalidation_dir(review_id, revalidation_id)
            try:
                if not directory.is_dir() or any(directory.iterdir()):
                    raise OXEvidenceError("revalidation evidence is not empty")
                payload = {
                    **identity,
                    "review_id": review_id,
                    "revalidation_id": revalidation_id,
                    "state": ReviewState.REVALIDATION_PREPARED.value,
                }
                self._write_immutable_json(directory / "revalidation.json", payload)
                self._write_immutable_json(directory / "manifest.json", manifest)
                self._write_immutable_json(directory / "bundles" / "prepared.json", bundle)
                self._append_jsonl(
                    directory / "events.jsonl",
                    {
                        "event_type": "REVALIDATION_PREPARED",
                        "manifest_sha256": manifest_sha256,
                        "revalidation_id": revalidation_id,
                    },
                )
            except OXEvidenceError:
                raise
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("unable to persist prepared revalidation") from None

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

    def claim_continuation_transmission(
        self, review_id: str, manifest_sha256: str
    ) -> dict[str, str]:
        self._require_digest(manifest_sha256)
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            if review["state"] != ReviewState.REVIEWED.value:
                raise OXEvidenceError("review is not available for continuation")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(review_id, manifest_sha256)

    def claim_continuation_retry(
        self,
        review_id: str,
        manifest_sha256: str,
        previous_attempt_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, str]:
        self._require_digest(manifest_sha256)
        self._require_attempt_id(review_id, previous_attempt_id)
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
                raise OXEvidenceError("continuation has no eligible attempt for retry")
            previous = attempts[-1]
            if (
                previous.get("attempt_id") != previous_attempt_id
                or previous.get("outcome") not in _RETRYABLE_OUTCOMES
            ):
                raise OXEvidenceError("continuation retry does not match latest attempt")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(review_id, manifest_sha256)

    def record_attempt_outcome(
        self, review_id: str, attempt_id: str, outcome: AttemptOutcome | str
    ) -> None:
        outcome_value = _enum_value(outcome)
        if outcome_value not in {item.value for item in AttemptOutcome}:
            raise OXEvidenceError("attempt outcome is invalid")
        with self._lock_for(review_id):
            try:
                review = self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to record attempt outcome") from None
            self._require_current_transmitting_attempt(review, attempt_id)
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
        self._require_thread_name(thread_name)
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
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
                review = self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist provider response") from None
            self._require_current_transmitting_attempt(review, attempt_id)
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
                self._write_immutable_json(
                    self._review_dir(review_id) / "findings" / "findings.json", findings
                )
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist findings") from None

    def append_adjudication(self, review_id: str, event: Mapping[str, object]) -> None:
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
                self._append_jsonl(self._review_dir(review_id) / "adjudication.jsonl", event)
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append adjudication") from None

    def read_thread(self, review_id: str, thread_name: str = "initial") -> list[dict[str, object]]:
        self._require_thread_name(thread_name)
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            records, warnings = self._read_jsonl(
                self._review_dir(review_id) / "threads" / f"{thread_name}.jsonl"
            )
            if warnings or not all(isinstance(record, dict) for record in records):
                raise OXEvidenceError("thread evidence requires recovery")
            return [dict(record) for record in records]

    def read_findings(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            try:
                value = self._read_json(self._review_dir(review_id) / "findings" / "findings.json")
            except FileNotFoundError:
                return {"protocol_version": "ox-findings-v1", "findings": []}
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("unable to read findings") from None
            if not isinstance(value, dict):
                raise OXEvidenceError("findings evidence is malformed")
            return value

    def read_adjudications(self, review_id: str) -> list[dict[str, object]]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            records, warnings = self._read_jsonl(self._review_dir(review_id) / "adjudication.jsonl")
            if warnings or not all(isinstance(record, dict) for record in records):
                raise OXEvidenceError("adjudication evidence requires recovery")
            return [dict(record) for record in records]

    def read_manifest(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            value = self._read_json(self._review_dir(review_id) / "manifest.json")
            if not isinstance(value, dict):
                raise OXEvidenceError("manifest evidence is malformed")
            return value

    def read_bundle(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            value = self._read_json(self._review_dir(review_id) / "bundles" / "prepared.json")
            if not isinstance(value, dict):
                raise OXEvidenceError("prepared bundle evidence is malformed")
            return value

    def read_attempt_identity(self, review_id: str, attempt_id: str) -> dict[str, object]:
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            try:
                value = self._read_json(
                    self._review_dir(review_id) / "attempts" / f"{attempt_id}.json"
                )
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("attempt evidence was not found") from None
            if not isinstance(value, dict):
                raise OXEvidenceError("attempt evidence is malformed")
            return value

    def get_review(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            return self._reconstruct(review_id)

    def get_revalidation(self, revalidation_id: str) -> dict[str, object]:
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            return self._reconstruct_revalidation(review_id, revalidation_id)

    def list_revalidations(self, review_id: str) -> list[dict[str, object]]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            root = self._review_dir(review_id) / "revalidations"
            if not root.exists():
                return []
            results: list[dict[str, object]] = []
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if _REVALIDATION_ID.fullmatch(path.name) is None:
                    continue
                if not (path / "revalidation.json").is_file():
                    continue
                results.append(self._reconstruct_revalidation(review_id, path.name))
            return results

    def claim_revalidation_transmission(
        self, revalidation_id: str, *, phase: str
    ) -> dict[str, str]:
        if phase not in {"blind", "targeted"}:
            raise OXEvidenceError("revalidation phase is invalid")
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(review_id, revalidation_id)
            self._reject_recovered_revalidation(revalidation)
            required_state = (
                ReviewState.REVALIDATION_PREPARED.value
                if phase == "blind"
                else ReviewState.BLIND_REVALIDATED.value
            )
            if revalidation["state"] != required_state:
                raise OXEvidenceError("revalidation phase is not available for transmission")
            digest = revalidation["manifest"]["manifest_sha256"]
            return self._append_revalidation_transmission_intent(
                review_id, revalidation_id, digest, phase
            )

    def claim_revalidation_retry(
        self,
        revalidation_id: str,
        previous_attempt_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, str]:
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, previous_attempt_id)
        if not renewed_approval:
            raise OXEvidenceError("retry requires renewed approval")
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(review_id, revalidation_id)
            self._reject_recovered_revalidation(revalidation)
            attempts = revalidation["attempts"]
            if not attempts or revalidation["state"] not in {
                ReviewState.FAILED.value,
                ReviewState.OUTCOME_UNKNOWN.value,
            }:
                raise OXEvidenceError("revalidation has no eligible attempt for retry")
            previous = attempts[-1]
            if (
                previous.get("attempt_id") != previous_attempt_id
                or previous.get("outcome") not in _RETRYABLE_OUTCOMES
            ):
                raise OXEvidenceError("revalidation retry does not match latest attempt")
            digest = revalidation["manifest"]["manifest_sha256"]
            return self._append_revalidation_transmission_intent(
                review_id,
                revalidation_id,
                digest,
                str(previous["phase"]),
            )

    def record_revalidation_attempt_outcome(
        self,
        revalidation_id: str,
        attempt_id: str,
        outcome: AttemptOutcome | str,
    ) -> None:
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, attempt_id)
        outcome_value = _enum_value(outcome)
        if outcome_value not in {item.value for item in AttemptOutcome}:
            raise OXEvidenceError("attempt outcome is invalid")
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(review_id, revalidation_id)
            self._reject_recovered_revalidation(revalidation)
            attempts = revalidation["attempts"]
            if not attempts or attempts[-1].get("attempt_id") != attempt_id:
                raise OXEvidenceError("revalidation attempt is not current")
            if revalidation["state"] != ReviewState.REVALIDATION_TRANSMITTING.value:
                raise OXEvidenceError("revalidation attempt is not transmitting")
            self._append_jsonl(
                self._revalidation_dir(review_id, revalidation_id) / "events.jsonl",
                {
                    "attempt_id": attempt_id,
                    "event_type": "REVALIDATION_ATTEMPT_OUTCOME",
                    "outcome": outcome_value,
                    "phase": attempts[-1]["phase"],
                },
            )

    def persist_revalidation_attempt_identity(
        self,
        revalidation_id: str,
        attempt_id: str,
        payload: Mapping[str, object],
    ) -> None:
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(review_id, revalidation_id)
            attempts = revalidation["attempts"]
            if (
                not attempts
                or attempts[-1].get("attempt_id") != attempt_id
                or revalidation["state"] != ReviewState.REVALIDATION_TRANSMITTING.value
            ):
                raise OXEvidenceError("revalidation attempt is not current")
            self._write_immutable_json(
                self._revalidation_dir(review_id, revalidation_id)
                / "attempts"
                / f"{attempt_id}.json",
                payload,
            )

    def append_revalidation_thread_message(
        self,
        revalidation_id: str,
        thread_name: str,
        message: Mapping[str, object],
    ) -> None:
        self._require_thread_name(thread_name)
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            self._reconstruct_revalidation(review_id, revalidation_id)
            self._append_jsonl(
                self._revalidation_dir(review_id, revalidation_id)
                / "threads"
                / f"{thread_name}.jsonl",
                message,
            )

    def read_revalidation_thread(
        self, revalidation_id: str, thread_name: str
    ) -> list[dict[str, object]]:
        self._require_thread_name(thread_name)
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            self._reconstruct_revalidation(review_id, revalidation_id)
            records, warnings = self._read_jsonl(
                self._revalidation_dir(review_id, revalidation_id)
                / "threads"
                / f"{thread_name}.jsonl"
            )
            if warnings or not all(isinstance(record, dict) for record in records):
                raise OXEvidenceError("revalidation thread requires recovery")
            return [dict(record) for record in records]

    def persist_revalidation_provider_response(
        self,
        revalidation_id: str,
        attempt_id: str,
        response: Mapping[str, object],
    ) -> None:
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(review_id, revalidation_id)
            attempts = revalidation["attempts"]
            if (
                not attempts
                or attempts[-1].get("attempt_id") != attempt_id
                or revalidation["state"] != ReviewState.REVALIDATION_TRANSMITTING.value
            ):
                raise OXEvidenceError("revalidation attempt is not current")
            self._write_immutable_json(
                self._revalidation_dir(review_id, revalidation_id)
                / "responses"
                / f"{attempt_id}.json",
                response,
            )

    def persist_revalidation_findings(
        self,
        revalidation_id: str,
        phase: str,
        findings: Mapping[str, object],
    ) -> None:
        if phase not in {"blind", "targeted"}:
            raise OXEvidenceError("revalidation phase is invalid")
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            self._reconstruct_revalidation(review_id, revalidation_id)
            self._write_immutable_json(
                self._revalidation_dir(review_id, revalidation_id)
                / "findings"
                / f"{phase}.json",
                findings,
            )

    def read_revalidation_bundle(self, revalidation_id: str) -> dict[str, object]:
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            self._reconstruct_revalidation(review_id, revalidation_id)
            value = self._read_json(
                self._revalidation_dir(review_id, revalidation_id) / "bundles" / "prepared.json"
            )
            if not isinstance(value, dict):
                raise OXEvidenceError("revalidation bundle evidence is malformed")
            return value

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
                while candidate <= 999999:
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
                raise OXEvidenceError("review identity space is exhausted")
            except OXEvidenceError:
                raise
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("unable to allocate review identity") from None

    def _append_transmission_intent(self, review_id: str, manifest_sha256: str) -> dict[str, str]:
        attempt_id = self._allocate_attempt_id(review_id)
        attempt = {"attempt_id": attempt_id, "manifest_sha256": manifest_sha256}
        self._append_event(review_id, {**attempt, "event_type": "TRANSMISSION_INTENT"})
        return attempt

    def _append_revalidation_transmission_intent(
        self,
        review_id: str,
        revalidation_id: str,
        manifest_sha256: str,
        phase: str,
    ) -> dict[str, str]:
        attempt_id = self._allocate_attempt_id(review_id)
        attempt = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "phase": phase,
        }
        self._append_jsonl(
            self._revalidation_dir(review_id, revalidation_id) / "events.jsonl",
            {**attempt, "event_type": "REVALIDATION_TRANSMISSION_INTENT"},
        )
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
            revalidations = self._review_dir(review_id) / "revalidations"
            if revalidations.is_dir():
                for path in revalidations.iterdir():
                    events_path = path / "events.jsonl"
                    if not events_path.is_file():
                        continue
                    records, warnings = self._read_jsonl(events_path)
                    if warnings:
                        raise OXEvidenceError("revalidation evidence requires recovery")
                    for event in records:
                        if not isinstance(event, dict):
                            raise OXEvidenceError("revalidation events are malformed")
                        attempt_id = event.get("attempt_id")
                        match = _ATTEMPT_ID.fullmatch(str(attempt_id))
                        if match is not None and match.group(1) == review_id:
                            maximum = max(maximum, int(match.group(2)))
            if maximum >= 999:
                raise OXEvidenceError("attempt identity space is exhausted")
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
                if (
                    not isinstance(attempt_id, str)
                    or not _attempt_belongs_to_review(review_id, attempt_id)
                    or outcome not in {item.value for item in AttemptOutcome}
                ):
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

    def _reconstruct_revalidation(
        self, review_id: str, revalidation_id: str
    ) -> dict[str, object]:
        self._require_revalidation_id(review_id, revalidation_id)
        directory = self._revalidation_dir(review_id, revalidation_id)
        try:
            identity = self._read_json(directory / "revalidation.json")
            manifest = self._read_json(directory / "manifest.json")
            events, warnings = self._read_jsonl(directory / "events.jsonl")
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to read revalidation evidence") from None
        if (
            not isinstance(identity, dict)
            or not isinstance(manifest, dict)
            or identity.get("review_id") != review_id
            or identity.get("revalidation_id") != revalidation_id
            or not _is_digest(manifest.get("manifest_sha256"))
        ):
            raise OXEvidenceError("revalidation evidence is malformed")
        manifest_digest = manifest["manifest_sha256"]
        state = ReviewState.REVALIDATION_PREPARED.value
        attempts: list[dict[str, str]] = []
        prepared_seen = False
        for event in events:
            if not isinstance(event, dict):
                raise OXEvidenceError("revalidation events are malformed")
            event_type = event.get("event_type")
            if event_type == "REVALIDATION_PREPARED":
                if prepared_seen or event.get("revalidation_id") != revalidation_id:
                    raise OXEvidenceError("revalidation events are malformed")
                if event.get("manifest_sha256") != manifest_digest:
                    raise OXEvidenceError("revalidation events are malformed")
                prepared_seen = True
            elif event_type == "REVALIDATION_TRANSMISSION_INTENT":
                attempt_id = event.get("attempt_id")
                phase = event.get("phase")
                if (
                    not isinstance(attempt_id, str)
                    or not _attempt_belongs_to_review(review_id, attempt_id)
                    or event.get("manifest_sha256") != manifest_digest
                    or phase not in {"blind", "targeted"}
                ):
                    raise OXEvidenceError("revalidation events are malformed")
                attempts.append(
                    {
                        "attempt_id": attempt_id,
                        "manifest_sha256": manifest_digest,
                        "phase": phase,
                    }
                )
                state = ReviewState.REVALIDATION_TRANSMITTING.value
            elif event_type == "REVALIDATION_ATTEMPT_OUTCOME":
                attempt_id = event.get("attempt_id")
                outcome = event.get("outcome")
                phase = event.get("phase")
                if (
                    not isinstance(attempt_id, str)
                    or outcome not in {item.value for item in AttemptOutcome}
                    or phase not in {"blind", "targeted"}
                ):
                    raise OXEvidenceError("revalidation events are malformed")
                matching = next(
                    (attempt for attempt in attempts if attempt["attempt_id"] == attempt_id), None
                )
                if matching is None or matching.get("phase") != phase or "outcome" in matching:
                    raise OXEvidenceError("revalidation events are malformed")
                matching["outcome"] = outcome
                if outcome == AttemptOutcome.COMPLETED.value:
                    state = (
                        ReviewState.BLIND_REVALIDATED.value
                        if phase == "blind"
                        else ReviewState.REVALIDATED.value
                    )
                elif outcome == AttemptOutcome.OUTCOME_UNKNOWN.value:
                    state = ReviewState.OUTCOME_UNKNOWN.value
                else:
                    state = ReviewState.FAILED.value
            else:
                raise OXEvidenceError("revalidation events are malformed")
        if not prepared_seen:
            raise OXEvidenceError("revalidation events are malformed")
        return {
            "attempts": attempts,
            "identity": identity,
            "manifest": manifest,
            "recovery_warnings": warnings,
            "review_id": review_id,
            "revalidation_id": revalidation_id,
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

    def _ensure_writable_review(self, review_id: str) -> dict[str, object]:
        review = self._reconstruct(review_id)
        self._reject_recovered_review(review)
        return review

    @staticmethod
    def _require_current_transmitting_attempt(
        review: Mapping[str, object], attempt_id: str
    ) -> None:
        attempts = review["attempts"]
        if not any(attempt["attempt_id"] == attempt_id for attempt in attempts):
            raise OXEvidenceError("attempt identity is unknown")
        if not attempts or attempts[-1]["attempt_id"] != attempt_id:
            raise OXEvidenceError("attempt is not the current transmission")
        if review["state"] != ReviewState.TRANSMITTING.value:
            raise OXEvidenceError("attempt is not currently transmitting")

    @staticmethod
    def _reject_recovered_review(review: Mapping[str, object]) -> None:
        if review["recovery_warnings"]:
            raise OXEvidenceError("review evidence requires recovery before mutation")

    @staticmethod
    def _reject_recovered_revalidation(revalidation: Mapping[str, object]) -> None:
        if revalidation["recovery_warnings"]:
            raise OXEvidenceError("revalidation evidence requires recovery before mutation")

    def _lock_for(self, review_id: str) -> threading.Lock:
        self._require_review_id(review_id)
        with self._review_locks_lock:
            return self._review_locks.setdefault(review_id, threading.Lock())

    def _review_dir(self, review_id: str) -> Path:
        return self._reviews / review_id

    def _revalidation_dir(self, review_id: str, revalidation_id: str) -> Path:
        return self._review_dir(review_id) / "revalidations" / revalidation_id

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
        if not isinstance(review_id, str) or _REVIEW_ID.fullmatch(review_id) is None:
            raise OXEvidenceError("review identity is invalid")

    @staticmethod
    def _require_attempt_id(review_id: str, attempt_id: str) -> None:
        match = _ATTEMPT_ID.fullmatch(attempt_id)
        if match is None or match.group(1) != review_id:
            raise OXEvidenceError("attempt identity is invalid")

    @staticmethod
    def _require_revalidation_id(review_id: str, revalidation_id: str) -> None:
        match = _REVALIDATION_ID.fullmatch(revalidation_id)
        if match is None or match.group(1) != review_id:
            raise OXEvidenceError("revalidation identity is invalid")

    @staticmethod
    def _review_id_from_revalidation(revalidation_id: str) -> str:
        if not isinstance(revalidation_id, str):
            raise OXEvidenceError("revalidation identity is invalid")
        match = _REVALIDATION_ID.fullmatch(revalidation_id)
        if match is None:
            raise OXEvidenceError("revalidation identity is invalid")
        return match.group(1)

    @staticmethod
    def _require_thread_name(thread_name: str) -> None:
        if not isinstance(thread_name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", thread_name):
            raise OXEvidenceError("thread identity is invalid")

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
