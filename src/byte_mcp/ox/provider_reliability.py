"""Structured provider-attempt outcomes for the live OX lifecycle."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict

from .execution import execute_provider_attempt
from .models import AttemptOutcome, ProviderResult, ReviewState


class ProviderReliabilityMixin:
    """Keep provider failures inside durable OX lifecycle results."""

    def _perform_text_attempt(
        self,
        *,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        execution = execute_provider_attempt(
            self._client,
            messages,
            json_mode=False,
            attempt_id=attempt_id,
        )
        if execution.provider_result is None:
            return self._terminal_continuation_result(
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                outcome=execution.outcome,
                safe_error_type=execution.safe_error_type,
            )

        result = execution.provider_result
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            return self._terminal_continuation_result(
                review_id=review_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                outcome=AttemptOutcome.COMPLETED,
                safe_error_type="OXProtocolError",
            )

        self._evidence.persist_provider_response(review_id, attempt_id, result.raw_response)
        self._evidence.append_thread_message(
            review_id,
            "initial",
            {"role": "assistant", "content": result.content},
        )
        self._evidence.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.COMPLETED)
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            AttemptOutcome.COMPLETED.value,
            action="ox_continue",
            phase="message",
        )
        return {
            "review_id": review_id,
            "attempt_id": attempt_id,
            "state": ReviewState.REVIEWED.value,
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": AttemptOutcome.COMPLETED.value,
            "safe_error_type": None,
            "response_available": True,
            "replayed": False,
            "response": result.content,
            "usage": asdict(result.usage) if result.usage is not None else None,
        }

    def _terminal_continuation_result(
        self,
        *,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        outcome: AttemptOutcome,
        safe_error_type: str | None,
    ) -> dict[str, object]:
        self._evidence.record_attempt_outcome(
            review_id,
            attempt_id,
            outcome,
            safe_error_type=safe_error_type,
        )
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            outcome.value,
            action="ox_continue",
            phase="message",
        )
        state = self._evidence.get_review(review_id)["state"]
        return {
            "review_id": review_id,
            "attempt_id": attempt_id,
            "state": state,
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": outcome.value,
            "safe_error_type": safe_error_type,
            "response_available": False,
            "replayed": False,
        }

    def _perform_revalidation_attempt(
        self,
        *,
        revalidation_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
        phase: str,
        thread_name: str,
    ) -> dict[str, object]:
        execution = execute_provider_attempt(
            self._client,
            messages,
            json_mode=False,
            attempt_id=attempt_id,
        )
        if execution.provider_result is None:
            return self._terminal_revalidation_result(
                revalidation_id=revalidation_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase=phase,
                outcome=execution.outcome,
                safe_error_type=execution.safe_error_type,
            )

        result = execution.provider_result
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            return self._terminal_revalidation_result(
                revalidation_id=revalidation_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase=phase,
                outcome=AttemptOutcome.COMPLETED,
                safe_error_type="OXProtocolError",
            )

        self._evidence.persist_revalidation_provider_response(
            revalidation_id,
            attempt_id,
            result.raw_response,
        )
        if not isinstance(result.content, str) or not result.content.strip():
            return self._terminal_revalidation_result(
                revalidation_id=revalidation_id,
                attempt_id=attempt_id,
                manifest_sha256=manifest_sha256,
                phase=phase,
                outcome=AttemptOutcome.REJECTED,
                safe_error_type="OXProtocolError",
            )

        self._evidence.append_revalidation_thread_message(
            revalidation_id,
            thread_name,
            {"role": "assistant", "content": result.content},
        )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        review_id = revalidation["review_id"]
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            attempt_id,
            AttemptOutcome.COMPLETED,
        )
        completed = self._effective_revalidation(
            self._evidence.get_revalidation(revalidation_id)
        )
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            AttemptOutcome.COMPLETED.value,
            action="ox_revalidate",
            phase=phase,
            revalidation_id=revalidation_id,
        )
        return {
            "review_id": review_id,
            "revalidation_id": revalidation_id,
            "attempt_id": attempt_id,
            "phase": phase,
            "state": completed["state"],
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": AttemptOutcome.COMPLETED.value,
            "safe_error_type": None,
            "response_available": True,
            "replayed": False,
            "response": result.content,
            "usage": asdict(result.usage) if result.usage is not None else None,
        }

    def _terminal_revalidation_result(
        self,
        *,
        revalidation_id: str,
        attempt_id: str,
        manifest_sha256: str,
        phase: str,
        outcome: AttemptOutcome,
        safe_error_type: str | None,
    ) -> dict[str, object]:
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id,
            attempt_id,
            outcome,
            safe_error_type=safe_error_type,
        )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        review_id = revalidation["review_id"]
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            outcome.value,
            action="ox_revalidate",
            phase=phase,
            revalidation_id=revalidation_id,
        )
        return {
            "review_id": review_id,
            "revalidation_id": revalidation_id,
            "attempt_id": attempt_id,
            "phase": phase,
            "state": revalidation["state"],
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": outcome.value,
            "safe_error_type": safe_error_type,
            "response_available": False,
            "replayed": False,
        }
