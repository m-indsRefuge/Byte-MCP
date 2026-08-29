"""High-level OX review preparation and transmission orchestration."""

import hashlib
import json
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
from .models import AttemptOutcome, ProviderResult, ReviewState
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
        total_bytes = _message_bytes(messages)
        if total_bytes > self._settings.max_bundle_bytes:
            raise OXBundleError(
                f"review payload size {total_bytes} exceeds max_bundle_bytes "
                f"{self._settings.max_bundle_bytes}"
            )
        identity = {
            "repository": repository,
            "subsystem": subsystem,
            "target_commit": target_commit,
            "base_commit": base_commit,
            "objective": objective,
            "verification": _json_copy(list(verification)),
            "artifact_count": len(prepared.manifest.entries),
            "total_bytes": total_bytes,
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
        )
        return self._perform_attempt(
            review_id=review_id,
            attempt_id=attempt_id,
            manifest_sha256=prepared.manifest.manifest_sha256,
            messages=messages,
        )

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
            raise OXApprovalError("review state does not permit this transmission")
        return review

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
        manifest_sha256 = manifest.get("manifest_sha256")
        if prepared.manifest.manifest_sha256 != manifest_sha256:
            raise OXApprovalError("prepared manifest no longer matches approved scope")
        messages = build_initial_messages(prepared.packet, objective=identity["objective"])
        if _message_bytes(messages) != identity.get("total_bytes"):
            raise OXApprovalError("prepared outbound payload no longer matches approval")
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
    ) -> None:
        timestamp = datetime.now(UTC).isoformat()
        payload = {
            "attempt_id": attempt_id,
            "manifest_sha256": manifest_sha256,
            "history_sha256": _history_sha256(messages),
            "recorded_at": timestamp,
        }
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

    def _record_provider_error(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        error,
    ) -> None:
        outcome = error.attempt_outcome
        self._evidence.record_attempt_outcome(review_id, attempt_id, outcome)
        self._audit_attempt(review_id, attempt_id, manifest_sha256, outcome)

    def _record_not_sent(self, review_id: str, attempt_id: str) -> None:
        with suppress(OXEvidenceError):
            self._evidence.record_attempt_outcome(
                review_id,
                attempt_id,
                AttemptOutcome.NOT_SENT,
            )

    def _audit_attempt(
        self,
        review_id: str,
        attempt_id: str,
        manifest_sha256: str,
        attempt_outcome: str,
    ) -> None:
        self._audit.record(
            "ox_review",
            outcome="allowed" if attempt_outcome == AttemptOutcome.COMPLETED.value else "error",
            review_id=review_id,
            phase="transmit",
            attempt_id=attempt_id,
            manifest_sha256=manifest_sha256,
            attempt_outcome=attempt_outcome,
        )


def _json_copy(value: object) -> object:
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise OXBundleError("review evidence must be JSON serializable") from exc


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
