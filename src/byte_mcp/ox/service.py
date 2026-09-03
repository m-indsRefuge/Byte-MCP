"""Q03H background ownership facade over the established OX service core.

The Q03G orchestration remains the inherited implementation for provider-free
and not-yet-migrated Task 5/6 paths. Q03H overrides initial review and explicit
initial retry so claim ownership is separated from provider execution.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime

from byte_mcp.errors import (
    OXApprovalError,
    OXEvidenceError,
    OXFindingValidationError,
    OXProtocolError,
    OXTransportError,
    OXUnavailableError,
)

from ._service_q03g import OXReviewService as _Q03GReviewService
from ._service_q03g import _PROVIDER_ERRORS, _history_sha256
from .jobs import (
    OXActiveLaunch,
    OXLaneLease,
    OXLaunchDescriptor,
    OXOperationKey,
    OXProviderJobManager,
)
from .models import AttemptOutcome, ProviderResult, ReviewState
from .protocol import parse_findings


class OXReviewService(_Q03GReviewService):
    """Add runtime-owned initial provider execution to the hardened Q03G core."""

    def __init__(
        self,
        settings,
        evidence,
        client,
        audit,
        jobs: OXProviderJobManager | None = None,
    ) -> None:
        super().__init__(settings, evidence, client, audit)
        self._jobs = jobs if jobs is not None else OXProviderJobManager()

    def transmit_review(self, review_id: str) -> dict[str, object]:
        replay = self._active_initial_replay(review_id, expected_operation="initial")
        if replay is not None:
            return replay

        review = self._load_prepared_review(review_id, expected_state=ReviewState.PREPARED)
        prepared, messages = self._rebuild_and_verify(review)
        manifest_sha256 = prepared.manifest.manifest_sha256
        operation_key = OXOperationKey(
            operation="initial",
            subject_id=review_id,
            input_sha256=_history_sha256(messages),
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_initial_transmission(
                review_id,
                manifest_sha256,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError("review is not available for initial approval") from exc

        attempt_id = attempt["attempt_id"]
        try:
            self._persist_claimed_initial_identity(
                review_id,
                attempt_id,
                manifest_sha256,
                messages,
                phase="initial",
            )
            for message in messages:
                self._evidence.append_thread_message(review_id, "initial", message)
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase="initial",
                revalidation_id=None,
                messages=tuple(messages),
            )
            receipt = self._initial_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_before_submission(reservation, review_id, attempt_id)
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_initial_attempt,
            self._terminalize_submission_failure,
            self._terminalize_worker_crash,
        )
        return receipt

    def retry_review(self, review_id: str, *, renewed_approval: bool) -> dict[str, object]:
        if not renewed_approval:
            raise OXApprovalError("retry requires renewed human approval")

        replay = self._active_initial_replay(
            review_id,
            expected_operation="initial-retry",
        )
        if replay is not None:
            return replay

        review = self._load_prepared_review(
            review_id,
            expected_state=(ReviewState.FAILED, ReviewState.OUTCOME_UNKNOWN),
        )
        prepared, messages = self._rebuild_and_verify(review)
        attempts = review.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise OXApprovalError("review has no eligible attempt for retry")
        retry_of = attempts[-1].get("attempt_id")
        if not isinstance(retry_of, str):
            raise OXApprovalError("review attempt evidence is malformed")
        manifest_sha256 = prepared.manifest.manifest_sha256
        operation_key = OXOperationKey(
            operation="initial-retry",
            subject_id=review_id,
            input_sha256=_retry_input_sha256(retry_of, messages),
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_retry_transmission(
                review_id,
                manifest_sha256,
                renewed_approval=True,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError("review is not eligible for retry") from exc

        attempt_id = attempt["attempt_id"]
        try:
            self._persist_claimed_initial_identity(
                review_id,
                attempt_id,
                manifest_sha256,
                messages,
                phase="initial-retry",
                retry_of=retry_of,
            )
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase="initial-retry",
                revalidation_id=None,
                messages=tuple(messages),
            )
            receipt = self._initial_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_before_submission(reservation, review_id, attempt_id)
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_initial_attempt,
            self._terminalize_submission_failure,
            self._terminalize_worker_crash,
        )
        return receipt

    def _active_initial_replay(
        self,
        review_id: str,
        *,
        expected_operation: str,
    ) -> dict[str, object] | None:
        active = self._jobs.snapshot()
        if active is None or active.descriptor.review_id != review_id:
            return None
        if active.descriptor.operation_key.operation != expected_operation:
            raise OXUnavailableError("OX provider lane is busy")
        return self._replay_launch_receipt(active)

    @staticmethod
    def _replay_launch_receipt(active: OXActiveLaunch) -> dict[str, object]:
        receipt = dict(active.receipt)
        receipt["launch_accepted"] = False
        receipt["replayed"] = True
        receipt["provider_request_performed"] = False
        return receipt

    @staticmethod
    def _initial_launch_receipt(descriptor: OXLaunchDescriptor) -> dict[str, object]:
        return {
            "review_id": descriptor.review_id,
            "attempt_id": descriptor.attempt_id,
            "state": ReviewState.TRANSMITTING.value,
            "manifest_sha256": descriptor.manifest_sha256,
            "launch_accepted": True,
            "replayed": False,
            "provider_request_performed": False,
        }

    def _persist_claimed_initial_identity(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
        *,
        phase: str,
        retry_of: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "history_sha256": _history_sha256(messages),
            "phase": phase,
            "recorded_at": datetime.now(UTC).isoformat(),
            "runtime_session_id": self._jobs.runtime_session_id,
        }
        if retry_of is not None:
            payload["retry_of"] = retry_of
        path = (
            self._settings.evidence_root
            / "reviews"
            / review_id
            / "attempts"
            / f"{attempt_id}.json"
        )
        self._evidence._write_immutable_json(path, payload)

    def _cleanup_claimed_before_submission(
        self,
        lease: OXLaneLease,
        review_id: str,
        attempt_id: str,
    ) -> None:
        try:
            self._evidence.record_attempt_outcome(
                review_id,
                attempt_id,
                AttemptOutcome.NOT_SENT,
            )
        except Exception:
            self._jobs.fault_closed(lease)
            raise
        self._jobs.abandon(lease)

    def _terminalize_submission_failure(self, descriptor: OXLaunchDescriptor) -> None:
        self._evidence.record_attempt_outcome(
            descriptor.review_id,
            descriptor.attempt_id,
            AttemptOutcome.NOT_SENT,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.NOT_SENT.value,
            phase="submission-failure",
        )

    def _terminalize_worker_crash(self, descriptor: OXLaunchDescriptor) -> None:
        self._evidence.record_attempt_outcome(
            descriptor.review_id,
            descriptor.attempt_id,
            AttemptOutcome.OUTCOME_UNKNOWN,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.OUTCOME_UNKNOWN.value,
            phase="worker-crash",
        )

    def _run_claimed_initial_attempt(self, descriptor: OXLaunchDescriptor) -> None:
        """Execute one already-claimed structured base-service initial attempt."""
        self._evidence.record_provider_request_started(
            descriptor.review_id,
            descriptor.attempt_id,
            runtime_session_id=self._jobs.runtime_session_id,
            phase="initial",
        )
        try:
            result = self._client.complete(
                descriptor.messages,
                json_mode=True,
                attempt_id=descriptor.attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                exc,
            )
            return

        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                error,
            )
            return

        self._evidence.persist_provider_response(
            descriptor.review_id,
            descriptor.attempt_id,
            result.raw_response,
        )
        self._evidence.append_thread_message(
            descriptor.review_id,
            "initial",
            {"role": "assistant", "content": result.content},
        )
        try:
            findings = parse_findings(result.content, descriptor.review_id)
        except OXFindingValidationError:
            self._persist_invalid_findings(
                descriptor.review_id,
                descriptor.attempt_id,
                result.content,
            )
            self._evidence.record_attempt_outcome(
                descriptor.review_id,
                descriptor.attempt_id,
                AttemptOutcome.COMPLETED,
            )
            self._audit_attempt(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                AttemptOutcome.COMPLETED.value,
            )
            return

        self._evidence.persist_findings(
            descriptor.review_id,
            {
                "protocol_version": "ox-findings-v1",
                "findings": [asdict(finding) for finding in findings],
            },
        )
        self._evidence.record_attempt_outcome(
            descriptor.review_id,
            descriptor.attempt_id,
            AttemptOutcome.COMPLETED,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.COMPLETED.value,
        )

    def _record_provider_error(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        error,
        *,
        action: str = "ox_review",
        phase: str = "transmit",
    ) -> None:
        outcome = error.attempt_outcome
        self._evidence.record_attempt_outcome(review_id, attempt_id, outcome)
        if isinstance(error, OXTransportError):
            kind = error.transport_failure_kind
            finished_at = error.provider_finished_at
            elapsed_ms = error.elapsed_ms
            if kind is not None and finished_at is not None and elapsed_ms is not None:
                self._evidence.record_provider_transport_metadata(
                    review_id,
                    attempt_id,
                    runtime_session_id=self._jobs.runtime_session_id,
                    provider_finished_at=finished_at,
                    elapsed_ms=elapsed_ms,
                    transport_failure_kind=kind.value,
                )
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            outcome,
            action=action,
            phase=phase,
        )


def _retry_input_sha256(
    retry_of: str,
    messages: Sequence[Mapping[str, object]],
) -> str:
    material = f"{retry_of}:{_history_sha256(messages)}".encode()
    return hashlib.sha256(material).hexdigest()


__all__ = [
    "OXReviewService",
]
