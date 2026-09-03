"""Durable, local-only append-only evidence for OX review attempts."""

import json
import os
import re
import shutil
import threading
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from byte_mcp.errors import OXEvidenceError, OXTransportFailureKind
from byte_mcp.ox.models import AttemptOutcome, ReviewState

_REVIEW_ID = re.compile(r"OX-(\d{6})")
_ATTEMPT_ID = re.compile(r"(OX-\d{6})-A(\d{3})")
_REVALIDATION_ID = re.compile(r"(OX-\d{6})-RV(\d{3})")
_RESERVATION_ID = re.compile(r"\.OX-(\d{6})\.reserve")
_RUNTIME_SESSION_ID = re.compile(r"[0-9a-f]{32}")
_REVIEW_PROVIDER_PHASES = frozenset({"initial", "continuation"})
_REVALIDATION_PROVIDER_PHASES = frozenset({"blind", "targeted"})
_TRANSPORT_FAILURE_KINDS = frozenset(item.value for item in OXTransportFailureKind)
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
                payload = {
                    **identity,
                    "review_id": review_id,
                    "state": ReviewState.PREPARED.value,
                }
                self._write_immutable_json(staging / "review.json", payload)
                self._write_immutable_json(staging / "manifest.json", manifest)
                self._write_immutable_json(
                    staging / "bundles" / "prepared.json", bundle
                )
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
                raise OXEvidenceError(
                    "unable to persist prepared review evidence"
                ) from None
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
                        raise OXEvidenceError(
                            "revalidation identity space is exhausted"
                        )
                    result = f"{review_id}-RV{maximum + 1:03d}"
                    (revalidations / result).mkdir()
                    return result
            except OXEvidenceError:
                raise
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError(
                    "unable to allocate revalidation identity"
                ) from None

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
                self._write_immutable_json(
                    directory / "revalidation.json", payload
                )
                self._write_immutable_json(directory / "manifest.json", manifest)
                self._write_immutable_json(
                    directory / "bundles" / "prepared.json", bundle
                )
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
                raise OXEvidenceError(
                    "unable to persist prepared revalidation"
                ) from None

    def recover_stale_transmissions(
        self,
        *,
        stale_after: timedelta,
        runtime_session_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        # Local-only append-only recovery. Never retries a provider request.
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise OXEvidenceError("orphan recovery horizon is invalid")
        if runtime_session_id is not None:
            self._require_runtime_session_id(runtime_session_id)
        recovery_now = now or datetime.now(UTC)
        if (
            not isinstance(recovery_now, datetime)
            or recovery_now.tzinfo is None
            or recovery_now.utcoffset() is None
        ):
            raise OXEvidenceError("orphan recovery time must be timezone-aware")
        cutoff = recovery_now.astimezone(UTC) - stale_after
        recovered: list[str] = []

        if not self._reviews.is_dir():
            return ()
        try:
            review_dirs = sorted(
                path
                for path in self._reviews.iterdir()
                if path.is_dir() and _REVIEW_ID.fullmatch(path.name)
            )
        except OSError:
            raise OXEvidenceError(
                "unable to inspect OX recovery evidence"
            ) from None

        for review_dir in review_dirs:
            review_id = review_dir.name
            with self._lock_for(review_id):
                review = self._reconstruct(review_id)
                self._reject_recovered_review(review)
                attempts = review.get("attempts")
                if (
                    review.get("state") == ReviewState.TRANSMITTING.value
                    and isinstance(attempts, list)
                    and attempts
                ):
                    latest = attempts[-1]
                    attempt_id = latest.get("attempt_id")
                    if (
                        isinstance(attempt_id, str)
                        and "outcome" not in latest
                        and self._attempt_requires_recovery(
                            owner=latest.get("runtime_session_id"),
                            current_runtime_session_id=runtime_session_id,
                            recorded_at=self._review_attempt_recorded_at(
                                review_id, attempt_id
                            ),
                            cutoff=cutoff,
                        )
                    ):
                        self._append_event(
                            review_id,
                            {
                                "attempt_id": attempt_id,
                                "event_type": "ATTEMPT_OUTCOME",
                                "outcome": AttemptOutcome.OUTCOME_UNKNOWN.value,
                            },
                        )
                        recovered.append(attempt_id)

                revalidations = review_dir / "revalidations"
                if not revalidations.is_dir():
                    continue
                try:
                    revalidation_dirs = sorted(
                        path
                        for path in revalidations.iterdir()
                        if path.is_dir()
                        and _REVALIDATION_ID.fullmatch(path.name)
                        and path.name.startswith(f"{review_id}-RV")
                    )
                except OSError:
                    raise OXEvidenceError(
                        "unable to inspect OX revalidation recovery evidence"
                    ) from None

                for revalidation_dir in revalidation_dirs:
                    revalidation_id = revalidation_dir.name
                    revalidation = self._reconstruct_revalidation(
                        review_id, revalidation_id
                    )
                    self._reject_recovered_revalidation(revalidation)
                    attempts = revalidation.get("attempts")
                    if (
                        revalidation.get("state")
                        != ReviewState.REVALIDATION_TRANSMITTING.value
                        or not isinstance(attempts, list)
                        or not attempts
                    ):
                        continue
                    latest = attempts[-1]
                    attempt_id = latest.get("attempt_id")
                    phase = latest.get("phase")
                    if (
                        not isinstance(attempt_id, str)
                        or phase not in _REVALIDATION_PROVIDER_PHASES
                        or "outcome" in latest
                    ):
                        continue
                    if not self._attempt_requires_recovery(
                        owner=latest.get("runtime_session_id"),
                        current_runtime_session_id=runtime_session_id,
                        recorded_at=self._revalidation_attempt_recorded_at(
                            review_id, revalidation_id, attempt_id
                        ),
                        cutoff=cutoff,
                    ):
                        continue
                    self._append_jsonl(
                        revalidation_dir / "events.jsonl",
                        {
                            "attempt_id": attempt_id,
                            "event_type": "REVALIDATION_ATTEMPT_OUTCOME",
                            "outcome": AttemptOutcome.OUTCOME_UNKNOWN.value,
                            "phase": phase,
                        },
                    )
                    recovered.append(attempt_id)

        return tuple(recovered)

    @staticmethod
    def _attempt_requires_recovery(
        *,
        owner: object,
        current_runtime_session_id: str | None,
        recorded_at: datetime | None,
        cutoff: datetime,
    ) -> bool:
        if current_runtime_session_id is not None and isinstance(owner, str):
            return owner != current_runtime_session_id
        return recorded_at is not None and recorded_at <= cutoff

    def _review_attempt_recorded_at(
        self, review_id: str, attempt_id: str
    ) -> datetime | None:
        try:
            events, warnings = self._read_jsonl(
                self._review_dir(review_id) / "events.jsonl"
            )
        except (OSError, TypeError, ValueError, OXEvidenceError):
            return None
        if warnings:
            return None
        for event in reversed(events):
            if (
                isinstance(event, Mapping)
                and event.get("event_type") == "TRANSMISSION_INTENT"
                and event.get("attempt_id") == attempt_id
            ):
                recorded_at = self._parse_recovery_timestamp(
                    event.get("recorded_at")
                )
                if recorded_at is not None:
                    return recorded_at
                break
        identity_path = (
            self._review_dir(review_id) / "attempts" / f"{attempt_id}.json"
        )
        try:
            identity = self._read_json(identity_path)
        except (OSError, TypeError, ValueError, OXEvidenceError):
            return None
        if not isinstance(identity, Mapping) or identity.get("attempt_id") != attempt_id:
            return None
        return self._parse_recovery_timestamp(identity.get("recorded_at"))

    def _revalidation_attempt_recorded_at(
        self,
        review_id: str,
        revalidation_id: str,
        attempt_id: str,
    ) -> datetime | None:
        directory = self._revalidation_dir(review_id, revalidation_id)
        try:
            events, warnings = self._read_jsonl(directory / "events.jsonl")
        except (OSError, TypeError, ValueError, OXEvidenceError):
            return None
        if warnings:
            return None
        for event in reversed(events):
            if (
                isinstance(event, Mapping)
                and event.get("event_type")
                == "REVALIDATION_TRANSMISSION_INTENT"
                and event.get("attempt_id") == attempt_id
            ):
                recorded_at = self._parse_recovery_timestamp(
                    event.get("recorded_at")
                )
                if recorded_at is not None:
                    return recorded_at
                break
        identity_path = directory / "attempts" / f"{attempt_id}.json"
        try:
            identity = self._read_json(identity_path)
        except (OSError, TypeError, ValueError, OXEvidenceError):
            return None
        if not isinstance(identity, Mapping) or identity.get("attempt_id") != attempt_id:
            return None
        return self._parse_recovery_timestamp(identity.get("recorded_at"))

    @staticmethod
    def _parse_recovery_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

    def claim_initial_transmission(
        self,
        review_id: str,
        manifest_sha256: str,
        *,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
        self._require_digest(manifest_sha256)
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            if review["state"] != ReviewState.PREPARED.value:
                raise OXEvidenceError("review is not prepared for transmission")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(
                review_id, manifest_sha256, runtime_session_id
            )

    def claim_retry_transmission(
        self,
        review_id: str,
        manifest_sha256: str,
        *,
        renewed_approval: bool,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
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
            return self._append_transmission_intent(
                review_id, manifest_sha256, runtime_session_id
            )

    def claim_continuation_transmission(
        self,
        review_id: str,
        manifest_sha256: str,
        *,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
        self._require_digest(manifest_sha256)
        with self._lock_for(review_id):
            review = self._reconstruct(review_id)
            self._reject_recovered_review(review)
            if review["state"] != ReviewState.REVIEWED.value:
                raise OXEvidenceError("review is not available for continuation")
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(
                review_id, manifest_sha256, runtime_session_id
            )

    def claim_continuation_retry(
        self,
        review_id: str,
        manifest_sha256: str,
        previous_attempt_id: str,
        *,
        renewed_approval: bool,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
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
                raise OXEvidenceError(
                    "continuation has no eligible attempt for retry"
                )
            previous = attempts[-1]
            if (
                previous.get("attempt_id") != previous_attempt_id
                or previous.get("outcome") not in _RETRYABLE_OUTCOMES
            ):
                raise OXEvidenceError(
                    "continuation retry does not match latest attempt"
                )
            self._verify_manifest_digest(review_id, manifest_sha256)
            return self._append_transmission_intent(
                review_id, manifest_sha256, runtime_session_id
            )

    def record_provider_request_started(
        self,
        review_id: str,
        attempt_id: str,
        *,
        runtime_session_id: str,
        phase: str,
    ) -> None:
        self._require_runtime_session_id(runtime_session_id)
        if phase not in _REVIEW_PROVIDER_PHASES:
            raise OXEvidenceError("provider request phase is invalid")
        with self._lock_for(review_id):
            try:
                review = self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError(
                    "unable to record provider request start"
                ) from None
            self._require_current_transmitting_attempt(review, attempt_id)
            attempt = review["attempts"][-1]
            self._require_attempt_owner(attempt, runtime_session_id)
            if "provider_started_at" in attempt:
                raise OXEvidenceError("provider request start already recorded")
            self._append_event(
                review_id,
                {
                    "attempt_id": attempt_id,
                    "event_type": "PROVIDER_REQUEST_STARTED",
                    "phase": phase,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "runtime_session_id": runtime_session_id,
                },
            )

    def record_provider_transport_metadata(
        self,
        review_id: str,
        attempt_id: str,
        *,
        runtime_session_id: str,
        provider_finished_at: str,
        elapsed_ms: int,
        transport_failure_kind: str | None,
    ) -> None:
        self._require_runtime_session_id(runtime_session_id)
        finished_at = self._require_provider_timestamp(provider_finished_at)
        failure_kind = self._require_transport_failure_kind(
            transport_failure_kind
        )
        self._require_elapsed_ms(elapsed_ms)
        with self._lock_for(review_id):
            try:
                review = self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError(
                    "unable to record provider transport metadata"
                ) from None
            attempt = self._require_current_attempt(review, attempt_id)
            self._require_attempt_owner(attempt, runtime_session_id)
            if "outcome" not in attempt:
                raise OXEvidenceError(
                    "provider transport metadata requires terminal outcome"
                )
            if "provider_finished_at" in attempt:
                raise OXEvidenceError(
                    "provider transport metadata already recorded"
                )
            self._require_finish_not_before_start(attempt, finished_at)
            self._append_event(
                review_id,
                {
                    "attempt_id": attempt_id,
                    "elapsed_ms": elapsed_ms,
                    "event_type": "PROVIDER_TRANSPORT_METADATA",
                    "provider_finished_at": provider_finished_at,
                    "runtime_session_id": runtime_session_id,
                    "transport_failure_kind": failure_kind,
                },
            )

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
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append thread message") from None
            try:
                self._append_jsonl(
                    self._review_dir(review_id)
                    / "threads"
                    / f"{thread_name}.jsonl",
                    message,
                )
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append thread message") from None

    def persist_provider_response(
        self, review_id: str, attempt_id: str, response: Mapping[str, object]
    ) -> None:
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            try:
                review = self._ensure_writable_review(review_id)
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError(
                    "unable to persist provider response"
                ) from None
            self._require_current_transmitting_attempt(review, attempt_id)
            try:
                self._write_immutable_json(
                    self._review_dir(review_id)
                    / "responses"
                    / f"{attempt_id}.json",
                    response,
                )
            except (OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError(
                    "unable to persist provider response"
                ) from None

    def read_provider_response(
        self, review_id: str, attempt_id: str
    ) -> dict[str, object]:
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            try:
                value = self._read_json(
                    self._review_dir(review_id)
                    / "responses"
                    / f"{attempt_id}.json"
                )
            except FileNotFoundError:
                raise OXEvidenceError(
                    "provider response evidence was not found"
                ) from None
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError(
                    "unable to read provider response"
                ) from None
            if not isinstance(value, dict):
                raise OXEvidenceError("provider response evidence is malformed")
            return value

    def persist_findings(
        self, review_id: str, findings: Mapping[str, object]
    ) -> None:
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
                self._write_immutable_json(
                    self._review_dir(review_id) / "findings" / "findings.json",
                    findings,
                )
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to persist findings") from None

    def append_adjudication(
        self, review_id: str, event: Mapping[str, object]
    ) -> None:
        with self._lock_for(review_id):
            try:
                self._ensure_writable_review(review_id)
                self._append_jsonl(
                    self._review_dir(review_id) / "adjudication.jsonl", event
                )
            except (OXEvidenceError, OSError, TypeError, ValueError, KeyError):
                raise OXEvidenceError("unable to append adjudication") from None

    def read_thread(
        self, review_id: str, thread_name: str = "initial"
    ) -> list[dict[str, object]]:
        self._require_thread_name(thread_name)
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            records, warnings = self._read_jsonl(
                self._review_dir(review_id)
                / "threads"
                / f"{thread_name}.jsonl"
            )
            if warnings or not all(isinstance(record, dict) for record in records):
                raise OXEvidenceError("thread evidence requires recovery")
            return [dict(record) for record in records]

    def findings_recorded(self, review_id: str) -> bool:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            path = self._review_dir(review_id) / "findings" / "findings.json"
            try:
                value = self._read_json(path)
            except FileNotFoundError:
                return False
            except (OSError, TypeError, ValueError):
                raise OXEvidenceError("unable to read findings") from None
            if not isinstance(value, dict):
                raise OXEvidenceError("findings evidence is malformed")
            return True

    def read_findings(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            try:
                value = self._read_json(
                    self._review_dir(review_id) / "findings" / "findings.json"
                )
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
            records, warnings = self._read_jsonl(
                self._review_dir(review_id) / "adjudication.jsonl"
            )
            if warnings or not all(isinstance(record, dict) for record in records):
                raise OXEvidenceError("adjudication evidence requires recovery")
            return [dict(record) for record in records]

    def read_manifest(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            value = self._read_json(
                self._review_dir(review_id) / "manifest.json"
            )
            if not isinstance(value, dict):
                raise OXEvidenceError("manifest evidence is malformed")
            return value

    def read_bundle(self, review_id: str) -> dict[str, object]:
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            value = self._read_json(
                self._review_dir(review_id) / "bundles" / "prepared.json"
            )
            if not isinstance(value, dict):
                raise OXEvidenceError("prepared bundle evidence is malformed")
            return value

    def read_attempt_identity(
        self, review_id: str, attempt_id: str
    ) -> dict[str, object]:
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            self._require_review_dir(review_id)
            try:
                value = self._read_json(
                    self._review_dir(review_id)
                    / "attempts"
                    / f"{attempt_id}.json"
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
                results.append(
                    self._reconstruct_revalidation(review_id, path.name)
                )
            return results

    def claim_revalidation_transmission(
        self,
        revalidation_id: str,
        *,
        phase: str,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
        if phase not in _REVALIDATION_PROVIDER_PHASES:
            raise OXEvidenceError("revalidation phase is invalid")
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            self._reject_recovered_revalidation(revalidation)
            required_state = (
                ReviewState.REVALIDATION_PREPARED.value
                if phase == "blind"
                else ReviewState.BLIND_REVALIDATED.value
            )
            if revalidation["state"] != required_state:
                raise OXEvidenceError(
                    "revalidation phase is not available for transmission"
                )
            digest = revalidation["manifest"]["manifest_sha256"]
            return self._append_revalidation_transmission_intent(
                review_id,
                revalidation_id,
                digest,
                phase,
                runtime_session_id,
            )

    def claim_revalidation_retry(
        self,
        revalidation_id: str,
        previous_attempt_id: str,
        *,
        renewed_approval: bool,
        runtime_session_id: str,
    ) -> dict[str, str]:
        self._require_runtime_session_id(runtime_session_id)
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, previous_attempt_id)
        if not renewed_approval:
            raise OXEvidenceError("retry requires renewed approval")
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            self._reject_recovered_revalidation(revalidation)
            attempts = revalidation["attempts"]
            if not attempts or revalidation["state"] not in {
                ReviewState.FAILED.value,
                ReviewState.OUTCOME_UNKNOWN.value,
            }:
                raise OXEvidenceError(
                    "revalidation has no eligible attempt for retry"
                )
            previous = attempts[-1]
            if (
                previous.get("attempt_id") != previous_attempt_id
                or previous.get("outcome") not in _RETRYABLE_OUTCOMES
            ):
                raise OXEvidenceError(
                    "revalidation retry does not match latest attempt"
                )
            digest = revalidation["manifest"]["manifest_sha256"]
            return self._append_revalidation_transmission_intent(
                review_id,
                revalidation_id,
                digest,
                str(previous["phase"]),
                runtime_session_id,
            )

    def record_revalidation_provider_request_started(
        self,
        revalidation_id: str,
        attempt_id: str,
        *,
        runtime_session_id: str,
        phase: str,
    ) -> None:
        self._require_runtime_session_id(runtime_session_id)
        if phase not in _REVALIDATION_PROVIDER_PHASES:
            raise OXEvidenceError("revalidation provider request phase is invalid")
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            self._reject_recovered_revalidation(revalidation)
            attempt = self._require_current_revalidation_transmitting_attempt(
                revalidation, attempt_id
            )
            self._require_attempt_owner(attempt, runtime_session_id)
            if attempt.get("phase") != phase:
                raise OXEvidenceError(
                    "revalidation provider request phase does not match attempt"
                )
            if "provider_started_at" in attempt:
                raise OXEvidenceError("provider request start already recorded")
            self._append_jsonl(
                self._revalidation_dir(review_id, revalidation_id)
                / "events.jsonl",
                {
                    "attempt_id": attempt_id,
                    "event_type": "PROVIDER_REQUEST_STARTED",
                    "phase": phase,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "runtime_session_id": runtime_session_id,
                },
            )

    def record_revalidation_provider_transport_metadata(
        self,
        revalidation_id: str,
        attempt_id: str,
        *,
        runtime_session_id: str,
        provider_finished_at: str,
        elapsed_ms: int,
        transport_failure_kind: str | None,
    ) -> None:
        self._require_runtime_session_id(runtime_session_id)
        finished_at = self._require_provider_timestamp(provider_finished_at)
        failure_kind = self._require_transport_failure_kind(
            transport_failure_kind
        )
        self._require_elapsed_ms(elapsed_ms)
        review_id = self._review_id_from_revalidation(revalidation_id)
        self._require_attempt_id(review_id, attempt_id)
        with self._lock_for(review_id):
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            self._reject_recovered_revalidation(revalidation)
            attempt = self._require_current_attempt(revalidation, attempt_id)
            self._require_attempt_owner(attempt, runtime_session_id)
            if "outcome" not in attempt:
                raise OXEvidenceError(
                    "provider transport metadata requires terminal outcome"
                )
            if "provider_finished_at" in attempt:
                raise OXEvidenceError(
                    "provider transport metadata already recorded"
                )
            self._require_finish_not_before_start(attempt, finished_at)
            self._append_jsonl(
                self._revalidation_dir(review_id, revalidation_id)
                / "events.jsonl",
                {
                    "attempt_id": attempt_id,
                    "elapsed_ms": elapsed_ms,
                    "event_type": "PROVIDER_TRANSPORT_METADATA",
                    "phase": attempt["phase"],
                    "provider_finished_at": provider_finished_at,
                    "runtime_session_id": runtime_session_id,
                    "transport_failure_kind": failure_kind,
                },
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
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            self._reject_recovered_revalidation(revalidation)
            attempts = revalidation["attempts"]
            if not attempts or attempts[-1].get("attempt_id") != attempt_id:
                raise OXEvidenceError("revalidation attempt is not current")
            if (
                revalidation["state"]
                != ReviewState.REVALIDATION_TRANSMITTING.value
            ):
                raise OXEvidenceError(
                    "revalidation attempt is not transmitting"
                )
            self._append_jsonl(
                self._revalidation_dir(review_id, revalidation_id)
                / "events.jsonl",
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
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            attempts = revalidation["attempts"]
            if (
                not attempts
                or attempts[-1].get("attempt_id") != attempt_id
                or revalidation["state"]
                != ReviewState.REVALIDATION_TRANSMITTING.value
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
            revalidation = self._reconstruct_revalidation(
                review_id, revalidation_id
            )
            attempts = revalidation["attempts"]
            if (
                not attempts
                or attempts[-1].get("attempt_id") != attempt_id
                or revalidation["state"]
                != ReviewState.REVALIDATION_TRANSMITTING.value
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
        if phase not in _REVALIDATION_PROVIDER_PHASES:
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

    def read_revalidation_bundle(
        self, revalidation_id: str
    ) -> dict[str, object]:
        review_id = self._review_id_from_revalidation(revalidation_id)
        with self._lock_for(review_id):
            self._reconstruct_revalidation(review_id, revalidation_id)
            value = self._read_json(
                self._revalidation_dir(review_id, revalidation_id) / "bundles" / "prepared.json"
            )
            if not isinstance(value, dict):
                raise OXEvidenceError(
                    "revalidation bundle evidence is malformed"
                )
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

    def _append_transmission_intent(
        self,
        review_id: str,
        manifest_sha256: str,
        runtime_session_id: str,
    ) -> dict[str, str]:
        attempt_id = self._allocate_attempt_id(review_id)
        attempt = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "runtime_session_id": runtime_session_id,
        }
        self._append_event(
            review_id,
            {
                **attempt,
                "event_type": "TRANSMISSION_INTENT",
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        return attempt

    def _append_revalidation_transmission_intent(
        self,
        review_id: str,
        revalidation_id: str,
        manifest_sha256: str,
        phase: str,
        runtime_session_id: str,
    ) -> dict[str, str]:
        attempt_id = self._allocate_attempt_id(review_id)
        attempt = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "phase": phase,
            "runtime_session_id": runtime_session_id,
        }
        self._append_jsonl(
            self._revalidation_dir(review_id, revalidation_id) / "events.jsonl",
            {
                **attempt,
                "event_type": "REVALIDATION_TRANSMISSION_INTENT",
                "recorded_at": datetime.now(UTC).isoformat(),
            },
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
                        raise OXEvidenceError(
                            "revalidation evidence requires recovery"
                        )
                    for event in records:
                        if not isinstance(event, dict):
                            raise OXEvidenceError(
                                "revalidation events are malformed"
                            )
                        attempt_id = event.get("attempt_id")
                        match = _ATTEMPT_ID.fullmatch(str(attempt_id))
                        if match is not None and match.group(1) == review_id:
                            maximum = max(maximum, int(match.group(2)))
            if maximum >= 999:
                raise OXEvidenceError("attempt identity space is exhausted")
            return f"{review_id}-A{maximum + 1:03d}"

    def _append_event(
        self, review_id: str, event: Mapping[str, object]
    ) -> None:
        try:
            self._append_jsonl(
                self._review_dir(review_id) / "events.jsonl", event
            )
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
        attempts: list[dict[str, object]] = []
        prepared_seen = False
        for event in events:
            if not isinstance(event, dict):
                raise OXEvidenceError("review events are malformed")
            event_type = event.get("event_type")
            if event_type == "TRANSMISSION_INTENT":
                attempt_id = event.get("attempt_id")
                digest = event.get("manifest_sha256")
                runtime_session_id = event.get("runtime_session_id")
                if (
                    not isinstance(attempt_id, str)
                    or not _attempt_belongs_to_review(review_id, attempt_id)
                    or digest != manifest_digest
                    or (
                        runtime_session_id is not None
                        and not _is_runtime_session_id(runtime_session_id)
                    )
                ):
                    raise OXEvidenceError("review events are malformed")
                attempt: dict[str, object] = {
                    "attempt_id": attempt_id,
                    "manifest_sha256": digest,
                }
                if runtime_session_id is not None:
                    attempt["runtime_session_id"] = runtime_session_id
                attempts.append(attempt)
                state = ReviewState.TRANSMITTING.value
            elif event_type == "PROVIDER_REQUEST_STARTED":
                self._apply_provider_started_event(
                    attempts,
                    event,
                    review_id=review_id,
                    expected_phase=None,
                    valid_phases=_REVIEW_PROVIDER_PHASES,
                )
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
                    (
                        attempt
                        for attempt in attempts
                        if attempt["attempt_id"] == attempt_id
                    ),
                    None,
                )
                if matching is None or "outcome" in matching:
                    raise OXEvidenceError("review events are malformed")
                matching["outcome"] = outcome
                state = {
                    AttemptOutcome.COMPLETED.value: ReviewState.REVIEWED.value,
                    AttemptOutcome.OUTCOME_UNKNOWN.value: (
                        ReviewState.OUTCOME_UNKNOWN.value
                    ),
                }.get(outcome, ReviewState.FAILED.value)
            elif event_type == "PROVIDER_TRANSPORT_METADATA":
                self._apply_transport_metadata_event(
                    attempts,
                    event,
                    review_id=review_id,
                    expected_phase=None,
                )
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
            raise OXEvidenceError(
                "unable to read revalidation evidence"
            ) from None
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
        attempts: list[dict[str, object]] = []
        prepared_seen = False
        for event in events:
            if not isinstance(event, dict):
                raise OXEvidenceError("revalidation events are malformed")
            event_type = event.get("event_type")
            if event_type == "REVALIDATION_PREPARED":
                if (
                    prepared_seen
                    or event.get("revalidation_id") != revalidation_id
                ):
                    raise OXEvidenceError("revalidation events are malformed")
                if event.get("manifest_sha256") != manifest_digest:
                    raise OXEvidenceError("revalidation events are malformed")
                prepared_seen = True
            elif event_type == "REVALIDATION_TRANSMISSION_INTENT":
                attempt_id = event.get("attempt_id")
                phase = event.get("phase")
                runtime_session_id = event.get("runtime_session_id")
                if (
                    not isinstance(attempt_id, str)
                    or not _attempt_belongs_to_review(review_id, attempt_id)
                    or event.get("manifest_sha256") != manifest_digest
                    or phase not in _REVALIDATION_PROVIDER_PHASES
                    or (
                        runtime_session_id is not None
                        and not _is_runtime_session_id(runtime_session_id)
                    )
                ):
                    raise OXEvidenceError("revalidation events are malformed")
                attempt = {
                    "attempt_id": attempt_id,
                    "manifest_sha256": manifest_digest,
                    "phase": phase,
                }
                if runtime_session_id is not None:
                    attempt["runtime_session_id"] = runtime_session_id
                attempts.append(attempt)
                state = ReviewState.REVALIDATION_TRANSMITTING.value
            elif event_type == "PROVIDER_REQUEST_STARTED":
                phase = event.get("phase")
                self._apply_provider_started_event(
                    attempts,
                    event,
                    review_id=review_id,
                    expected_phase=phase if isinstance(phase, str) else None,
                    valid_phases=_REVALIDATION_PROVIDER_PHASES,
                )
                if not attempts or attempts[-1].get("phase") != phase:
                    raise OXEvidenceError("revalidation events are malformed")
            elif event_type == "REVALIDATION_ATTEMPT_OUTCOME":
                attempt_id = event.get("attempt_id")
                outcome = event.get("outcome")
                phase = event.get("phase")
                if (
                    not isinstance(attempt_id, str)
                    or outcome not in {item.value for item in AttemptOutcome}
                    or phase not in _REVALIDATION_PROVIDER_PHASES
                ):
                    raise OXEvidenceError("revalidation events are malformed")
                matching = next(
                    (
                        attempt
                        for attempt in attempts
                        if attempt["attempt_id"] == attempt_id
                    ),
                    None,
                )
                if (
                    matching is None
                    or matching.get("phase") != phase
                    or "outcome" in matching
                ):
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
            elif event_type == "PROVIDER_TRANSPORT_METADATA":
                phase = event.get("phase")
                self._apply_transport_metadata_event(
                    attempts,
                    event,
                    review_id=review_id,
                    expected_phase=phase if isinstance(phase, str) else None,
                )
                if not attempts or attempts[-1].get("phase") != phase:
                    raise OXEvidenceError("revalidation events are malformed")
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

    @classmethod
    def _apply_provider_started_event(
        cls,
        attempts: list[dict[str, object]],
        event: Mapping[str, object],
        *,
        review_id: str,
        expected_phase: str | None,
        valid_phases: frozenset[str],
    ) -> None:
        attempt_id = event.get("attempt_id")
        runtime_session_id = event.get("runtime_session_id")
        phase = event.get("phase")
        recorded_at = event.get("recorded_at")
        if (
            not isinstance(attempt_id, str)
            or not _attempt_belongs_to_review(review_id, attempt_id)
            or not _is_runtime_session_id(runtime_session_id)
            or phase not in valid_phases
            or (expected_phase is not None and phase != expected_phase)
            or cls._safe_provider_timestamp(recorded_at) is None
        ):
            raise OXEvidenceError("review events are malformed")
        if not attempts or attempts[-1].get("attempt_id") != attempt_id:
            raise OXEvidenceError("review events are malformed")
        matching = attempts[-1]
        if (
            matching.get("runtime_session_id") != runtime_session_id
            or "outcome" in matching
            or "provider_started_at" in matching
        ):
            raise OXEvidenceError("review events are malformed")
        matching["provider_started_at"] = recorded_at

    @classmethod
    def _apply_transport_metadata_event(
        cls,
        attempts: list[dict[str, object]],
        event: Mapping[str, object],
        *,
        review_id: str,
        expected_phase: str | None,
    ) -> None:
        attempt_id = event.get("attempt_id")
        runtime_session_id = event.get("runtime_session_id")
        provider_finished_at = event.get("provider_finished_at")
        elapsed_ms = event.get("elapsed_ms")
        failure_kind = event.get("transport_failure_kind")
        phase = event.get("phase")
        parsed_finished_at = cls._safe_provider_timestamp(provider_finished_at)
        if (
            not isinstance(attempt_id, str)
            or not _attempt_belongs_to_review(review_id, attempt_id)
            or not _is_runtime_session_id(runtime_session_id)
            or parsed_finished_at is None
            or not _is_elapsed_ms(elapsed_ms)
            or not _is_transport_failure_kind(failure_kind)
            or (expected_phase is not None and phase != expected_phase)
        ):
            raise OXEvidenceError("review events are malformed")
        if not attempts or attempts[-1].get("attempt_id") != attempt_id:
            raise OXEvidenceError("review events are malformed")
        matching = attempts[-1]
        if (
            matching.get("runtime_session_id") != runtime_session_id
            or "outcome" not in matching
            or "provider_finished_at" in matching
        ):
            raise OXEvidenceError("review events are malformed")
        cls._require_finish_not_before_start(matching, parsed_finished_at)
        matching["provider_finished_at"] = provider_finished_at
        matching["elapsed_ms"] = elapsed_ms
        matching["transport_failure_kind"] = failure_kind

    def _verify_manifest_digest(
        self, review_id: str, manifest_sha256: str
    ) -> None:
        try:
            manifest = self._read_json(
                self._review_dir(review_id) / "manifest.json"
            )
            if (
                not isinstance(manifest, dict)
                or manifest.get("manifest_sha256") != manifest_sha256
            ):
                raise OXEvidenceError(
                    "manifest digest does not match prepared review"
                )
        except OXEvidenceError:
            raise
        except (OSError, TypeError, ValueError):
            raise OXEvidenceError("unable to verify manifest digest") from None

    def _ensure_writable_review(self, review_id: str) -> dict[str, object]:
        review = self._reconstruct(review_id)
        self._reject_recovered_review(review)
        return review

    @staticmethod
    def _require_current_attempt(
        record: Mapping[str, object], attempt_id: str
    ) -> dict[str, object]:
        attempts = record["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise OXEvidenceError("attempt identity is unknown")
        current = attempts[-1]
        if not isinstance(current, dict) or current.get("attempt_id") != attempt_id:
            if any(
                isinstance(attempt, Mapping)
                and attempt.get("attempt_id") == attempt_id
                for attempt in attempts
            ):
                raise OXEvidenceError("attempt is not the current transmission")
            raise OXEvidenceError("attempt identity is unknown")
        return current

    @classmethod
    def _require_current_transmitting_attempt(
        cls, review: Mapping[str, object], attempt_id: str
    ) -> None:
        cls._require_current_attempt(review, attempt_id)
        if review["state"] != ReviewState.TRANSMITTING.value:
            raise OXEvidenceError("attempt is not currently transmitting")

    @classmethod
    def _require_current_revalidation_transmitting_attempt(
        cls,
        revalidation: Mapping[str, object],
        attempt_id: str,
    ) -> dict[str, object]:
        current = cls._require_current_attempt(revalidation, attempt_id)
        if (
            revalidation["state"]
            != ReviewState.REVALIDATION_TRANSMITTING.value
        ):
            raise OXEvidenceError("revalidation attempt is not transmitting")
        return current

    @staticmethod
    def _require_attempt_owner(
        attempt: Mapping[str, object], runtime_session_id: str
    ) -> None:
        if attempt.get("runtime_session_id") != runtime_session_id:
            raise OXEvidenceError("attempt runtime session owner does not match")

    @classmethod
    def _require_finish_not_before_start(
        cls,
        attempt: Mapping[str, object],
        finished_at: datetime,
    ) -> None:
        started_value = attempt.get("provider_started_at")
        if started_value is None:
            return
        started_at = cls._safe_provider_timestamp(started_value)
        if started_at is None or finished_at < started_at:
            raise OXEvidenceError("provider timing metadata is invalid")

    @staticmethod
    def _reject_recovered_review(review: Mapping[str, object]) -> None:
        if review["recovery_warnings"]:
            raise OXEvidenceError(
                "review evidence requires recovery before mutation"
            )

    @staticmethod
    def _reject_recovered_revalidation(
        revalidation: Mapping[str, object]
    ) -> None:
        if revalidation["recovery_warnings"]:
            raise OXEvidenceError(
                "revalidation evidence requires recovery before mutation"
            )

    def _lock_for(self, review_id: str) -> threading.Lock:
        self._require_review_id(review_id)
        with self._review_locks_lock:
            return self._review_locks.setdefault(review_id, threading.Lock())

    def _review_dir(self, review_id: str) -> Path:
        return self._reviews / review_id

    def _revalidation_dir(
        self, review_id: str, revalidation_id: str
    ) -> Path:
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
        if (
            not isinstance(review_id, str)
            or _REVIEW_ID.fullmatch(review_id) is None
        ):
            raise OXEvidenceError("review identity is invalid")

    @staticmethod
    def _require_attempt_id(review_id: str, attempt_id: str) -> None:
        match = _ATTEMPT_ID.fullmatch(attempt_id)
        if match is None or match.group(1) != review_id:
            raise OXEvidenceError("attempt identity is invalid")

    @staticmethod
    def _require_revalidation_id(
        review_id: str, revalidation_id: str
    ) -> None:
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
        if (
            not isinstance(thread_name, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]*", thread_name)
        ):
            raise OXEvidenceError("thread identity is invalid")

    @staticmethod
    def _require_digest(manifest_sha256: str) -> None:
        if not _is_digest(manifest_sha256):
            raise OXEvidenceError("manifest digest is invalid")

    @staticmethod
    def _require_runtime_session_id(runtime_session_id: str) -> None:
        if not _is_runtime_session_id(runtime_session_id):
            raise OXEvidenceError("runtime session identity is invalid")

    @classmethod
    def _require_provider_timestamp(cls, value: str) -> datetime:
        parsed = cls._safe_provider_timestamp(value)
        if parsed is None:
            raise OXEvidenceError("provider timing metadata is invalid")
        return parsed

    @staticmethod
    def _safe_provider_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or len(value) > 64:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _require_elapsed_ms(elapsed_ms: int) -> None:
        if not _is_elapsed_ms(elapsed_ms):
            raise OXEvidenceError("provider elapsed time is invalid")

    @staticmethod
    def _require_transport_failure_kind(value: str | None) -> str | None:
        if isinstance(value, OXTransportFailureKind):
            return value.value
        if value is None:
            return None
        if not isinstance(value, str) or value not in _TRANSPORT_FAILURE_KINDS:
            raise OXEvidenceError("transport failure kind is invalid")
        return value

    @staticmethod
    def _write_immutable_json(
        path: Path, value: Mapping[str, object]
    ) -> None:
        if path.exists():
            raise OXEvidenceError("immutable evidence already exists")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = _canonical_json(value)
            with NamedTemporaryFile(
                "wb", dir=path.parent, delete=False
            ) as handle:
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
            raise OXEvidenceError(
                "unable to persist immutable evidence"
            ) from None

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
                    return records, [
                        "ignored malformed trailing events record"
                    ]
                raise OXEvidenceError("review events are malformed") from None
        return records, []


def _canonical_json(value: Mapping[str, object]) -> bytes:
    serialized = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return serialized.encode("utf-8")


def _enum_value(value: AttemptOutcome | str) -> str:
    return value.value if isinstance(value, AttemptOutcome) else value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _is_runtime_session_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and _RUNTIME_SESSION_ID.fullmatch(value) is not None
    )


def _is_elapsed_ms(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_transport_failure_kind(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and value in _TRANSPORT_FAILURE_KINDS
    )


def _attempt_belongs_to_review(review_id: str, attempt_id: str) -> bool:
    match = _ATTEMPT_ID.fullmatch(attempt_id)
    return match is not None and match.group(1) == review_id
