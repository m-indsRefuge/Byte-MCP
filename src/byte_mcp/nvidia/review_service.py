"""Provider-free preparation and read-only inspection for NVIDIA reviews."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .review_evidence import NvidiaReviewEvidenceStore, NvidiaReviewSnapshot
from .review_packet import prepare_review_packet
from .review_protocol import prepare_nvidia_review_request
from .review_registry import NvidiaReviewGitRepository, NvidiaReviewRepositoryRegistry
from .review_settings import NvidiaReviewSettings

_REVIEW_VIEWS = frozenset({"summary", "findings", "attempt", "manifest"})


class NvidiaReviewService:
    """Prepare exact NVIDIA review identities and expose bounded read-only views."""

    def __init__(
        self,
        registry: NvidiaReviewRepositoryRegistry,
        evidence_store: NvidiaReviewEvidenceStore,
    ) -> None:
        self._registry = registry
        self._evidence_store = evidence_store

    @classmethod
    def initialize(
        cls,
        repo_root: Path,
        *,
        evidence_store: NvidiaReviewEvidenceStore | None = None,
    ) -> NvidiaReviewService:
        settings = NvidiaReviewSettings.load(repo_root)
        registry = NvidiaReviewRepositoryRegistry.load(settings.repositories_file)
        store = evidence_store or NvidiaReviewEvidenceStore.from_environment()
        return cls(registry, store)

    def prepare_review(
        self,
        *,
        repository: str,
        subsystem: str,
        target_commit: str,
        base_commit: str,
        objective: str,
        verification: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        try:
            definition = self._registry.get(repository)
        except ValueError:
            raise ValueError(f"unknown repository alias: {repository}") from None
        try:
            subsystem_definition = definition.subsystems[subsystem]
        except KeyError:
            raise ValueError(f"unknown subsystem: {subsystem}") from None

        git_repository = NvidiaReviewGitRepository.open(definition)
        packet = prepare_review_packet(
            git_repository,
            subsystem_definition,
            base_commit,
            target_commit,
            objective,
            verification,
        )
        prepared_request = prepare_nvidia_review_request(packet)
        manifest = self._evidence_store.prepare(
            packet,
            prepared_request,
            prepared_at=datetime.now(UTC).isoformat(),
        )
        return {
            "review_id": manifest.review_id,
            "repository_alias": manifest.repository_alias,
            "subsystem_id": manifest.subsystem_id,
            "base_commit": manifest.base_commit,
            "target_commit": manifest.target_commit,
            "model_id": manifest.model_id,
            "packet_sha256": manifest.packet_sha256,
            "manifest_sha256": manifest.manifest_sha256,
            "payload_sha256": manifest.payload_sha256,
            "request_sha256": manifest.request_sha256,
            "prepared_at": manifest.prepared_at,
        }

    def get_review(self, review_id: str, *, view: str = "summary") -> dict[str, object]:
        if view not in _REVIEW_VIEWS:
            raise ValueError(f"unknown review view: {view}")
        snapshot = self._evidence_store.load(review_id)
        if view == "summary":
            return self._summary_view(snapshot)
        if view == "findings":
            return self._findings_view(snapshot)
        if view == "attempt":
            return self._attempt_view(snapshot)
        return asdict(snapshot.manifest)

    @staticmethod
    def _state(snapshot: NvidiaReviewSnapshot) -> str:
        if snapshot.terminal_event is not None:
            return "TERMINAL"
        if snapshot.provider_started_at is not None:
            return "STARTED"
        if snapshot.authorized_at is not None:
            return "AUTHORIZED"
        return "PREPARED"

    @classmethod
    def _summary_view(cls, snapshot: NvidiaReviewSnapshot) -> dict[str, object]:
        manifest = snapshot.manifest
        return {
            "review_id": manifest.review_id,
            "state": cls._state(snapshot),
            "repository_alias": manifest.repository_alias,
            "subsystem_id": manifest.subsystem_id,
            "base_commit": manifest.base_commit,
            "target_commit": manifest.target_commit,
            "model_id": manifest.model_id,
            "request_sha256": manifest.request_sha256,
            "prepared_at": manifest.prepared_at,
            "provider_started_at": snapshot.provider_started_at,
            "has_terminal_event": snapshot.terminal_event is not None,
        }

    @staticmethod
    def _findings_view(snapshot: NvidiaReviewSnapshot) -> dict[str, object]:
        terminal = snapshot.terminal_event
        result = snapshot.result
        result_status = None if terminal is None else terminal.get("review_result_status")
        if result is None:
            return {
                "review_id": snapshot.manifest.review_id,
                "review_result_status": result_status,
                "decision": None,
                "summary": None,
                "findings": [],
            }
        return {
            "review_id": snapshot.manifest.review_id,
            "review_result_status": result_status,
            "decision": result.decision,
            "summary": result.summary,
            "findings": [asdict(finding) for finding in result.findings],
        }

    @staticmethod
    def _attempt_view(snapshot: NvidiaReviewSnapshot) -> dict[str, object]:
        terminal = snapshot.terminal_event or {}
        return {
            "review_id": snapshot.manifest.review_id,
            "authorized_at": snapshot.authorized_at,
            "provider_started_at": snapshot.provider_started_at,
            "provider_finished_at": terminal.get("provider_finished_at"),
            "attempt_outcome": terminal.get("attempt_outcome"),
            "nvidia_failure_kind": terminal.get("nvidia_failure_kind"),
            "transport_failure_kind": terminal.get("transport_failure_kind"),
            "http_status_code": terminal.get("http_status_code"),
            "review_result_status": terminal.get("review_result_status"),
            "result_sha256": terminal.get("result_sha256"),
        }
