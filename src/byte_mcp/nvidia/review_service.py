"""Governed preparation, inspection, and exactly-once transmission for NVIDIA reviews."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from byte_mcp.providers import (
    PreparedProviderRequest,
    ProviderAttemptOutcome,
    ProviderAuthorization,
    ProviderTransmissionContext,
    ProviderTransportError,
    ProviderTransportObservation,
)
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity

from .chat import NvidiaChatResult, execute_prepared_nvidia_chat
from .errors import NvidiaChatError
from .review_evidence import NvidiaReviewEvidenceStore, NvidiaReviewSnapshot
from .review_packet import prepare_review_packet
from .review_protocol import (
    NvidiaReviewResultError,
    parse_nvidia_review_result,
    prepare_nvidia_review_request,
)
from .review_registry import NvidiaReviewGitRepository, NvidiaReviewRepositoryRegistry
from .review_settings import NvidiaReviewSettings
from .settings import NvidiaHostedSettings

_REVIEW_VIEWS = frozenset({"summary", "findings", "attempt", "manifest"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_timestamp(now: Callable[[], datetime]) -> str:
    value = now()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat()


def _allowed_review_paths(snapshot: NvidiaReviewSnapshot) -> frozenset[str]:
    try:
        packet = json.loads(snapshot.review_packet.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("persisted review packet is invalid") from None
    if not isinstance(packet, dict):
        raise ValueError("persisted review packet is invalid")
    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("persisted review packet artifacts are invalid")
    paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("persisted review packet artifacts are invalid")
        logical_path = artifact.get("logical_path")
        if not isinstance(logical_path, str):
            raise ValueError("persisted review packet artifacts are invalid")
        paths.add(logical_path)
    return frozenset(paths)


def _terminal_event(
    *,
    snapshot: NvidiaReviewSnapshot,
    observation: ProviderTransportObservation,
    attempt_outcome: ProviderAttemptOutcome,
    review_result_status: str,
    result_sha256: str | None,
    nvidia_failure_kind: str | None = None,
    transport_failure_kind: str | None = None,
    finish_reason: str | None = None,
    response_id: str | None = None,
    usage: object | None = None,
) -> dict[str, object]:
    manifest = snapshot.manifest
    provider_started_at = snapshot.provider_started_at
    if provider_started_at is None or observation.provider_started_at != provider_started_at:
        raise ValueError("provider observation start is inconsistent")
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
    completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
    total_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
    return {
        "event_type": "REVIEW_TERMINAL",
        "review_id": manifest.review_id,
        "request_sha256": manifest.request_sha256,
        "provider_id": manifest.provider_id,
        "model_id": manifest.model_id,
        "provider_started_at": provider_started_at,
        "provider_finished_at": observation.provider_finished_at,
        "attempt_outcome": attempt_outcome.value,
        "nvidia_failure_kind": nvidia_failure_kind,
        "transport_failure_kind": transport_failure_kind,
        "http_status_code": observation.http_status_code,
        "response_headers_received": observation.response_headers_received,
        "response_body_started": observation.response_body_started,
        "decoded_body_bytes_received": observation.decoded_body_bytes_received,
        "elapsed_ms": observation.elapsed_ms,
        "finish_reason": finish_reason,
        "response_id": response_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "review_result_status": review_result_status,
        "result_sha256": result_sha256,
        "recorded_at": observation.provider_finished_at,
    }


class NvidiaReviewService:
    """Prepare exact NVIDIA review identities and govern one-shot transmission."""

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

    async def transmit_review(
        self,
        review_id: str,
        *,
        expected_request_sha256: str,
        approve: bool,
        settings_loader: Callable[[], NvidiaHostedSettings] = NvidiaHostedSettings.load,
        executor: Callable[
            [PreparedProviderRequest, ProviderTransmissionContext, NvidiaHostedSettings],
            Awaitable[NvidiaChatResult],
        ] = execute_prepared_nvidia_chat,
        now: Callable[[], datetime] = _utc_now,
    ) -> dict[str, object]:
        """Transmit one exact prepared review after explicit approval, with zero retry."""

        with self._evidence_store.transmit_lock(review_id):
            snapshot = self._evidence_store.load(review_id)
            manifest = snapshot.manifest
            if approve is not True:
                raise ValueError("explicit review approval is required")
            if expected_request_sha256 != manifest.request_sha256:
                raise ValueError("expected request identity does not match prepared review")
            if snapshot.provider_started_at is not None:
                raise ValueError("review provider-start already exists")
            if snapshot.terminal_event is not None:
                raise ValueError("review attempt is already terminal")

            hosted_settings = settings_loader()
            if not isinstance(hosted_settings, NvidiaHostedSettings):
                raise ValueError("settings loader returned invalid NVIDIA hosted settings")
            if hosted_settings.api_key is None:
                raise ValueError("NVIDIA API key is not configured")
            ProviderAuthorization(f"Bearer {hosted_settings.api_key}")

            prepared_request = PreparedProviderRequest(
                provider_id=manifest.provider_id,
                method=manifest.method,
                target_origin=manifest.target_origin,
                endpoint_path=manifest.endpoint_path,
                model_id=manifest.model_id,
                body_bytes=snapshot.request_body,
                payload_sha256=manifest.payload_sha256,
                request_sha256=manifest.request_sha256,
            )
            validate_prepared_provider_request_integrity(prepared_request)

            request_sha256 = manifest.request_sha256
            if snapshot.authorized_at is None:
                self._evidence_store.append_authorized(
                    review_id,
                    request_sha256=request_sha256,
                    recorded_at=_utc_timestamp(now),
                )
            provider_started_at = _utc_timestamp(now)
            self._evidence_store.append_provider_start(
                review_id,
                request_sha256=request_sha256,
                recorded_at=provider_started_at,
            )
            context = ProviderTransmissionContext(
                provider_started_at=provider_started_at,
                expected_request_sha256=request_sha256,
            )
            started_snapshot = self._evidence_store.load(review_id)

            try:
                result = await executor(prepared_request, context, hosted_settings)
            except NvidiaChatError as error:
                if error.request_sha256 != request_sha256:
                    raise ValueError("NVIDIA error request identity is inconsistent") from None
                observation = error.transport_observation
                event = _terminal_event(
                    snapshot=started_snapshot,
                    observation=observation,
                    attempt_outcome=error.attempt_outcome,
                    review_result_status="NOT_AVAILABLE",
                    result_sha256=None,
                    nvidia_failure_kind=error.kind.value,
                    transport_failure_kind=(
                        observation.transport_failure_kind.value
                        if observation.transport_failure_kind is not None
                        else None
                    ),
                )
                self._evidence_store.append_terminal(review_id, event)
                raise
            except ProviderTransportError as error:
                event = _terminal_event(
                    snapshot=started_snapshot,
                    observation=error.transport_observation,
                    attempt_outcome=error.attempt_outcome,
                    review_result_status="NOT_AVAILABLE",
                    result_sha256=None,
                    transport_failure_kind=error.transport_failure_kind.value,
                )
                self._evidence_store.append_terminal(review_id, event)
                raise

            if not isinstance(result, NvidiaChatResult):
                raise ValueError("executor returned invalid NVIDIA chat result")
            if (
                result.request_sha256 != request_sha256
                or result.payload_sha256 != manifest.payload_sha256
                or result.model_id != manifest.model_id
            ):
                raise ValueError("NVIDIA result identity is inconsistent")

            try:
                parsed = parse_nvidia_review_result(
                    result.content,
                    _allowed_review_paths(started_snapshot),
                )
            except NvidiaReviewResultError:
                event = _terminal_event(
                    snapshot=started_snapshot,
                    observation=result.transport_observation,
                    attempt_outcome=ProviderAttemptOutcome.COMPLETED,
                    review_result_status="INVALID",
                    result_sha256=None,
                    finish_reason=result.finish_reason,
                    response_id=result.response_id,
                    usage=result.usage,
                )
                self._evidence_store.append_terminal(review_id, event)
                return {
                    "review_id": review_id,
                    "request_sha256": request_sha256,
                    "attempt_outcome": ProviderAttemptOutcome.COMPLETED.value,
                    "review_result_status": "INVALID",
                    "decision": None,
                }

            result_sha256 = self._evidence_store.persist_result(review_id, parsed)
            event = _terminal_event(
                snapshot=self._evidence_store.load(review_id),
                observation=result.transport_observation,
                attempt_outcome=ProviderAttemptOutcome.COMPLETED,
                review_result_status="VALID",
                result_sha256=result_sha256,
                finish_reason=result.finish_reason,
                response_id=result.response_id,
                usage=result.usage,
            )
            self._evidence_store.append_terminal(review_id, event)
            return {
                "review_id": review_id,
                "request_sha256": request_sha256,
                "attempt_outcome": ProviderAttemptOutcome.COMPLETED.value,
                "review_result_status": "VALID",
                "decision": parsed.decision,
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
