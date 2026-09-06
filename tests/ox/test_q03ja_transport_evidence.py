import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from byte_mcp.errors import OXEvidenceError, OXTransportFailureKind
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import AttemptOutcome, ProviderTransportObservation

MANIFEST_SHA256 = "a" * 64
RUNTIME_SESSION_ID = "a" * 32
Q03JA_FIELDS = (
    "response_headers_received",
    "response_headers_at",
    "response_headers_elapsed_ms",
    "http_status_code",
    "response_body_started",
    "first_body_at",
    "first_body_elapsed_ms",
    "last_body_at",
    "last_body_elapsed_ms",
    "decoded_body_bytes_received",
    "trust_env_enabled",
    "proxy_environment_present",
)


def _prepare(store: EvidenceStore) -> str:
    return store.persist_prepared_review(
        identity={"repository": "fixture", "subsystem": "validation", "objective": "review"},
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )


def _claim_started_review(store: EvidenceStore) -> tuple[str, str]:
    review_id = _prepare(store)
    attempt = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    attempt_id = str(attempt["attempt_id"])
    store.record_provider_request_started(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        phase="initial",
    )
    return review_id, attempt_id


def _observation(
    *,
    kind: OXTransportFailureKind | None = None,
) -> ProviderTransportObservation:
    now = datetime.now(UTC).isoformat()
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at=now,
        response_headers_elapsed_ms=0,
        http_status_code=200,
        response_body_started=True,
        first_body_at=now,
        first_body_elapsed_ms=0,
        last_body_at=now,
        last_body_elapsed_ms=0,
        decoded_body_bytes_received=128,
        provider_finished_at=now,
        elapsed_ms=0,
        transport_failure_kind=kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def test_q03ja_review_transport_metadata_round_trips_full_observation(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _claim_started_review(store)
    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.COMPLETED)
    value = _observation()

    store.record_provider_transport_metadata(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        observation=value,
    )

    attempt = store.get_review(review_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert attempt[field] == getattr(value, field)
    assert attempt["provider_finished_at"] == value.provider_finished_at
    assert attempt["elapsed_ms"] == value.elapsed_ms
    assert attempt["transport_failure_kind"] is None


def test_q03ja_legacy_transport_metadata_does_not_synthesize_new_fields(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _claim_started_review(store)
    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.OUTCOME_UNKNOWN)

    store.record_provider_transport_metadata(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        provider_finished_at=datetime.now(UTC).isoformat(),
        elapsed_ms=17,
        transport_failure_kind=OXTransportFailureKind.READ_ERROR,
    )

    attempt = store.get_review(review_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert field not in attempt
    assert attempt["elapsed_ms"] == 17
    assert attempt["transport_failure_kind"] == OXTransportFailureKind.READ_ERROR.value


@pytest.mark.parametrize(
    "changes",
    [
        {"response_headers_received": False},
        {"response_body_started": False},
        {"decoded_body_bytes_received": 0},
        {"first_body_elapsed_ms": 2, "response_headers_elapsed_ms": 3},
        {"last_body_elapsed_ms": 2, "elapsed_ms": 1},
        {"trust_env_enabled": 1},
        {"proxy_environment_present": "yes"},
        {"http_status_code": 999},
    ],
)
def test_q03ja_evidence_rejects_inconsistent_observations(tmp_path, changes) -> None:
    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _claim_started_review(store)
    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.COMPLETED)
    invalid = replace(_observation(), **changes)

    with pytest.raises(OXEvidenceError, match="transport observation"):
        store.record_provider_transport_metadata(
            review_id,
            attempt_id,
            runtime_session_id=RUNTIME_SESSION_ID,
            observation=invalid,
        )


def test_q03ja_reconstruction_rejects_partial_new_schema_event(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _claim_started_review(store)
    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.OUTCOME_UNKNOWN)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    event = {
        "attempt_id": attempt_id,
        "elapsed_ms": 1,
        "event_type": "PROVIDER_TRANSPORT_METADATA",
        "provider_finished_at": datetime.now(UTC).isoformat(),
        "response_headers_received": True,
        "runtime_session_id": RUNTIME_SESSION_ID,
        "transport_failure_kind": OXTransportFailureKind.READ_ERROR.value,
    }
    with events_path.open("ab") as handle:
        handle.write(
            json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        )

    with pytest.raises(OXEvidenceError, match="malformed"):
        store.get_review(review_id)


def test_q03ja_revalidation_metadata_is_symmetric_and_duplicate_rejected(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    revalidation_id = store.allocate_revalidation_id(review_id)
    store.persist_prepared_revalidation(
        review_id,
        revalidation_id,
        identity={
            "repository": "fixture",
            "subsystem": "validation",
            "target_commit": "c" * 40,
            "base_commit": "d" * 40,
        },
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "revalidation"},
    )
    attempt = store.claim_revalidation_transmission(
        revalidation_id,
        phase="blind",
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    attempt_id = str(attempt["attempt_id"])
    store.record_revalidation_provider_request_started(
        revalidation_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        phase="blind",
    )
    store.record_revalidation_attempt_outcome(
        revalidation_id,
        attempt_id,
        AttemptOutcome.COMPLETED,
    )
    value = _observation()

    store.record_revalidation_provider_transport_metadata(
        revalidation_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        observation=value,
    )

    reconstructed = store.get_revalidation(revalidation_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert reconstructed[field] == getattr(value, field)
    with pytest.raises(OXEvidenceError, match="already|duplicate"):
        store.record_revalidation_provider_transport_metadata(
            revalidation_id,
            attempt_id,
            runtime_session_id=RUNTIME_SESSION_ID,
            observation=value,
        )
