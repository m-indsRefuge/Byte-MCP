"""High-level OX review preparation, follow-up, and revalidation orchestration."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime

from byte_mcp.errors import (
    OXApprovalError,
    OXAuthenticationError,
    OXBundleError,
    OXConfigurationError,
    OXContextLimitError,
    OXEvidenceError,
    OXFindingValidationError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRepositoryError,
    OXRequestError,
    OXScopeError,
    OXTransportError,
)

from .bundles import BundleBuilder, PreparedBundle
from .evidence import EvidenceStore
from .models import AttemptOutcome, FindingStatus, ProviderResult, ReviewState
from .protocol import build_initial_messages, parse_findings
from .repositories import GitRepository, validate_ox_local_config
from .settings import OXSettings

_PROVIDER_ERRORS = (
    OXAuthenticationError,
    OXPermissionError,
    OXRequestError,
    OXContextLimitError,
    OXRateLimitError,
    OXQuotaError,
    OXProviderUnavailableError,
    OXTransportError,
    OXProtocolError,
)

_ALLOWED_FINDING_TRANSITIONS = {
    FindingStatus.RAISED: frozenset(
        {
            FindingStatus.REPRODUCED,
            FindingStatus.CONFIRMED,
            FindingStatus.DISPROVED,
            FindingStatus.DEFERRED,
            FindingStatus.UNRESOLVED,
        }
    ),
    FindingStatus.REPRODUCED: frozenset(
        {
            FindingStatus.CONFIRMED,
            FindingStatus.DISPROVED,
            FindingStatus.DEFERRED,
            FindingStatus.UNRESOLVED,
        }
    ),
    FindingStatus.CONFIRMED: frozenset(
        {FindingStatus.REMEDIATED, FindingStatus.DEFERRED, FindingStatus.UNRESOLVED}
    ),
    FindingStatus.DISPROVED: frozenset(),
    FindingStatus.DEFERRED: frozenset(
        {
            FindingStatus.REPRODUCED,
            FindingStatus.CONFIRMED,
            FindingStatus.DISPROVED,
            FindingStatus.UNRESOLVED,
        }
    ),
    FindingStatus.UNRESOLVED: frozenset(
        {
            FindingStatus.REPRODUCED,
            FindingStatus.CONFIRMED,
            FindingStatus.DISPROVED,
            FindingStatus.DEFERRED,
        }
    ),
    FindingStatus.REMEDIATED: frozenset(
        {FindingStatus.REVALIDATED, FindingStatus.CONFIRMED, FindingStatus.UNRESOLVED}
    ),
    FindingStatus.REVALIDATED: frozenset(),
}


class OXReviewService:
    """Prepare immutable review packets and perform explicitly approved attempts."""

    def __init__(self, settings: OXSettings, evidence: EvidenceStore, client, audit) -> None:
        self._settings = settings
        self._evidence = evidence
        self._client = client
        self._audit = audit

    def prepare_review(
        self,
        *,
        repository: str,
        subsystem: str,
        target_commit: str,
        base_commit: str | None,
        objective: str,
        verification: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        if not isinstance(objective, str) or not objective.strip():
            raise OXBundleError("review objective is required")
        prepared = self._build_bundle(
            repository=repository,
            subsystem=subsystem,
            target_commit=target_commit,
            base_commit=base_commit,
            verification=verification,
        )
        objective = objective.strip()
        messages = build_initial_messages(prepared.packet, objective=objective)
        self._reject_configured_credential(messages)
        total_bytes = _message_bytes(messages)
        if total_bytes > self._settings.max_bundle_bytes:
            raise OXBundleError(
                f"review payload size {total_bytes} exceeds max_bundle_bytes "
                f"{self._settings.max_bundle_bytes}"
            )
        payload_sha256 = _history_sha256(messages)
        identity = {
            "repository": repository,
            "subsystem": subsystem,
            "target_commit": target_commit,
            "base_commit": base_commit,
            "objective": objective,
            "verification": _json_copy(list(verification)),
            "artifact_count": len(prepared.manifest.entries),
            "total_bytes": total_bytes,
            "payload_sha256": payload_sha256,
            "model": "zai/glm-5.3-flash",
            "provider": "zai",
        }
        manifest = _json_copy(asdict(prepared.manifest))
        packet = json.loads(prepared.serialized_packet.decode("utf-8"))
        review_id = self._evidence.persist_prepared_review(
            identity=identity,
            manifest=manifest,
            bundle=packet,
        )
        proposal = {
            "review_id": review_id,
            **identity,
            "manifest_sha256": prepared.manifest.manifest_sha256,
            "transmitted": False,
        }
        self._audit.record(
            "ox_review",
            outcome="allowed",
            review_id=review_id,
            phase="prepare",
            manifest_sha256=prepared.manifest.manifest_sha256,
        )
        return proposal

    def transmit_review(self, review_id: str) -> dict[str, object]:
        review = self._load_prepared_review(review_id, expected_state=ReviewState.PREPARED)
        prepared, messages = self._rebuild_and_verify(review)
        try:
            attempt = self._evidence.claim_initial_transmission(
                review_id, prepared.manifest.manifest_sha256
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("review is not available for initial approval") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_attempt_identity(
            review_id,
            attempt_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="initial",
        )
        try:
            for message in messages:
                self._evidence.append_thread_message(review_id, "initial", message)
        except OXEvidenceError:
            self._record_not_sent(review_id, attempt_id)
            raise
        return self._perform_attempt(
            review_id=review_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
        )

    def retry_review(self, review_id: str, *, renewed_approval: bool) -> dict[str, object]:
        if not renewed_approval:
            raise OXApprovalError("retry requires renewed human approval")
        review = self._load_prepared_review(
            review_id,
            expected_state=(ReviewState.FAILED, ReviewState.OUTCOME_UNKNOWN),
        )
        prepared, messages = self._rebuild_and_verify(review)
        try:
            attempt = self._evidence.claim_retry_transmission(
                review_id,
                prepared.manifest.manifest_sha256,
                renewed_approval=True,
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("review is not eligible for retry") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_attempt_identity(
            review_id,
            attempt_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="initial-retry",
        )
        return self._perform_attempt(
            review_id=review_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
        )

    def continue_message(self, review_id: str, message: str) -> dict[str, object]:
        if not isinstance(message, str) or not message.strip():
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        review = self._load_prepared_review(review_id, expected_state=ReviewState.REVIEWED)
        manifest_sha256 = _manifest_digest(review)
        history = self._evidence.read_thread(review_id, "initial")
        messages = [*history, {"role": "user", "content": message.strip()}]
        self._reject_configured_credential(messages)
        self._enforce_message_bound(messages)
        try:
            attempt = self._evidence.claim_continuation_transmission(
                review_id, manifest_sha256
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("review is not available for continuation") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_attempt_identity(
            review_id,
            attempt_id,
            manifest_sha256,
            messages,
            phase="continuation",
        )
        try:
            self._evidence.append_thread_message(review_id, "initial", messages[-1])
        except OXEvidenceError:
            self._record_not_sent(review_id, attempt_id)
            raise
        return self._perform_text_attempt(
            review_id=review_id,
            attempt_id=attempt_id,
            manifest_sha256=manifest_sha256,
            messages=messages,
        )

    def retry_continuation(
        self,
        review_id: str,
        attempt_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, object]:
        if not renewed_approval:
            raise OXApprovalError("continuation retry requires renewed human approval")
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
        manifest_sha256 = _manifest_digest(review)
        try:
            attempt = self._evidence.claim_continuation_retry(
                review_id,
                manifest_sha256,
                attempt_id,
                renewed_approval=True,
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("continuation is not eligible for retry") from exc
        retry_attempt_id = attempt["attempt_id"]
        self._persist_attempt_identity(
            review_id,
            retry_attempt_id,
            manifest_sha256,
            messages,
            phase="continuation-retry",
            retry_of=attempt_id,
        )
        return self._perform_text_attempt(
            review_id=review_id,
            attempt_id=retry_attempt_id,
            manifest_sha256=manifest_sha256,
            messages=messages,
        )

    def adjudicate(
        self,
        review_id: str,
        events: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        self._load_prepared_review(review_id, expected_state=ReviewState.REVIEWED)
        if (
            isinstance(events, str | bytes | bytearray)
            or not isinstance(events, Sequence)
            or not events
        ):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        self._reject_configured_credential(list(events))
        findings_payload = self._evidence.read_findings(review_id)
        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        findings = {
            item.get("finding_id"): item
            for item in raw_findings
            if isinstance(item, Mapping) and isinstance(item.get("finding_id"), str)
        }
        existing = self._evidence.read_adjudications(review_id)
        current_status = {finding_id: FindingStatus.RAISED for finding_id in findings}
        for event in existing:
            finding_id = event.get("finding_id")
            status = event.get("status")
            if (
                isinstance(finding_id, str)
                and finding_id in current_status
                and isinstance(status, str)
            ):
                with suppress(ValueError):
                    current_status[finding_id] = FindingStatus(status)

        prepared_events: list[dict[str, object]] = []
        for offset, raw in enumerate(events, start=1):
            if not isinstance(raw, Mapping):
                raise OXProtocolError(attempt_outcome="NOT_SENT")
            allowed_fields = {
                "finding_id",
                "status",
                "evidence",
                "reasoning_summary",
                "remediation_commit",
            }
            if not set(raw).issubset(allowed_fields) or not {
                "finding_id",
                "status",
                "evidence",
                "reasoning_summary",
            }.issubset(raw):
                raise OXProtocolError(attempt_outcome="NOT_SENT")
            finding_id = raw.get("finding_id")
            status_value = raw.get("status")
            evidence = raw.get("evidence")
            reasoning_summary = raw.get("reasoning_summary")
            remediation_commit = raw.get("remediation_commit")
            if (
                not isinstance(finding_id, str)
                or finding_id not in findings
                or not isinstance(status_value, str)
                or not isinstance(evidence, str)
                or not evidence.strip()
                or not isinstance(reasoning_summary, str)
                or not reasoning_summary.strip()
            ):
                raise OXProtocolError(attempt_outcome="NOT_SENT")
            try:
                status = FindingStatus(status_value)
            except ValueError:
                raise OXProtocolError(attempt_outcome="NOT_SENT") from None
            previous = current_status[finding_id]
            if status not in _ALLOWED_FINDING_TRANSITIONS[previous]:
                raise OXProtocolError(attempt_outcome="NOT_SENT")
            if remediation_commit is not None and (
                not isinstance(remediation_commit, str)
                or re.fullmatch(r"[0-9a-f]{40}", remediation_commit) is None
            ):
                raise OXProtocolError(attempt_outcome="NOT_SENT")
            event = {
                "event_id": f"{review_id}-ADJ{len(existing) + offset:03d}",
                "finding_id": finding_id,
                "status": status.value,
                "evidence": evidence.strip(),
                "reasoning_summary": reasoning_summary.strip(),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            if remediation_commit is not None:
                event["remediation_commit"] = remediation_commit
            prepared_events.append(event)
            current_status[finding_id] = status

        for event in prepared_events:
            self._evidence.append_adjudication(review_id, event)
        self._audit.record(
            "ox_continue",
            outcome="allowed",
            review_id=review_id,
            phase="adjudicate",
            event_count=len(prepared_events),
        )
        return {
            "review_id": review_id,
            "adjudications": [*existing, *prepared_events],
        }

    def prepare_revalidation(
        self,
        review_id: str,
        *,
        target_commit: str,
        base_commit: str | None,
        verification: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        review = self._load_prepared_review(review_id, expected_state=ReviewState.REVIEWED)
        identity = review.get("identity")
        if not isinstance(identity, Mapping):
            raise OXApprovalError("review identity is unavailable for revalidation")
        repository = identity.get("repository")
        subsystem = identity.get("subsystem")
        if not isinstance(repository, str) or not isinstance(subsystem, str):
            raise OXApprovalError("review identity is unavailable for revalidation")
        prepared = self._build_bundle(
            repository=repository,
            subsystem=subsystem,
            target_commit=target_commit,
            base_commit=base_commit,
            verification=verification,
        )
        objective = (
            "Blindly validate the exact approved subsystem state at the new committed target."
        )
        messages = build_initial_messages(prepared.packet, objective=objective)
        self._reject_configured_credential(messages)
        total_bytes = _message_bytes(messages)
        self._enforce_message_bound(messages)
        payload_sha256 = _history_sha256(messages)
        revalidation_id = self._evidence.allocate_revalidation_id(review_id)
        revalidation_identity = {
            "repository": repository,
            "subsystem": subsystem,
            "target_commit": target_commit,
            "base_commit": base_commit,
            "objective": objective,
            "verification": _json_copy(list(verification)),
            "artifact_count": len(prepared.manifest.entries),
            "total_bytes": total_bytes,
            "payload_sha256": payload_sha256,
            "model": "zai/glm-5.3-flash",
            "provider": "zai",
        }
        manifest = _json_copy(asdict(prepared.manifest))
        packet = json.loads(prepared.serialized_packet.decode("utf-8"))
        self._evidence.persist_prepared_revalidation(
            review_id,
            revalidation_id,
            identity=revalidation_identity,
            manifest=manifest,
            bundle=packet,
        )
        self._audit.record(
            "ox_revalidate",
            outcome="allowed",
            review_id=review_id,
            revalidation_id=revalidation_id,
            phase="prepare",
            manifest_sha256=prepared.manifest.manifest_sha256,
        )
        return {
            "review_id": review_id,
            "revalidation_id": revalidation_id,
            **revalidation_identity,
            "manifest_sha256": prepared.manifest.manifest_sha256,
            "transmitted": False,
        }

    def transmit_blind_revalidation(self, revalidation_id: str) -> dict[str, object]:
        revalidation = self._load_revalidation(
            revalidation_id, expected_state=ReviewState.REVALIDATION_PREPARED
        )
        prepared, messages = self._rebuild_revalidation_and_verify(revalidation)
        try:
            attempt = self._evidence.claim_revalidation_transmission(
                revalidation_id, phase="blind"
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("revalidation is not available for blind approval") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_revalidation_attempt_identity(
            revalidation_id,
            attempt_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase="blind",
        )
        try:
            for message in messages:
                self._evidence.append_revalidation_thread_message(
                    revalidation_id, "blind-revalidation", message
                )
        except OXEvidenceError:
            self._record_revalidation_not_sent(revalidation_id, attempt_id)
            raise
        return self._perform_revalidation_attempt(
            revalidation_id=revalidation_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
            phase="blind",
            thread_name="blind-revalidation",
        )

    def retry_revalidation(
        self,
        revalidation_id: str,
        *,
        renewed_approval: bool,
    ) -> dict[str, object]:
        if not renewed_approval:
            raise OXApprovalError("revalidation retry requires renewed human approval")
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
            thread_name = "blind-revalidation"
        else:
            messages = self._evidence.read_revalidation_thread(
                revalidation_id, "targeted-revalidation"
            )
            thread_name = "targeted-revalidation"
        prior_identity = self._read_revalidation_attempt_identity(
            revalidation_id, previous_attempt_id
        )
        if (
            prior_identity.get("revalidation_id") != revalidation_id
            or prior_identity.get("phase") != phase
            or prior_identity.get("history_sha256") != _history_sha256(messages)
        ):
            raise OXApprovalError("revalidation history no longer matches failed attempt")
        try:
            attempt = self._evidence.claim_revalidation_retry(
                revalidation_id,
                previous_attempt_id,
                renewed_approval=True,
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("revalidation is not eligible for retry") from exc
        attempt_id = attempt["attempt_id"]
        self._persist_revalidation_attempt_identity(
            revalidation_id,
            attempt_id,
            prepared.manifest.manifest_sha256,
            messages,
            phase=str(phase),
            retry_of=previous_attempt_id,
        )
        return self._perform_revalidation_attempt(
            revalidation_id=revalidation_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
            phase=str(phase),
            thread_name=thread_name,
        )

    def run_targeted_revalidation(
        self,
        revalidation_id: str,
        finding_ids: Sequence[str],
    ) -> dict[str, object]:
        revalidation = self._load_revalidation(
            revalidation_id, expected_state=ReviewState.BLIND_REVALIDATED
        )
        self._require_validated_revalidation_phase(revalidation_id, "blind")
        if (
            isinstance(finding_ids, str | bytes | bytearray)
            or not isinstance(finding_ids, Sequence)
            or not finding_ids
            or not all(isinstance(finding_id, str) for finding_id in finding_ids)
        ):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        unique_finding_ids = set(finding_ids)
        if len(unique_finding_ids) != len(finding_ids):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        review_id = revalidation.get("review_id")
        if not isinstance(review_id, str):
            raise OXApprovalError("revalidation parent review is malformed")
        findings_payload = self._evidence.read_findings(review_id)
        raw_findings = findings_payload.get("findings")
        if not isinstance(raw_findings, list):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
        findings = {
            item.get("finding_id"): item
            for item in raw_findings
            if isinstance(item, Mapping) and isinstance(item.get("finding_id"), str)
        }
        if any(
            not isinstance(finding_id, str) or finding_id not in findings
            for finding_id in finding_ids
        ):
            raise OXProtocolError(attempt_outcome="NOT_SENT")
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
        self._enforce_message_bound(messages)
        try:
            attempt = self._evidence.claim_revalidation_transmission(
                revalidation_id, phase="targeted"
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
                    revalidation_id, "targeted-revalidation", message
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

    def get_review(self, review_id: str, *, view: str = "summary") -> dict[str, object]:
        if view == "summary":
            review = self._evidence.get_review(review_id)
            return {
                **review,
                "revalidations": [
                    self._effective_revalidation(item)
                    for item in self._evidence.list_revalidations(review_id)
                ],
            }
        if view == "findings":
            return {"review_id": review_id, **self._evidence.read_findings(review_id)}
        if view == "thread":
            return {
                "review_id": review_id,
                "messages": self._evidence.read_thread(review_id, "initial"),
            }
        if view == "manifest":
            return {"review_id": review_id, "manifest": self._evidence.read_manifest(review_id)}
        if view == "adjudication":
            return {
                "review_id": review_id,
                "adjudications": self._evidence.read_adjudications(review_id),
            }
        if view == "attempts":
            review = self._evidence.get_review(review_id)
            return {"review_id": review_id, "attempts": review["attempts"]}
        if view == "revalidation":
            return {
                "review_id": review_id,
                "revalidations": [
                    self._effective_revalidation(item)
                    for item in self._evidence.list_revalidations(review_id)
                ],
            }
        raise OXProtocolError(attempt_outcome="NOT_SENT")

    def _load_prepared_review(
        self,
        review_id: str,
        *,
        expected_state: ReviewState | tuple[ReviewState, ...],
    ) -> dict[str, object]:
        try:
            review = self._evidence.get_review(review_id)
        except OXEvidenceError as exc:
            raise OXApprovalError("review evidence is unavailable") from exc
        allowed = (
            {expected_state.value}
            if isinstance(expected_state, ReviewState)
            else {state.value for state in expected_state}
        )
        if review.get("state") not in allowed:
            raise OXApprovalError("review state does not permit this operation")
        return review

    def _load_revalidation(
        self,
        revalidation_id: str,
        *,
        expected_state: ReviewState | tuple[ReviewState, ...],
    ) -> dict[str, object]:
        try:
            revalidation = self._effective_revalidation(
                self._evidence.get_revalidation(revalidation_id)
            )
        except OXEvidenceError as exc:
            raise OXApprovalError("revalidation evidence is unavailable") from exc
        allowed = (
            {expected_state.value}
            if isinstance(expected_state, ReviewState)
            else {state.value for state in expected_state}
        )
        if revalidation.get("state") not in allowed:
            raise OXApprovalError("revalidation state does not permit this operation")
        return revalidation

    def _effective_revalidation(
        self, revalidation: Mapping[str, object]
    ) -> dict[str, object]:
        result = dict(revalidation)
        revalidation_id = result.get("revalidation_id")
        state = result.get("state")
        if not isinstance(revalidation_id, str):
            return result
        phase = None
        if state == ReviewState.BLIND_REVALIDATED.value:
            phase = "blind"
        elif state == ReviewState.REVALIDATED.value:
            phase = "targeted"
        if phase is not None and not self._validated_revalidation_phase_exists(
            revalidation_id, phase
        ):
            result["state"] = ReviewState.FAILED.value
            result["protocol_status"] = "FINDINGS_INVALID"
        return result

    def _validated_revalidation_phase_exists(self, revalidation_id: str, phase: str) -> bool:
        match = re.fullmatch(r"(OX-\d{6})-RV\d{3}", revalidation_id)
        if match is None or phase not in {"blind", "targeted"}:
            return False
        path = (
            self._settings.evidence_root
            / "reviews"
            / match.group(1)
            / "revalidations"
            / revalidation_id
            / "findings"
            / f"{phase}.json"
        )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(value, dict)
            and value.get("protocol_version") == "ox-findings-v1"
            and isinstance(value.get("findings"), list)
        )

    def _require_validated_revalidation_phase(
        self, revalidation_id: str, phase: str
    ) -> None:
        if not self._validated_revalidation_phase_exists(revalidation_id, phase):
            raise OXApprovalError("revalidation phase has no validated findings evidence")

    def _read_revalidation_attempt_identity(
        self, revalidation_id: str, attempt_id: str
    ) -> dict[str, object]:
        revalidation_match = re.fullmatch(r"(OX-\d{6})-RV\d{3}", revalidation_id)
        attempt_match = re.fullmatch(r"(OX-\d{6})-A\d{3}", attempt_id)
        if (
            revalidation_match is None
            or attempt_match is None
            or revalidation_match.group(1) != attempt_match.group(1)
        ):
            raise OXApprovalError("revalidation attempt identity is invalid")
        path = (
            self._settings.evidence_root
            / "reviews"
            / revalidation_match.group(1)
            / "revalidations"
            / revalidation_id
            / "attempts"
            / f"{attempt_id}.json"
        )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OXApprovalError("revalidation attempt evidence is unavailable") from exc
        if not isinstance(value, dict):
            raise OXApprovalError("revalidation attempt evidence is malformed")
        return value

    def _rebuild_and_verify(
        self, review: Mapping[str, object]
    ) -> tuple[PreparedBundle, list[dict[str, str]]]:
        identity = review.get("identity")
        manifest = review.get("manifest")
        if not isinstance(identity, Mapping) or not isinstance(manifest, Mapping):
            raise OXApprovalError("prepared review evidence is malformed")
        required = (
            "repository",
            "subsystem",
            "target_commit",
            "objective",
            "verification",
            "payload_sha256",
        )
        if any(key not in identity for key in required):
            raise OXApprovalError("prepared review identity is incomplete")
        verification = identity["verification"]
        if not isinstance(verification, list) or not all(
            isinstance(item, Mapping) for item in verification
        ):
            raise OXApprovalError("prepared verification evidence is malformed")
        base_commit = identity.get("base_commit")
        if base_commit is not None and not isinstance(base_commit, str):
            raise OXApprovalError("prepared base commit is malformed")
        values = (
            identity["repository"],
            identity["subsystem"],
            identity["target_commit"],
            identity["objective"],
        )
        if not all(isinstance(value, str) for value in values):
            raise OXApprovalError("prepared review identity is malformed")
        prepared = self._build_bundle(
            repository=identity["repository"],
            subsystem=identity["subsystem"],
            target_commit=identity["target_commit"],
            base_commit=base_commit,
            verification=verification,
        )
        persisted_manifest = _json_copy(dict(manifest))
        expected_manifest = _json_copy(asdict(prepared.manifest))
        if persisted_manifest != expected_manifest:
            raise OXApprovalError("prepared manifest no longer matches approved scope")
        messages = build_initial_messages(prepared.packet, objective=identity["objective"])
        self._reject_configured_credential(messages)
        if _message_bytes(messages) != identity.get("total_bytes"):
            raise OXApprovalError("prepared outbound payload no longer matches approval")
        if _history_sha256(messages) != identity.get("payload_sha256"):
            raise OXApprovalError("prepared outbound payload no longer matches approval")
        if identity.get("artifact_count") != len(prepared.manifest.entries):
            raise OXApprovalError("prepared artifact count no longer matches approval")
        return prepared, messages

    def _rebuild_revalidation_and_verify(
        self, revalidation: Mapping[str, object]
    ) -> tuple[PreparedBundle, list[dict[str, str]]]:
        identity = revalidation.get("identity")
        manifest = revalidation.get("manifest")
        if not isinstance(identity, Mapping) or not isinstance(manifest, Mapping):
            raise OXApprovalError("prepared revalidation evidence is malformed")
        required = (
            "repository",
            "subsystem",
            "target_commit",
            "objective",
            "verification",
            "payload_sha256",
        )
        if any(key not in identity for key in required):
            raise OXApprovalError("prepared revalidation identity is incomplete")
        verification = identity["verification"]
        if not isinstance(verification, list) or not all(
            isinstance(item, Mapping) for item in verification
        ):
            raise OXApprovalError("prepared revalidation verification is malformed")
        base_commit = identity.get("base_commit")
        if base_commit is not None and not isinstance(base_commit, str):
            raise OXApprovalError("prepared revalidation base commit is malformed")
        values = (
            identity["repository"],
            identity["subsystem"],
            identity["target_commit"],
            identity["objective"],
        )
        if not all(isinstance(value, str) for value in values):
            raise OXApprovalError("prepared revalidation identity is malformed")
        prepared = self._build_bundle(
            repository=identity["repository"],
            subsystem=identity["subsystem"],
            target_commit=identity["target_commit"],
            base_commit=base_commit,
            verification=verification,
        )
        persisted_manifest = _json_copy(dict(manifest))
        expected_manifest = _json_copy(asdict(prepared.manifest))
        if persisted_manifest != expected_manifest:
            raise OXApprovalError("revalidation manifest no longer matches approved scope")
        messages = build_initial_messages(prepared.packet, objective=identity["objective"])
        self._reject_configured_credential(messages)
        if _message_bytes(messages) != identity.get("total_bytes"):
            raise OXApprovalError("revalidation outbound payload no longer matches approval")
        if _history_sha256(messages) != identity.get("payload_sha256"):
            raise OXApprovalError("revalidation outbound payload no longer matches approval")
        if identity.get("artifact_count") != len(prepared.manifest.entries):
            raise OXApprovalError("revalidation artifact count no longer matches approval")
        return prepared, messages

    def _build_bundle(
        self,
        *,
        repository: str,
        subsystem: str,
        target_commit: str,
        base_commit: str | None,
        verification: Sequence[Mapping[str, object]],
    ) -> PreparedBundle:
        try:
            registry = validate_ox_local_config(self._settings)
        except ValueError as exc:
            raise OXConfigurationError("OX repository configuration is invalid") from exc
        try:
            definition = registry.get(repository)
        except ValueError as exc:
            raise OXRepositoryError("unknown approved OX repository") from exc
        try:
            subsystem_definition = definition.subsystems[subsystem]
        except KeyError as exc:
            raise OXScopeError("unknown approved OX subsystem") from exc
        try:
            git_repository = GitRepository.open(definition)
            git_repository.resolve_commit(target_commit)
            if base_commit is not None:
                git_repository.resolve_commit(base_commit)
        except (OSError, ValueError) as exc:
            raise OXRepositoryError("requested committed repository state is unavailable") from exc
        return BundleBuilder(
            git_repository,
            max_bundle_bytes=self._settings.max_bundle_bytes,
        ).prepare(
            subsystem_definition,
            target_commit,
            base_commit,
            verification,
        )

    def _persist_attempt_identity(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
        *,
        phase: str,
        retry_of: str | None = None,
    ) -> None:
        payload = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "history_sha256": _history_sha256(messages),
            "phase": phase,
            "recorded_at": datetime.now(UTC).isoformat(),
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
        try:
            self._evidence._write_immutable_json(path, payload)
        except OXEvidenceError:
            self._record_not_sent(review_id, attempt_id)
            raise

    def _persist_revalidation_attempt_identity(
        self,
        revalidation_id: str,
        attempt_id: str,
        manifest_sha256: str,
        messages: Sequence[Mapping[str, object]],
        *,
        phase: str,
        retry_of: str | None = None,
    ) -> None:
        payload = {
            "attempt_id": attempt_id,
            "revalidation_id": revalidation_id,
            "manifest_sha256": manifest_sha256,
            "history_sha256": _history_sha256(messages),
            "phase": phase,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        if retry_of is not None:
            payload["retry_of"] = retry_of
        try:
            self._evidence.persist_revalidation_attempt_identity(
                revalidation_id, attempt_id, payload
            )
        except OXEvidenceError:
            self._record_revalidation_not_sent(revalidation_id, attempt_id)
            raise

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
                json_mode=True,
                attempt_id=attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_provider_error(review_id, attempt_id, manifest_sha256, exc)
            raise
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome="COMPLETED")
            self._record_provider_error(review_id, attempt_id, manifest_sha256, error)
            raise error
        self._evidence.persist_provider_response(review_id, attempt_id, result.raw_response)
        self._evidence.append_thread_message(
            review_id,
            "initial",
            {"role": "assistant", "content": result.content},
        )
        try:
            findings = parse_findings(result.content, review_id)
        except OXFindingValidationError:
            self._persist_invalid_findings(review_id, attempt_id, result.content)
            self._evidence.record_attempt_outcome(
                review_id, attempt_id, AttemptOutcome.COMPLETED
            )
            self._audit_attempt(
                review_id,
                attempt_id,
                manifest_sha256,
                AttemptOutcome.COMPLETED.value,
            )
            raise
        findings_payload = {
            "protocol_version": "ox-findings-v1",
            "findings": [asdict(finding) for finding in findings],
        }
        self._evidence.persist_findings(review_id, findings_payload)
        self._evidence.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.COMPLETED)
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
            "findings": [asdict(finding) for finding in findings],
            "usage": asdict(result.usage) if result.usage is not None else None,
        }

    def _perform_text_attempt(
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
            self._record_provider_error(
                review_id,
                attempt_id,
                manifest_sha256,
                exc,
                action="ox_continue",
                phase="message",
            )
            raise
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome="COMPLETED")
            self._record_provider_error(
                review_id,
                attempt_id,
                manifest_sha256,
                error,
                action="ox_continue",
                phase="message",
            )
            raise error
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
            "response": result.content,
            "usage": asdict(result.usage) if result.usage is not None else None,
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
        try:
            result = self._client.complete(
                messages,
                json_mode=True,
                attempt_id=attempt_id,
            )
        except _PROVIDER_ERRORS as exc:
            self._record_revalidation_provider_error(
                revalidation_id, attempt_id, manifest_sha256, exc, phase=phase
            )
            raise
        if not isinstance(result, ProviderResult) or not isinstance(result.raw_response, dict):
            error = OXProtocolError(attempt_outcome="COMPLETED")
            self._record_revalidation_provider_error(
                revalidation_id, attempt_id, manifest_sha256, error, phase=phase
            )
            raise error
        self._evidence.persist_revalidation_provider_response(
            revalidation_id, attempt_id, result.raw_response
        )
        self._evidence.append_revalidation_thread_message(
            revalidation_id,
            thread_name,
            {"role": "assistant", "content": result.content},
        )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        review_id = revalidation["review_id"]
        try:
            findings = parse_findings(result.content, review_id)
        except OXFindingValidationError:
            self._persist_invalid_revalidation_findings(
                review_id, revalidation_id, attempt_id, phase, result.content
            )
            self._evidence.record_revalidation_attempt_outcome(
                revalidation_id, attempt_id, AttemptOutcome.COMPLETED
            )
            self._audit_attempt(
                review_id,
                attempt_id,
                manifest_sha256,
                AttemptOutcome.COMPLETED.value,
                action="ox_revalidate",
                phase=f"{phase}-protocol-failure",
                revalidation_id=revalidation_id,
            )
            raise
        self._evidence.persist_revalidation_findings(
            revalidation_id,
            phase,
            {
                "protocol_version": "ox-findings-v1",
                "findings": [asdict(finding) for finding in findings],
            },
        )
        self._evidence.record_revalidation_attempt_outcome(
            revalidation_id, attempt_id, AttemptOutcome.COMPLETED
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
            "findings": [asdict(finding) for finding in findings],
            "usage": asdict(result.usage) if result.usage is not None else None,
        }

    def _persist_invalid_findings(self, review_id: str, attempt_id: str, content: str) -> None:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = (
            self._settings.evidence_root
            / "reviews"
            / review_id
            / "findings"
            / f"FINDINGS_INVALID-{attempt_id}.json"
        )
        self._evidence._write_immutable_json(
            path,
            {
                "attempt_id": attempt_id,
                "validation": "FINDINGS_INVALID",
                "raw_content_sha256": digest,
            },
        )

    def _persist_invalid_revalidation_findings(
        self,
        review_id: str,
        revalidation_id: str,
        attempt_id: str,
        phase: str,
        content: str,
    ) -> None:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = (
            self._settings.evidence_root
            / "reviews"
            / review_id
            / "revalidations"
            / revalidation_id
            / "findings"
            / f"FINDINGS_INVALID-{attempt_id}.json"
        )
        self._evidence._write_immutable_json(
            path,
            {
                "attempt_id": attempt_id,
                "phase": phase,
                "validation": "FINDINGS_INVALID",
                "raw_content_sha256": digest,
            },
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
            revalidation_id, attempt_id, outcome
        )
        revalidation = self._evidence.get_revalidation(revalidation_id)
        self._audit_attempt(
            revalidation["review_id"],
            attempt_id,
            manifest_sha256,
            outcome,
            action="ox_revalidate",
            phase=phase,
            revalidation_id=revalidation_id,
        )

    def _record_not_sent(self, review_id: str, attempt_id: str) -> None:
        with suppress(OXEvidenceError):
            self._evidence.record_attempt_outcome(
                review_id,
                attempt_id,
                AttemptOutcome.NOT_SENT,
            )

    def _record_revalidation_not_sent(self, revalidation_id: str, attempt_id: str) -> None:
        with suppress(OXEvidenceError):
            self._evidence.record_revalidation_attempt_outcome(
                revalidation_id,
                attempt_id,
                AttemptOutcome.NOT_SENT,
            )

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
    ) -> None:
        fields: dict[str, object] = {
            "review_id": review_id,
            "phase": phase,
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "attempt_outcome": attempt_outcome,
        }
        if revalidation_id is not None:
            fields["revalidation_id"] = revalidation_id
        self._audit.record(
            action,
            outcome="allowed" if attempt_outcome == AttemptOutcome.COMPLETED.value else "error",
            **fields,
        )

    def _enforce_message_bound(self, messages: Sequence[Mapping[str, object]]) -> None:
        total_bytes = _message_bytes(messages)
        if total_bytes > self._settings.max_bundle_bytes:
            raise OXBundleError(
                f"outbound message size {total_bytes} exceeds max_bundle_bytes "
                f"{self._settings.max_bundle_bytes}"
            )

    def _reject_configured_credential(self, value: object) -> None:
        api_key = self._settings.api_key
        if not api_key:
            return
        try:
            payload = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            )
        except (TypeError, ValueError, RecursionError):
            return
        if api_key in payload:
            raise OXBundleError("review material contains the configured gateway credential")


def _json_copy(value: object) -> object:
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise OXBundleError("review evidence must be JSON serializable") from exc


def _manifest_digest(review: Mapping[str, object]) -> str:
    manifest = review.get("manifest")
    if not isinstance(manifest, Mapping):
        raise OXApprovalError("review manifest evidence is unavailable")
    digest = manifest.get("manifest_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise OXApprovalError("review manifest digest is malformed")
    return digest


def _history_sha256(messages: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(
        list(messages),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _message_bytes(messages: Sequence[Mapping[str, object]]) -> int:
    return len(
        json.dumps(
            list(messages),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
