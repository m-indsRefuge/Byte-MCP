"""Q03H natural-text initial worker over the established natural OX service."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from byte_mcp.errors import OXApprovalError, OXEvidenceError, OXProtocolError

from ._natural_service_q03g import OXReviewService as _Q03GNaturalReviewService
from .models import AttemptOutcome, ProviderResult, ReviewState
from .protocol import build_initial_messages
from .service import _PROVIDER_ERRORS


class OXReviewService(_Q03GNaturalReviewService):
    """Keep natural OX authority while provider execution is runtime-owned."""

    def transmit_review(self, review_id: str) -> dict[str, object]:
        try:
            review = self._evidence.get_review(review_id)
        except OXEvidenceError as exc:
            raise OXApprovalError("review evidence is unavailable") from exc

        if review.get("state") == ReviewState.TRANSMITTING.value:
            replay = self._active_initial_replay(
                review_id,
                expected_operation="initial",
            )
            if replay is not None:
                return self._natural_launch_receipt(replay)

        result = super().transmit_review(review_id)
        if result.get("state") == ReviewState.TRANSMITTING.value:
            return self._natural_launch_receipt(result)
        return result

    def retry_review(self, review_id: str, *, renewed_approval: bool) -> dict[str, object]:
        result = super().retry_review(
            review_id,
            renewed_approval=renewed_approval,
        )
        if result.get("state") == ReviewState.TRANSMITTING.value:
            return self._natural_launch_receipt(result)
        return result

    def run_targeted_revalidation(
        self,
        revalidation_id: str,
        finding_ids: Sequence[str],
    ) -> dict[str, object]:
        """Q03H compatibility path until Task 6 backgrounds targeted revalidation."""
        revalidation = self._load_revalidation(
            revalidation_id,
            expected_state=ReviewState.BLIND_REVALIDATED,
        )
        self._require_validated_revalidation_phase(revalidation_id, "blind")
        if (
            isinstance(finding_ids, str | bytes | bytearray)
            or not isinstance(finding_ids, Sequence)
            or not finding_ids
            or not all(isinstance(finding_id, str) for finding_id in finding_ids)
        ):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)
        unique_finding_ids = set(finding_ids)
        if len(unique_finding_ids) != len(finding_ids):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)

        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            raise OXApprovalError("revalidation parent review is malformed")
        findings_payload = self._evidence.read_findings(review_id)
        if (
            findings_payload.get("protocol_version") != "byte-derived-findings-v1"
            or findings_payload.get("review_id") != review_id
            or findings_payload.get("derivation_authority") != "byte"
            or findings_payload.get("derivation_provenance")
            != "derived-from-ox-natural-review"
            or not isinstance(findings_payload.get("source_attempt_id"), str)
            or not isinstance(findings_payload.get("source_response_sha256"), str)
        ):
            raise OXApprovalError("targeted revalidation requires Byte-derived findings")

        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            raise OXApprovalError("Byte-derived findings evidence is malformed")
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
                "byte_derived_findings_provenance": {
                    "protocol_version": findings_payload["protocol_version"],
                    "derivation_authority": findings_payload["derivation_authority"],
                    "derivation_provenance": findings_payload["derivation_provenance"],
                    "source_attempt_id": findings_payload["source_attempt_id"],
                    "source_response_sha256": findings_payload["source_response_sha256"],
                },
                "byte_derived_findings": [findings[finding_id] for finding_id in finding_ids],
                "byte_adjudications": selected_adjudications,
            },
        }
        messages = build_initial_messages(
            targeted_packet,
            objective=(
                "Perform a targeted completeness pass using only the approved remediation packet "
                "and the explicitly Byte-derived finding/adjudication evidence. Treat the Byte "
                "context as local engineering interpretation, not as verbatim prior OX output."
            ),
        )
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        try:
            attempt = self._evidence.claim_revalidation_transmission(
                revalidation_id,
                phase="targeted",
                runtime_session_id=self._jobs.runtime_session_id,
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("targeted revalidation is not available") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_revalidation_attempt_identity(
            revalidation_id,
            attempt_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="targeted",
        )
        try:
            for message in messages:
                self._evidence.append_revalidation_thread_message(
                    revalidation_id,
                    "targeted-revalidation",
                    message,
                )
        except OXEvidenceError:
            self._record_revalidation_not_sent(revalidation_id, attempt_id)
            raise
        return self._perform_revalidation_attempt(
            revalidation_id=revalidation_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
            phase="targeted",
            thread_name="targeted-revalidation",
        )

    def _initial_review_receipt(
        self,
        review: Mapping[str, object],
        attempt: Mapping[str, object],
        *,
        review_text: str | None,
        usage: Mapping[str, object] | None,
        replayed: bool,
        provider_request_performed: bool,
    ) -> dict[str, object]:
        receipt = super()._initial_review_receipt(
            review,
            attempt,
            review_text=review_text,
            usage=usage,
            replayed=replayed,
            provider_request_performed=provider_request_performed,
        )
        receipt["launch_accepted"] = False
        return receipt

    def _natural_launch_receipt(
        self,
        receipt: Mapping[str, object],
    ) -> dict[str, object]:
        result = dict(receipt)
        review_id = result.get("review_id")
        if not isinstance(review_id, str):
            raise OXEvidenceError("initial launch receipt is malformed")
        result.update(
            {
                "review_text": None,
                "findings_recorded": self._evidence.findings_recorded(review_id),
                "usage": None,
            }
        )
        return result

    def _run_claimed_initial_attempt(self, descriptor) -> None:
        self._evidence.record_provider_request_started(
            descriptor.review_id,
            descriptor.attempt_id,
            runtime_session_id=self._jobs.runtime_session_id,
            phase="initial",
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

        if not isinstance(result.content, str) or not result.content.strip():
            error = OXProtocolError(attempt_outcome=AttemptOutcome.REJECTED.value)
            self._record_provider_error(
                descriptor.review_id,
                descriptor.attempt_id,
                descriptor.manifest_sha256,
                error,
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
        )


__all__ = ["OXReviewService"]
