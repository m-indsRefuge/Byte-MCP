"""Q03H background ownership facade over the established OX service core.

The Q03G orchestration remains the inherited implementation for provider-free
operations. Q03H overrides every provider-bearing path so claim ownership is
separated from provider execution and one runtime owns one provider lane.
"""

from __future__ import annotations

import hashlib
import json
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

from ._service_q03g import _PROVIDER_ERRORS, _history_sha256, _manifest_digest
from ._service_q03g import OXReviewService as _Q03GReviewService
from .jobs import (
    OXActiveLaunch,
    OXLaneLease,
    OXLaunchDescriptor,
    OXOperationKey,
    OXProviderJobManager,
)
from .models import AttemptOutcome, ProviderResult, ReviewState
from .protocol import build_initial_messages, parse_findings


class OXReviewService(_Q03GReviewService):
    """Add runtime-owned provider execution to the hardened Q03G core."""

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

    def get_review(self, review_id: str, *, view: str = "summary") -> dict[str, object]:
        if view != "attempts":
            return super().get_review(review_id, view=view)

        review = self._evidence.get_review(review_id)
        attempts = review.get("attempts")
        if not isinstance(attempts, list):
            raise OXEvidenceError("review attempt evidence is malformed")

        approved_fields = (
            "attempt_id",
            "manifest_sha256",
            "phase",
            "outcome",
            "runtime_session_id",
            "provider_started_at",
            "provider_finished_at",
            "elapsed_ms",
            "transport_failure_kind",
        )
        projected: list[dict[str, object]] = []
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                raise OXEvidenceError("review attempt evidence is malformed")
            item = {field: attempt[field] for field in approved_fields if field in attempt}
            if "runtime_session_id" in attempt:
                item["provider_request_started"] = "provider_started_at" in attempt
            projected.append(item)

        result: dict[str, object] = {"review_id": review_id, "attempts": projected}
        self._reject_configured_credential(result)
        return result

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

    def continue_message(self, review_id: str, message: str) -> dict[str, object]:
        """Launch one natural-text continuation without binding it to the MCP task."""
        if not isinstance(message, str) or not message.strip():
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)
        message = message.strip()

        replay = self._active_continuation_replay(
            review_id,
            expected_operation="continuation",
            message=message,
        )
        if replay is not None:
            return replay

        review = self._load_prepared_review(review_id, expected_state=ReviewState.REVIEWED)
        manifest_sha256 = _manifest_digest(review)
        history = self._evidence.read_thread(review_id, "initial")
        messages = [*history, {"role": "user", "content": message}]
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        operation_key = OXOperationKey(
            operation="continuation",
            subject_id=review_id,
            input_sha256=_history_sha256(messages),
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_continuation_transmission(
                review_id,
                manifest_sha256,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError("review is not available for continuation") from exc

        attempt_id = attempt["attempt_id"]
        try:
            self._persist_attempt_identity(
                review_id,
                attempt_id,
                manifest_sha256,
                messages,
                phase="continuation",
            )
            self._evidence.append_thread_message(review_id, "initial", messages[-1])
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase="continuation",
                revalidation_id=None,
                messages=tuple(messages),
            )
            receipt = self._continuation_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_before_submission(reservation, review_id, attempt_id)
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_continuation_attempt,
            self._terminalize_continuation_submission_failure,
            self._terminalize_continuation_worker_crash,
        )
        return receipt

    def retry_continuation(
        self,
        review_id: str,
        attempt_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, object]:
        """Launch an exact continuation retry only after renewed human approval."""
        if not renewed_approval:
            raise OXApprovalError("continuation retry requires renewed human approval")

        replay = self._active_continuation_replay(
            review_id,
            expected_operation="continuation-retry",
            retry_of=attempt_id,
        )
        if replay is not None:
            return replay

        review = self._load_prepared_review(
            review_id,
            expected_state=(ReviewState.FAILED, ReviewState.OUTCOME_UNKNOWN),
        )
        attempts = review.get("attempts")
        if (
            not isinstance(attempts, list)
            or not attempts
            or attempts[-1].get("attempt_id") != attempt_id
        ):
            raise OXApprovalError("continuation retry must reference the latest failed attempt")
        try:
            prior_identity = self._evidence.read_attempt_identity(review_id, attempt_id)
        except OXEvidenceError as exc:
            raise OXApprovalError("continuation attempt evidence is unavailable") from exc
        if prior_identity.get("phase") not in {"continuation", "continuation-retry"}:
            raise OXApprovalError("attempt is not a continuation attempt")
        messages = self._evidence.read_thread(review_id, "initial")
        if prior_identity.get("history_sha256") != _history_sha256(messages):
            raise OXApprovalError("continuation history no longer matches failed attempt")
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        manifest_sha256 = _manifest_digest(review)
        operation_key = OXOperationKey(
            operation="continuation-retry",
            subject_id=review_id,
            input_sha256=_retry_input_sha256(attempt_id, messages),
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_continuation_retry(
                review_id,
                manifest_sha256,
                attempt_id,
                renewed_approval=True,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError("continuation is not eligible for retry") from exc

        retry_attempt_id = attempt["attempt_id"]
        try:
            self._persist_attempt_identity(
                review_id,
                retry_attempt_id,
                manifest_sha256,
                messages,
                phase="continuation-retry",
                retry_of=attempt_id,
            )
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=retry_attempt_id,
                manifest_sha256=manifest_sha256,
                phase="continuation-retry",
                revalidation_id=None,
                messages=tuple(messages),
            )
            receipt = self._continuation_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_before_submission(
                reservation,
                review_id,
                retry_attempt_id,
            )
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_continuation_attempt,
            self._terminalize_continuation_submission_failure,
            self._terminalize_continuation_worker_crash,
        )
        return receipt

    def transmit_blind_revalidation(self, revalidation_id: str) -> dict[str, object]:
        replay = self._active_revalidation_replay(
            revalidation_id,
            expected_operation="blind",
        )
        if replay is not None:
            return replay

        revalidation = self._load_revalidation(
            revalidation_id,
            expected_state=ReviewState.REVALIDATION_PREPARED,
        )
        prepared, messages = self._rebuild_revalidation_and_verify(revalidation)
        return self._launch_revalidation_transmission(
            revalidation,
            revalidation_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="blind",
            operation="blind",
            thread_name="blind-revalidation",
            claim_error_message="revalidation is not available for blind approval",
        )

    def retry_revalidation(
        self,
        revalidation_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, object]:
        if not renewed_approval:
            raise OXApprovalError("revalidation retry requires renewed human approval")

        replay = self._active_revalidation_replay(
            revalidation_id,
            expected_operation="revalidation-retry",
        )
        if replay is not None:
            return replay

        revalidation = self._load_revalidation(
            revalidation_id,
            expected_state=(ReviewState.FAILED, ReviewState.OUTCOME_UNKNOWN),
        )
        attempts = revalidation.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise OXApprovalError("revalidation has no failed attempt to retry")
        previous = attempts[-1]
        previous_attempt_id = previous.get("attempt_id")
        phase = previous.get("phase")
        if not isinstance(previous_attempt_id, str) or phase not in {"blind", "targeted"}:
            raise OXApprovalError("revalidation attempt evidence is malformed")

        prepared, blind_messages = self._rebuild_revalidation_and_verify(revalidation)
        if phase == "blind":
            messages = blind_messages
        else:
            messages = self._evidence.read_revalidation_thread(
                revalidation_id,
                "targeted-revalidation",
            )
        prior_identity = self._read_revalidation_attempt_identity(
            revalidation_id,
            previous_attempt_id,
        )
        if (
            prior_identity.get("revalidation_id") != revalidation_id
            or prior_identity.get("phase") != phase
            or prior_identity.get("history_sha256") != _history_sha256(messages)
        ):
            raise OXApprovalError("revalidation history no longer matches failed attempt")
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)

        operation_key = OXOperationKey(
            operation="revalidation-retry",
            subject_id=revalidation_id,
            input_sha256=_revalidation_retry_input_sha256(
                previous_attempt_id,
                str(phase),
                messages,
            ),
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_revalidation_retry(
                revalidation_id,
                previous_attempt_id,
                renewed_approval=True,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError("revalidation is not eligible for retry") from exc

        attempt_id = attempt["attempt_id"]
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            self._cleanup_claimed_revalidation_before_submission(
                reservation,
                revalidation_id,
                attempt_id,
            )
            raise OXApprovalError("revalidation parent review is malformed")

        try:
            self._persist_revalidation_attempt_identity(
                revalidation_id,
                attempt_id,
                prepared.manifest.manifest_sha256,
                messages,
                phase=str(phase),
                retry_of=previous_attempt_id,
            )
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=prepared.manifest.manifest_sha256,
                phase=str(phase),
                revalidation_id=revalidation_id,
                messages=tuple(messages),
            )
            receipt = self._revalidation_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_revalidation_before_submission(
                reservation,
                revalidation_id,
                attempt_id,
            )
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_revalidation_attempt,
            self._terminalize_revalidation_submission_failure,
            self._terminalize_revalidation_worker_crash,
        )
        return receipt

    def run_targeted_revalidation(
        self,
        revalidation_id: str,
        finding_ids: Sequence[str],
    ) -> dict[str, object]:
        self._validate_targeted_finding_ids(finding_ids)
        replay = self._active_revalidation_replay(
            revalidation_id,
            expected_operation="targeted",
            finding_ids=finding_ids,
        )
        if replay is not None:
            return replay

        revalidation = self._load_revalidation(
            revalidation_id,
            expected_state=ReviewState.BLIND_REVALIDATED,
        )
        self._require_validated_revalidation_phase(revalidation_id, "blind")
        unique_finding_ids = set(finding_ids)
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            raise OXApprovalError("revalidation parent review is malformed")
        findings_payload = self._evidence.read_findings(review_id)
        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)
        findings = {
            item.get("finding_id"): item
            for item in raw_findings
            if isinstance(item, Mapping) and isinstance(item.get("finding_id"), str)
        }
        if any(finding_id not in findings for finding_id in finding_ids):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)
        adjudications = self._evidence.read_adjudications(review_id)
        selected_adjudications = [
            event for event in adjudications if event.get("finding_id") in unique_finding_ids
        ]
        prepared, _ = self._rebuild_revalidation_and_verify(revalidation)
        targeted_packet = {
            "approved_revalidation_packet": json.loads(
                prepared.serialized_packet.decode("utf-8")
            ),
            "targeted_context": {
                "original_findings": [findings[finding_id] for finding_id in finding_ids],
                "byte_adjudications": selected_adjudications,
            },
        }
        messages = build_initial_messages(
            targeted_packet,
            objective=(
                "Perform a targeted completeness pass using only the approved remediation packet "
                "and the selected prior finding/adjudication evidence."
            ),
        )
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        return self._launch_revalidation_transmission(
            revalidation,
            revalidation_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="targeted",
            operation="targeted",
            thread_name="targeted-revalidation",
            claim_error_message="targeted revalidation is not available",
            finding_ids=finding_ids,
        )

    def _launch_revalidation_transmission(
        self,
        revalidation: Mapping[str, object],
        revalidation_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
        *,
        phase: str,
        operation: str,
        thread_name: str,
        claim_error_message: str,
        finding_ids: Sequence[str] | None = None,
    ) -> dict[str, object]:
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            raise OXApprovalError("revalidation parent review is malformed")
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        input_sha256 = (
            _targeted_input_sha256(finding_ids, messages)
            if finding_ids is not None
            else _history_sha256(messages)
        )
        operation_key = OXOperationKey(
            operation=operation,
            subject_id=revalidation_id,
            input_sha256=input_sha256,
        )
        reservation = self._jobs.reserve(operation_key)
        if isinstance(reservation, OXActiveLaunch):
            return self._replay_launch_receipt(reservation)

        try:
            attempt = self._evidence.claim_revalidation_transmission(
                revalidation_id,
                phase=phase,
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            self._jobs.abandon(reservation)
            raise OXApprovalError(claim_error_message) from exc

        attempt_id = attempt["attempt_id"]
        try:
            self._persist_revalidation_attempt_identity(
                revalidation_id,
                attempt_id,
                manifest_sha256,
                messages,
                phase=phase,
            )
            for message in messages:
                self._evidence.append_revalidation_thread_message(
                    revalidation_id,
                    thread_name,
                    message,
                )
            descriptor = OXLaunchDescriptor(
                operation_key=operation_key,
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase=phase,
                revalidation_id=revalidation_id,
                messages=tuple(messages),
            )
            receipt = self._revalidation_launch_receipt(descriptor)
        except Exception:
            self._cleanup_claimed_revalidation_before_submission(
                reservation,
                revalidation_id,
                attempt_id,
            )
            raise

        self._jobs.submit(
            reservation,
            descriptor,
            receipt,
            self._run_claimed_revalidation_attempt,
            self._terminalize_revalidation_submission_failure,
            self._terminalize_revalidation_worker_crash,
        )
        return receipt

    def _validate_targeted_finding_ids(self, finding_ids: Sequence[str]) -> None:
        if (
            isinstance(finding_ids, str | bytes | bytearray)
            or not isinstance(finding_ids, Sequence)
            or not finding_ids
            or not all(isinstance(finding_id, str) for finding_id in finding_ids)
        ):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)
        if len(set(finding_ids)) != len(finding_ids):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)

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

    def _active_continuation_replay(
        self,
        review_id: str,
        *,
        expected_operation: str,
        message: str | None = None,
        retry_of: str | None = None,
    ) -> dict[str, object] | None:
        active = self._jobs.snapshot()
        if active is None:
            return None
        if active.descriptor.review_id != review_id:
            raise OXUnavailableError("OX provider lane is busy")
        if active.descriptor.operation_key.operation != expected_operation:
            raise OXUnavailableError("OX provider lane is busy")
        if expected_operation == "continuation":
            if message is None or not active.descriptor.messages:
                raise OXUnavailableError("OX provider lane is busy")
            if active.descriptor.messages[-1] != {"role": "user", "content": message}:
                raise OXUnavailableError("OX provider lane is busy")
        elif expected_operation == "continuation-retry":
            if retry_of is None:
                raise OXUnavailableError("OX provider lane is busy")
            identity = self._evidence.read_attempt_identity(
                review_id,
                active.descriptor.attempt_id,
            )
            if identity.get("retry_of") != retry_of:
                raise OXUnavailableError("OX provider lane is busy")
        return self._replay_launch_receipt(active)

    def _active_revalidation_replay(
        self,
        revalidation_id: str,
        *,
        expected_operation: str,
        finding_ids: Sequence[str] | None = None,
    ) -> dict[str, object] | None:
        active = self._jobs.snapshot()
        if active is None:
            return None
        if active.descriptor.revalidation_id != revalidation_id:
            raise OXUnavailableError("OX provider lane is busy")
        if active.descriptor.operation_key.operation != expected_operation:
            raise OXUnavailableError("OX provider lane is busy")
        if expected_operation == "targeted":
            if finding_ids is None:
                raise OXUnavailableError("OX provider lane is busy")
            expected_digest = _targeted_input_sha256(
                finding_ids,
                active.descriptor.messages,
            )
            if active.descriptor.operation_key.input_sha256 != expected_digest:
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

    @staticmethod
    def _continuation_launch_receipt(descriptor: OXLaunchDescriptor) -> dict[str, object]:
        return {
            "review_id": descriptor.review_id,
            "attempt_id": descriptor.attempt_id,
            "state": ReviewState.TRANSMITTING.value,
            "manifest_sha256": descriptor.manifest_sha256,
            "launch_accepted": True,
            "replayed": False,
            "provider_request_performed": False,
        }

    @staticmethod
    def _revalidation_launch_receipt(descriptor: OXLaunchDescriptor) -> dict[str, object]:
        revalidation_id = descriptor.revalidation_id
        if revalidation_id is None:
            raise OXEvidenceError("revalidation launch descriptor is malformed")
        return {
            "review_id": descriptor.review_id,
            "revalidation_id": revalidation_id,
            "attempt_id": descriptor.attempt_id,
            "state": ReviewState.TRANSMITTING.value,
            "manifest_sha256": descriptor.manifest_sha256,
            "phase": descriptor.phase,
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
            if self._attempt_is_already_not_sent(review_id, attempt_id):
                self._jobs.abandon(lease)
                return
            self._jobs.fault_closed(lease)
            raise
        self._jobs.abandon(lease)

    def _cleanup_claimed_revalidation_before_submission(
        self,
        lease: OXLaneLease,
        revalidation_id: str,
        attempt_id: str,
    ) -> None:
        try:
            self._evidence.record_revalidation_attempt_outcome(
                revalidation_id,
                attempt_id,
                AttemptOutcome.NOT_SENT,
            )
        except Exception:
            if self._revalidation_attempt_is_already_not_sent(
                revalidation_id,
                attempt_id,
            ):
                self._jobs.abandon(lease)
                return
            self._jobs.fault_closed(lease)
            raise
        self._jobs.abandon(lease)

    def _attempt_is_already_not_sent(self, review_id: str, attempt_id: str) -> bool:
        try:
            review = self._evidence.get_review(review_id)
        except Exception:
            return False
        attempts = review.get("attempts")
        if not isinstance(attempts, list):
            return False
        return any(
            isinstance(attempt, Mapping)
            and attempt.get("attempt_id") == attempt_id
            and attempt.get("outcome") == AttemptOutcome.NOT_SENT.value
            for attempt in attempts
        )

    def _revalidation_attempt_is_already_not_sent(
        self,
        revalidation_id: str,
        attempt_id: str,
    ) -> bool:
        try:
            revalidation = self._evidence.get_revalidation(revalidation_id)
        except Exception:
            return False
        attempts = revalidation.get("attempts")
        if not isinstance(attempts, list):
            return False
        return any(
            isinstance(attempt, Mapping)
            and attempt.get("attempt_id") == attempt_id
            and attempt.get("outcome") == AttemptOutcome.NOT_SENT.value
            for attempt in attempts
        )

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

    def _terminalize_continuation_submission_failure(
        self,
        descriptor: OXLaunchDescriptor,
    ) -> None:
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
            action="ox_continue",
            phase="submission-failure",
        )

    def _terminalize_continuation_worker_crash(
        self,
        descriptor: OXLaunchDescriptor,
    ) -> None:
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
            action="ox_continue",
            phase="worker-crash",
        )

    def _terminalize_revalidation_submission_failure(
        self,
        descriptor: OXLaunchDescriptor,
    ) -> None:
        revalidation_id = self._descriptor_revalidation_id(descriptor)
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            descriptor.attempt_id,
            AttemptOutcome.NOT_SENT,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.NOT_SENT.value,
            action="ox_revalidate",
            phase="submission-failure",
            revalidation_id=revalidation_id,
        )

    def _terminalize_revalidation_worker_crash(
        self,
        descriptor: OXLaunchDescriptor,
    ) -> None:
        revalidation_id = self._descriptor_revalidation_id(descriptor)
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            descriptor.attempt_id,
            AttemptOutcome.OUTCOME_UNKNOWN,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.OUTCOME_UNKNOWN.value,
            action="ox_revalidate",
            phase="worker-crash",
            revalidation_id=revalidation_id,
        )

    @staticmethod
    def _descriptor_revalidation_id(descriptor: OXLaunchDescriptor) -> str:
        revalidation_id = descriptor.revalidation_id
        if revalidation_id is None:
            raise OXEvidenceError("revalidation launch descriptor is malformed")
        return revalidation_id

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

    def _run_claimed_continuation_attempt(self, descriptor: OXLaunchDescriptor) -> None:
        """Execute one already-claimed natural-text continuation attempt."""
        self._evidence.record_provider_request_started(
            descriptor.review_id,
            descriptor.attempt_id,
            runtime_session_id=self._jobs.runtime_session_id,
            phase="continuation",
        )
        try:
            result = self._client.complete(
                descriptor.messages,
                json_mode=False,
                attempt_id=descriptor.attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                exc,
                action="ox_continue",
                phase=(
                    "retry"
                    if descriptor.phase == "continuation-retry"
                    else "message"
                ),
            )
            return

        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                error,
                action="ox_continue",
                phase=(
                    "retry"
                    if descriptor.phase == "continuation-retry"
                    else "message"
                ),
            )
            return

        self._evidence.persist_provider_response(
            descriptor.review_id,
            descriptor.attempt_id,
            result.raw_response,
        )
        if not isinstance(result.content, str) or not result.content.strip():
            error = OXProtocolError(attempt_outcome=AttemptOutcome.REJECTED.value)
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                error,
                action="ox_continue",
                phase=(
                    "retry"
                    if descriptor.phase == "continuation-retry"
                    else "message"
                ),
            )
            return

        self._evidence.append_thread_message(
            descriptor.review_id,
            "initial",
            {"role": "assistant", "content": result.content},
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
            action="ox_continue",
            phase=(
                "retry"
                if descriptor.phase == "continuation-retry"
                else "message"
            ),
        )

    def _run_claimed_revalidation_attempt(self, descriptor: OXLaunchDescriptor) -> None:
        """Execute one already-claimed structured base-service revalidation attempt."""
        revalidation_id = self._descriptor_revalidation_id(descriptor)
        self._evidence.record_revalidation_provider_request_started(
            revalidation_id,
            descriptor.attempt_id,
            runtime_session_id=self._jobs.runtime_session_id,
            phase=descriptor.phase,
        )
        try:
            result = self._client.complete(
                descriptor.messages,
                json_mode=True,
                attempt_id=descriptor.attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_revalidation_provider_error(
                revalidation_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                exc,
                phase=descriptor.phase,
            )
            return

        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_revalidation_provider_error(
                revalidation_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                error,
                phase=descriptor.phase,
            )
            return

        self._evidence.persist_revalidation_provider_response(
            revalidation_id,
            descriptor.attempt_id,
            result.raw_response,
        )
        thread_name = (
            "blind-revalidation"
            if descriptor.phase == "blind"
            else "targeted-revalidation"
        )
        self._evidence.append_revalidation_thread_message(
            revalidation_id,
            thread_name,
            {"role": "assistant", "content": result.content},
        )
        try:
            findings = parse_findings(result.content, descriptor.review_id)
        except OXFindingValidationError:
            self._persist_invalid_revalidation_findings(
                descriptor.review_id,
                revalidation_id,
                descriptor.attempt_id,
                descriptor.phase,
                result.content,
            )
            self._evidence.record_revalidation_attempt_outcome(
                revalidation_id,
                descriptor.attempt_id,
                AttemptOutcome.COMPLETED,
            )
            self._audit_attempt(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                AttemptOutcome.COMPLETED.value,
                action="ox_revalidate",
                phase=f"{descriptor.phase}-protocol-failure",
                revalidation_id=revalidation_id,
            )
            return

        self._evidence.persist_revalidation_findings(
            revalidation_id,
            descriptor.phase,
            {
                "protocol_version": "ox-findings-v1",
                "findings": [asdict(finding) for finding in findings],
            },
        )
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            descriptor.attempt_id,
            AttemptOutcome.COMPLETED,
        )
        self._audit_attempt(
            descriptor.review_id,
            descriptor.attempt_id,
            descriptor.manifest_sha256,
            AttemptOutcome.COMPLETED.value,
            action="ox_revalidate",
            phase=descriptor.phase,
            revalidation_id=revalidation_id,
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

    def _record_revalidation_provider_error(
        self,
        revalidation_id: str,
        attempt_id: str,
        manifest_sha256: str,
        error,
        *,
        phase: str,
    ) -> None:
        outcome = error.attempt_outcome
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            attempt_id,
            outcome,
        )
        if isinstance(error, OXTransportError):
            kind = error.transport_failure_kind
            finished_at = error.provider_finished_at
            elapsed_ms = error.elapsed_ms
            if kind is not None and finished_at is not None and elapsed_ms is not None:
                self._evidence.record_revalidation_provider_transport_metadata(
                    revalidation_id,
                    attempt_id,
                    runtime_session_id=self._jobs.runtime_session_id,
                    provider_finished_at=finished_at,
                    elapsed_ms=elapsed_ms,
                    transport_failure_kind=kind.value,
                )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            raise OXEvidenceError("revalidation parent review evidence is malformed")
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            outcome,
            action="ox_revalidate",
            phase=phase,
            revalidation_id=revalidation_id,
        )


def _retry_input_sha256(
    retry_of: str,
    messages: Sequence[Mapping[str, object]],
) -> str:
    material = f"{retry_of}:{_history_sha256(messages)}".encode()
    return hashlib.sha256(material).hexdigest()


def _revalidation_retry_input_sha256(
    retry_of: str,
    phase: str,
    messages: Sequence[Mapping[str, object]],
) -> str:
    material = f"{retry_of}:{phase}:{_history_sha256(messages)}".encode()
    return hashlib.sha256(material).hexdigest()


def _targeted_input_sha256(
    finding_ids: Sequence[str],
    messages: Sequence[Mapping[str, object]],
) -> str:
    material = json.dumps(
        {
            "finding_ids": list(finding_ids),
            "history_sha256": _history_sha256(messages),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


__all__ = [
    "OXReviewService",
]
