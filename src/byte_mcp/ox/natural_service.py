"""Natural-text OX review orchestration layered on the hardened base service."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict

from byte_mcp.errors import OXEvidenceError, OXProtocolError

from .models import AttemptOutcome, ProviderResult, ReviewState
from .protocol import parse_findings
from .service import _PROVIDER_ERRORS
from .service import OXReviewService as BaseOXReviewService


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

    def record_findings(
        self,
        review_id: str,
        findings: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        """Persist one immutable Byte-authored interpretation of a natural OX review."""
        review = self._load_prepared_review(review_id, expected_state=ReviewState.REVIEWED)
        if (
            isinstance(findings, str | bytes | bytearray)
            or not isinstance(findings, Sequence)
            or not findings
            or not all(isinstance(item, Mapping) for item in findings)
        ):
            raise OXProtocolError(attempt_outcome=AttemptOutcome.NOT_SENT.value)

        # Byte-authored interpretation is a new local input boundary. Apply the
        # same exact configured-credential rejection used by outbound/retrieval paths.
        self._reject_configured_credential(list(findings))

        attempts = review.get("attempts")
        if not isinstance(attempts, list):
            raise OXEvidenceError("review attempt evidence is malformed")

        source_attempt_id: str | None = None
        for attempt in attempts:
            if (
                not isinstance(attempt, Mapping)
                or attempt.get("outcome") != AttemptOutcome.COMPLETED.value
            ):
                continue
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str):
                continue
            identity = self._evidence.read_attempt_identity(review_id, attempt_id)
            if identity.get("phase") in {"initial", "initial-retry"}:
                source_attempt_id = attempt_id
                break
        if source_attempt_id is None:
            raise OXEvidenceError("completed initial OX attempt evidence is unavailable")

        thread = self._evidence.read_thread(review_id, "initial")
        source_response: str | None = None
        for message in thread:
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                source_response = content
                break
        if source_response is None:
            raise OXEvidenceError("source OX response evidence is unavailable")

        local_wire_payload = {
            "protocol_version": "ox-findings-v1",
            "findings": [dict(item) for item in findings],
        }
        validated = parse_findings(
            json.dumps(local_wire_payload, ensure_ascii=False, allow_nan=False),
            review_id,
        )
        payload = {
            "protocol_version": "byte-derived-findings-v1",
            "review_id": review_id,
            "source_attempt_id": source_attempt_id,
            "source_response_sha256": hashlib.sha256(
                source_response.encode("utf-8")
            ).hexdigest(),
            "derivation_authority": "byte",
            "derivation_provenance": "derived-from-ox-natural-review",
            "findings": [asdict(finding) for finding in validated],
        }
        self._evidence.persist_findings(review_id, payload)
        return payload
