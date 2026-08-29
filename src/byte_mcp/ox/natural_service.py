"""Natural-text OX review orchestration layered on the hardened base service."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict

from byte_mcp.errors import OXProtocolError

from .models import AttemptOutcome, ProviderResult, ReviewState
from .service import OXReviewService as BaseOXReviewService
from .service import _PROVIDER_ERRORS


class OXReviewService(BaseOXReviewService):
    """Use natural OX review text while retaining base approval/evidence controls."""

    def _perform_attempt(
        self,
        *,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        try:
            result = self._client.complete(
                messages,
                json_mode=False,
                attempt_id=attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_provider_error(review_id, attempt_id, manifest_sha256, exc)
            raise

        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_provider_error(review_id, attempt_id, manifest_sha256, error)
            raise error

        # The raw provider response is canonical evidence and is durable before
        # any higher-level usability check is applied to the assistant text.
        self._evidence.persist_provider_response(review_id, attempt_id, result.raw_response)

        if not isinstance(result.content, str) or not result.content.strip():
            error = OXProtocolError(attempt_outcome=AttemptOutcome.REJECTED.value)
            self._record_provider_error(review_id, attempt_id, manifest_sha256, error)
            raise error

        self._evidence.append_thread_message(
            review_id,
            "initial",
            {"role": "assistant", "content": result.content},
        )
        self._evidence.record_attempt_outcome(
            review_id,
            attempt_id,
            AttemptOutcome.COMPLETED,
        )
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            AttemptOutcome.COMPLETED.value,
        )
        return {
            "review_id": review_id,
            "attempt_id": attempt_id,
            "state": ReviewState.REVIEWED.value,
            "manifest_sha256": manifest_sha256,
            "response": result.content,
            "usage": asdict(result.usage) if result.usage is not None else None,
        }
