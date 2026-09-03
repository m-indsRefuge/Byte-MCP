"""Natural-text OX review orchestration layered on the hardened base service."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict

from byte_mcp.errors import (
    OXApprovalError,
    OXEvidenceError,
    OXFindingValidationError,
    OXProtocolError,
)

from .models import AttemptOutcome, ProviderResult, ReviewState
from .protocol import build_initial_messages, parse_findings
from .service import _PROVIDER_ERRORS
from .service import OXReviewService as BaseOXReviewService


class OXReviewService(BaseOXReviewService):
    """Use natural OX review text while retaining base approval/evidence controls."""

    def transmit_review(self, review_id: str) -> dict[str, object]:
        """Send a fresh initial review or replay its local receipt without resending."""
        try:
            review = self._evidence.get_review(review_id)
        except OXEvidenceError as exc:
            raise OXApprovalError("review evidence is unavailable") from exc

        state = review.get("state")
        if state == ReviewState.PREPARED.value:
            return super().transmit_review(review_id)

        if state == ReviewState.TRANSMITTING.value:
            attempt = self._select_initial_receipt_attempt(review, current_only=True)
            if attempt is None:
                return super().transmit_review(review_id)
            return self._initial_review_receipt(
                review,
                attempt,
                review_text=None,
                usage=None,
                replayed=True,
                provider_request_performed=False,
            )

        if state == ReviewState.REVIEWED.value:
            attempt = self._select_initial_receipt_attempt(review, current_only=False)
            if attempt is None:
                raise OXEvidenceError("completed initial OX attempt evidence is unavailable")
            attempt_id = attempt["attempt_id"]
            if not isinstance(attempt_id, str):
                raise OXEvidenceError("initial OX attempt evidence is malformed")
            review_text = self._read_initial_review_text(review_id, attempt_id)
            return self._initial_review_receipt(
                review,
                attempt,
                review_text=review_text,
                usage=None,
                replayed=True,
                provider_request_performed=False,
            )

        return super().transmit_review(review_id)

    def _select_initial_receipt_attempt(
        self,
        review: Mapping[str, object],
        *,
        current_only: bool,
    ) -> Mapping[str, object] | None:
        review_id = review.get("review_id")
        attempts = review.get("attempts")
        if not isinstance(review_id, str) or not isinstance(attempts, list) or not attempts:
            raise OXEvidenceError("review attempt evidence is malformed")

        candidates = attempts[-1:] if current_only else list(reversed(attempts))
        for attempt in candidates:
            if not isinstance(attempt, Mapping):
                raise OXEvidenceError("review attempt evidence is malformed")
            attempt_id = attempt.get("attempt_id")
            manifest_sha256 = attempt.get("manifest_sha256")
            if not isinstance(attempt_id, str) or not isinstance(manifest_sha256, str):
                raise OXEvidenceError("review attempt evidence is malformed")
            identity = self._evidence.read_attempt_identity(review_id, attempt_id)
            if identity.get("phase") not in {"initial", "initial-retry"}:
                if current_only:
                    return None
                continue
            if (
                not current_only
                and attempt.get("outcome") != AttemptOutcome.COMPLETED.value
            ):
                continue
            return attempt

        return None

    def _read_initial_review_text(self, review_id: str, attempt_id: str) -> str:
        raw = self._evidence.read_provider_response(review_id, attempt_id)
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise OXEvidenceError("provider response evidence is malformed")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise OXEvidenceError("provider response evidence is malformed")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise OXEvidenceError("provider response evidence is malformed")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OXEvidenceError("provider response evidence is malformed")

        thread = self._evidence.read_thread(review_id, "initial")
        if not any(
            item.get("role") == "assistant" and item.get("content") == content
            for item in thread
        ):
            raise OXEvidenceError("provider response evidence does not match review thread")
        return content

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
        review_id = review.get("review_id")
        state = review.get("state")
        attempt_id = attempt.get("attempt_id")
        manifest_sha256 = attempt.get("manifest_sha256")
        if (
            not isinstance(review_id, str)
            or state not in {
                ReviewState.TRANSMITTING.value,
                ReviewState.REVIEWED.value,
            }
            or not isinstance(attempt_id, str)
            or not isinstance(manifest_sha256, str)
        ):
            raise OXEvidenceError("initial review receipt evidence is malformed")

        return {
            "review_id": review_id,
            "attempt_id": attempt_id,
            "state": state,
            "manifest_sha256": manifest_sha256,
            "review_text": review_text,
            "findings_recorded": self._evidence.findings_recorded(review_id),
            "usage": dict(usage) if usage is not None else None,
            "replayed": replayed,
            "provider_request_performed": provider_request_performed,
        }
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
        completed_review = self._evidence.get_review(review_id)
        return self._initial_review_receipt(
            completed_review,
            {
                "attempt_id": attempt_id,
                "manifest_sha256": manifest_sha256,
            },
            review_text=result.content,
            usage=asdict(result.usage) if result.usage is not None else None,
            replayed=False,
            provider_request_performed=True,
        )

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
        try:
            serialized_findings = json.dumps(
                local_wire_payload,
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise OXFindingValidationError(
                attempt_outcome=AttemptOutcome.NOT_SENT.value
            ) from None
        validated = parse_findings(serialized_findings, review_id)
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

    def run_targeted_revalidation(
        self,
        revalidation_id: str,
        finding_ids: Sequence[str],
    ) -> dict[str, object]:
        """Run a targeted natural review using only Byte-derived finding context."""
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
        try:
            result = self._client.complete(
                messages,
                json_mode=False,
                attempt_id=attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_revalidation_provider_error(
                revalidation_id,
                attempt_id,
                manifest_sha256,
                exc,
                phase=phase,
            )
            raise
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_revalidation_provider_error(
                revalidation_id,
                attempt_id,
                manifest_sha256,
                error,
                phase=phase,
            )
            raise error

        self._evidence.persist_revalidation_provider_response(
            revalidation_id,
            attempt_id,
            result.raw_response,
        )
        if not isinstance(result.content, str) or not result.content.strip():
            error = OXProtocolError(attempt_outcome=AttemptOutcome.REJECTED.value)
            self._record_revalidation_provider_error(
                revalidation_id,
                attempt_id,
                manifest_sha256,
                error,
                phase=phase,
            )
            raise error

        self._evidence.append_revalidation_thread_message(
            revalidation_id,
            thread_name,
            {"role": "assistant", "content": result.content},
        )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            error = OXProtocolError(attempt_outcome=AttemptOutcome.COMPLETED.value)
            self._record_revalidation_provider_error(
                revalidation_id,
                attempt_id,
                manifest_sha256,
                error,
                phase=phase,
            )
            raise error

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
            "state": completed["state"],
            "manifest_sha256": manifest_sha256,
            "response": result.content,
            "usage": asdict(result.usage) if result.usage is not None else None,
        }

    def _effective_revalidation(
        self,
        revalidation: Mapping[str, object],
    ) -> dict[str, object]:
        result = dict(revalidation)
        revalidation_id = result.get("revalidation_id")
        state = result.get("state")
        if not isinstance(revalidation_id, str):
            return result
        phase: str | None = None
        if state == ReviewState.BLIND_REVALIDATED.value:
            phase = "blind"
        elif state == ReviewState.REVALIDATED.value:
            phase = "targeted"
        if phase is not None and not self._validated_revalidation_phase_exists(
            revalidation_id,
            phase,
        ):
            result["state"] = ReviewState.FAILED.value
            result["protocol_status"] = "NATURAL_RESPONSE_EVIDENCE_INVALID"
        return result

    def _validated_revalidation_phase_exists(
        self,
        revalidation_id: str,
        phase: str,
    ) -> bool:
        if phase not in {"blind", "targeted"}:
            return False
        try:
            revalidation = self._evidence.get_revalidation(revalidation_id)
        except OXEvidenceError:
            return False
        review_id = revalidation.get("review_id")
        attempts = revalidation.get("attempts")
        if not isinstance(review_id, str) or not isinstance(attempts, list):
            return False
        thread_name = "blind-revalidation" if phase == "blind" else "targeted-revalidation"
        try:
            thread = self._evidence.read_revalidation_thread(revalidation_id, thread_name)
        except OXEvidenceError:
            return False

        assistant_contents = {
            content
            for message in thread
            if message.get("role") == "assistant"
            and isinstance((content := message.get("content")), str)
            and content.strip()
        }
        if not assistant_contents:
            return False

        for attempt in reversed(attempts):
            if (
                not isinstance(attempt, Mapping)
                or attempt.get("phase") != phase
                or attempt.get("outcome") != AttemptOutcome.COMPLETED.value
            ):
                continue
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str):
                continue
            response_path = (
                self._settings.evidence_root
                / "reviews"
                / review_id
                / "revalidations"
                / revalidation_id
                / "responses"
                / f"{attempt_id}.json"
            )
            try:
                raw = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, Mapping):
                continue
            choices = raw.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                continue
            choice = choices[0]
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip() and content in assistant_contents:
                return True
        return False

    def _require_validated_revalidation_phase(
        self,
        revalidation_id: str,
        phase: str,
    ) -> None:
        if not self._validated_revalidation_phase_exists(revalidation_id, phase):
            raise OXApprovalError("revalidation phase has no valid natural response evidence")
