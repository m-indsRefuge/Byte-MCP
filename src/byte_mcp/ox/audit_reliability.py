"""Bounded audit diagnostics for the live OX provider lifecycle."""

import re

from byte_mcp.errors import OXEvidenceError

from .models import AttemptOutcome

_SAFE_ERROR_TYPE = re.compile(r"OX[A-Za-z0-9]+Error")


class SafeAttemptAuditMixin:
    """Audit terminal OX attempts without recording provider or exception material."""

    def _audit_attempt(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        attempt_outcome: str,
        *,
        action: str = "ox_review",
        phase: str = "transmit",
        revalidation_id: str | None = None,
        safe_error_type: str | None = None,
    ) -> None:
        bounded_error_type = self._bounded_safe_error_type(
            review_id=review_id,
            attempt_id=attempt_id,
            revalidation_id=revalidation_id,
            explicit=safe_error_type,
        )
        fields: dict[str, object] = {
            "review_id": review_id,
            "phase": phase,
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": attempt_outcome,
        }
        if revalidation_id is not None:
            fields["revalidation_id"] = revalidation_id
        if bounded_error_type is not None:
            fields["safe_error_type"] = bounded_error_type
        self._audit.record(
            action,
            outcome="allowed" if attempt_outcome == AttemptOutcome.COMPLETED.value else "error",
            **fields,
        )

    def _bounded_safe_error_type(
        self,
        *,
        review_id: str,
        attempt_id: str,
        revalidation_id: str | None,
        explicit: str | None,
    ) -> str | None:
        candidate = explicit
        if candidate is None:
            try:
                record = (
                    self._evidence.get_revalidation(revalidation_id)
                    if revalidation_id is not None
                    else self._evidence.get_review(review_id)
                )
            except OXEvidenceError:
                return None
            attempts = record.get("attempts")
            if isinstance(attempts, list):
                for attempt in reversed(attempts):
                    if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
                        continue
                    observed = attempt.get("safe_error_type")
                    if isinstance(observed, str):
                        candidate = observed
                    break
        if candidate is None or _SAFE_ERROR_TYPE.fullmatch(candidate) is None:
            return None
        return candidate
