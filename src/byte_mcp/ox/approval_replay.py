from collections.abc import Mapping

from byte_mcp.errors import OXApprovalError, OXEvidenceError

from .models import ReviewState

_INITIAL_ATTEMPT_PHASES = frozenset({"initial", "initial-retry"})


class InitialApprovalReplayMixin:
    """Make duplicate initial approval a read-only observation of durable evidence."""

    def transmit_review(self, review_id: str) -> dict[str, object]:
        review = self._read_review_for_replay(review_id)
        if review.get("state") == ReviewState.PREPARED.value:
            try:
                return super().transmit_review(review_id)
            except OXApprovalError:
                latest = self._read_review_for_replay(review_id)
                if latest.get("state") == ReviewState.PREPARED.value:
                    raise
                status = self._initial_attempt_status(
                    review_id,
                    latest,
                    allow_missing_identity=latest.get("state")
                    == ReviewState.TRANSMITTING.value,
                )
                if status is not None:
                    return status
                raise

        status = self._initial_attempt_status(review_id, review)
        if status is not None:
            return status
        raise OXApprovalError("review state does not permit this operation")

    def _read_review_for_replay(self, review_id: str) -> dict[str, object]:
        try:
            return self._evidence.get_review(review_id)
        except OXEvidenceError as exc:
            raise OXApprovalError("review evidence is unavailable") from exc

    def _initial_attempt_status(
        self,
        review_id: str,
        review: Mapping[str, object],
        *,
        allow_missing_identity: bool = False,
    ) -> dict[str, object] | None:
        attempts = review.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return None
        attempt = attempts[-1]
        if not isinstance(attempt, Mapping):
            return None
        attempt_id = attempt.get("attempt_id")
        manifest_sha256 = attempt.get("manifest_sha256")
        if not isinstance(attempt_id, str) or not isinstance(manifest_sha256, str):
            return None

        try:
            identity = self._evidence.read_attempt_identity(review_id, attempt_id)
        except OXEvidenceError:
            if not allow_missing_identity:
                return None
        else:
            if identity.get("phase") not in _INITIAL_ATTEMPT_PHASES:
                return None

        try:
            thread = self._evidence.read_thread(review_id, "initial")
        except OXEvidenceError:
            thread = []
        response_available = any(
            message.get("role") == "assistant"
            and isinstance(message.get("content"), str)
            and bool(message["content"].strip())
            for message in thread
            if isinstance(message, Mapping)
        )

        return {
            "review_id": review_id,
            "attempt_id": attempt_id,
            "state": review.get("state"),
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": attempt.get("outcome"),
            "safe_error_type": attempt.get("safe_error_type"),
            "response_available": response_available,
            "replayed": True,
        }
