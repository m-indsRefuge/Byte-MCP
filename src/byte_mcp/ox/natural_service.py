"""Q03H natural-text initial worker over the established natural OX service."""

from __future__ import annotations

from collections.abc import Mapping

from byte_mcp.errors import OXApprovalError, OXEvidenceError, OXProtocolError

from ._natural_service_q03g import OXReviewService as _Q03GNaturalReviewService
from .models import AttemptOutcome, ProviderResult, ReviewState
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
