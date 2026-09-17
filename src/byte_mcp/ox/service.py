"""Synchronous orchestration for one authorized OX code review lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

import httpx

from byte_mcp.errors import OXBundleError, OXConfigurationError, OXEvidenceError, OXProtocolError
from byte_mcp.ox.client import execute_ox_transport, extract_ox_review_text
from byte_mcp.ox.evidence import OXEvidenceStore
from byte_mcp.ox.models import OXPreparedReview, OXReviewMode, OXReviewState
from byte_mcp.ox.packet import (
    build_review_packet,
    prepare_ox_request,
    validate_provider_bound_safety,
)
from byte_mcp.ox.scope import OXScopeResolver
from byte_mcp.ox.settings import OX_MODEL_ID, OXSettings
from byte_mcp.ox.snapshot import freeze_snapshot
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransmissionContext,
    ProviderTransportError,
)
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _terminal_metadata(
    *,
    state: OXReviewState,
    attempt_outcome: ProviderAttemptOutcome,
    provider_started_at: str,
    provider_finished_at: str,
) -> dict[str, object]:
    return {
        "state": state.value,
        "provider_started_at": provider_started_at,
        "provider_finished_at": provider_finished_at,
        "attempt_outcome": attempt_outcome.value,
    }


class OXReviewService:
    """Own exactly one synchronous OX review from snapshot through durable projection."""

    def __init__(
        self,
        scope_resolver: OXScopeResolver,
        evidence_store: OXEvidenceStore,
        settings_loader: Callable[[], OXSettings],
    ) -> None:
        if not isinstance(scope_resolver, OXScopeResolver):
            raise TypeError("scope_resolver must be an OXScopeResolver")
        if not isinstance(evidence_store, OXEvidenceStore):
            raise TypeError("evidence_store must be an OXEvidenceStore")
        if not callable(settings_loader):
            raise TypeError("settings_loader must be callable")
        self._scope_resolver = scope_resolver
        self._evidence_store = evidence_store
        self._settings_loader = settings_loader

    async def review(
        self,
        *,
        repository: str,
        mode: str,
        paths: Sequence[str] | None,
        objective: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> dict[str, object]:
        review_mode = self._parse_mode(mode)
        requested_paths = self._normalize_paths(paths)
        resolved_repository, scope = self._scope_resolver.resolve_scope(
            repository,
            review_mode,
            requested_paths,
            objective,
        )
        snapshot = freeze_snapshot(resolved_repository, scope)
        packet_bytes = build_review_packet(scope, snapshot)
        prepared_request = prepare_ox_request(packet_bytes)

        review_id = self._evidence_store.allocate_review_id()
        try:
            prepared = OXPreparedReview(
                review_id=review_id,
                scope=scope,
                snapshot=snapshot,
                packet_bytes=packet_bytes,
                packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
                prepared_request=prepared_request,
            )
        except ValueError:
            raise OXBundleError("OX prepared review is invalid.") from None
        self._evidence_store.persist_prepared(prepared)

        settings = self._load_settings()
        api_key = settings.api_key
        if api_key is None or not api_key.strip():
            raise OXConfigurationError("OX provider credential is not configured.")

        try:
            validate_prepared_provider_request_integrity(prepared_request)
        except ValueError:
            raise OXBundleError("OX prepared request integrity is invalid.") from None
        validate_provider_bound_safety(
            packet_bytes,
            prepared_request.body_bytes,
            exact_credential=api_key,
        )

        provider_started_at = _utc_now()
        claimed = self._evidence_store.claim_send(
            review_id,
            prepared_request.request_sha256,
            provider_started_at,
        )
        if not claimed:
            return self.get_review(review_id)

        transmission_context = ProviderTransmissionContext(
            provider_started_at=provider_started_at,
            expected_request_sha256=prepared_request.request_sha256,
        )
        try:
            response = await execute_ox_transport(
                prepared_request,
                transmission_context,
                api_key=api_key,
                transport=transport,
            )
        except ProviderTransportError as exc:
            observation = exc.transport_observation
            state = (
                OXReviewState.FAILED
                if exc.attempt_outcome is ProviderAttemptOutcome.NOT_SENT
                else OXReviewState.OUTCOME_UNKNOWN
            )
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=state,
                    attempt_outcome=exc.attempt_outcome,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )

        observation = response.observation
        try:
            self._evidence_store.persist_response(review_id, response.body)
        except OXEvidenceError:
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=OXReviewState.OUTCOME_UNKNOWN,
                    attempt_outcome=ProviderAttemptOutcome.OUTCOME_UNKNOWN,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )

        if response.outcome is ProviderAttemptOutcome.REJECTED:
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=OXReviewState.FAILED,
                    attempt_outcome=ProviderAttemptOutcome.REJECTED,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )
        if response.outcome is not ProviderAttemptOutcome.COMPLETED:
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=OXReviewState.OUTCOME_UNKNOWN,
                    attempt_outcome=ProviderAttemptOutcome.OUTCOME_UNKNOWN,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )

        try:
            review_text = extract_ox_review_text(response.body)
        except OXProtocolError:
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=OXReviewState.FAILED,
                    attempt_outcome=ProviderAttemptOutcome.COMPLETED,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )

        try:
            self._evidence_store.persist_review_text(review_id, review_text)
        except OXEvidenceError:
            return self._finalize_and_project(
                review_id,
                _terminal_metadata(
                    state=OXReviewState.OUTCOME_UNKNOWN,
                    attempt_outcome=ProviderAttemptOutcome.OUTCOME_UNKNOWN,
                    provider_started_at=observation.provider_started_at,
                    provider_finished_at=observation.provider_finished_at,
                ),
            )

        return self._finalize_and_project(
            review_id,
            _terminal_metadata(
                state=OXReviewState.COMPLETED,
                attempt_outcome=ProviderAttemptOutcome.COMPLETED,
                provider_started_at=observation.provider_started_at,
                provider_finished_at=observation.provider_finished_at,
            ),
        )

    def get_review(self, review_id: str) -> dict[str, object]:
        evidence = self._evidence_store.get(review_id)
        return {
            "review_id": evidence.review_id,
            "state": evidence.state.value,
            "repository": evidence.repository,
            "mode": evidence.mode.value,
            "scope": {
                "repository": evidence.repository,
                "mode": evidence.mode.value,
            },
            "snapshot_sha256": evidence.snapshot_sha256,
            "request_sha256": evidence.request_sha256,
            "provider": "ox",
            "model": OX_MODEL_ID,
            "provider_started_at": evidence.provider_started_at,
            "provider_finished_at": evidence.provider_finished_at,
            "attempt_outcome": evidence.attempt_outcome,
            "response_bytes": evidence.response_bytes,
            "review_text": evidence.review_text,
        }

    def _load_settings(self) -> OXSettings:
        settings = self._settings_loader()
        if not isinstance(settings, OXSettings):
            raise OXConfigurationError("OX provider settings are invalid.")
        return settings

    def _finalize_and_project(
        self,
        review_id: str,
        terminal_metadata: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            self._evidence_store.finalize(review_id, terminal_metadata)
        except OXEvidenceError:
            pass
        return self.get_review(review_id)

    @staticmethod
    def _parse_mode(mode: str) -> OXReviewMode:
        try:
            return OXReviewMode(mode)
        except (TypeError, ValueError):
            from byte_mcp.errors import OXScopeError

            raise OXScopeError("OX review mode is invalid.") from None

    @staticmethod
    def _normalize_paths(paths: Sequence[str] | None) -> tuple[str, ...]:
        if paths is None:
            return ()
        if isinstance(paths, (str, bytes)):
            from byte_mcp.errors import OXScopeError

            raise OXScopeError("OX review paths are invalid.")
        return tuple(paths)
