import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from byte_mcp.errors import (
    OXEvidenceError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXTransportFailureKind,
)
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import (
    AttemptOutcome,
    ProviderResult,
    ProviderTransportObservation,
    ProviderUsage,
    ReviewState,
)
from tests.ox.q03h_initial_support import (
    FakeAudit,
    make_natural_service,
    prepare,
    wait_for_lane_release,
    wait_for_state,
)
from tests.ox.q03h_revalidation_support import (
    establish_initial_review,
    make_revalidation_service,
    prepare_revalidation,
    wait_for_lane_release as wait_for_revalidation_lane_release,
    wait_for_revalidation_state,
)

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


def _observed_result(attempt_id: str, content: str = "Natural OX engineering review.") -> ProviderResult:
    raw = {
        "id": f"response-{attempt_id}",
        "model": "zai/glm-5.3-flash",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }
    return ProviderResult(
        content=content,
        usage=ProviderUsage(3, 4, 7, 0),
        response_id=str(raw["id"]),
        model=str(raw["model"]),
        raw_response=raw,
        transport_observation=_observation(),
    )


class ObservedNaturalClient:
    def __init__(self, order: list[str] | None = None, *, content: str | None = None) -> None:
        self.order = order
        self.content = content
        self.calls: list[str] = []

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        if self.order is not None:
            self.order.append("client.complete")
        self.calls.append(attempt_id)
        content = self.content if self.content is not None else "Natural OX engineering review."
        return _observed_result(attempt_id, content)


class ObservedErrorClient:
    def __init__(self, error_type, order: list[str]) -> None:
        self.error_type = error_type
        self.order = order

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.order.append("client.complete")
        outcome = "COMPLETED" if self.error_type is OXProtocolError else "REJECTED"
        raise self.error_type(
            attempt_outcome=outcome,
            transport_observation=_observation(),
        )


class OrderedEvidenceStore(EvidenceStore):
    def __init__(self, root, order: list[str]) -> None:
        super().__init__(root)
        self.order = order

    def record_provider_request_started(self, *args, **kwargs) -> None:
        self.order.append("provider-start")
        super().record_provider_request_started(*args, **kwargs)

    def persist_provider_response(self, *args, **kwargs) -> None:
        self.order.append("raw-response")
        super().persist_provider_response(*args, **kwargs)

    def append_thread_message(self, review_id, thread_name, message) -> None:
        if message.get("role") == "assistant":
            self.order.append("assistant-thread")
        super().append_thread_message(review_id, thread_name, message)

    def record_attempt_outcome(self, review_id, attempt_id, outcome) -> None:
        value = outcome.value if isinstance(outcome, AttemptOutcome) else outcome
        self.order.append(f"outcome:{value}")
        super().record_attempt_outcome(review_id, attempt_id, outcome)

    def record_provider_transport_metadata(self, *args, **kwargs) -> None:
        self.order.append("transport-metadata")
        super().record_provider_transport_metadata(*args, **kwargs)


class OrderedAudit(FakeAudit):
    _TERMINAL_PHASES = frozenset(
        {
            "transmit",
            "message",
            "retry",
            "blind",
            "targeted",
            "blind-protocol-failure",
            "targeted-protocol-failure",
        }
    )

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self.order = order

    def record(self, action: str, *, outcome: str = "allowed", **fields: object) -> None:
        if fields.get("phase") in self._TERMINAL_PHASES:
            self.order.append("audit")
        super().record(action, outcome=outcome, **fields)


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


def _make_ordered_natural_service(tmp_path, client, order: list[str]):
    store = OrderedEvidenceStore(tmp_path / "evidence", order)
    audit = OrderedAudit(order)
    return make_natural_service(tmp_path, client, evidence=store, audit=audit)


def test_q03ja_natural_initial_records_observation_after_outcome_before_audit(tmp_path) -> None:
    order: list[str] = []
    client = ObservedNaturalClient(order)
    service, store, jobs, base, target = _make_ordered_natural_service(tmp_path, client, order)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    order.clear()

    service.transmit_review(review_id)
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(jobs)

    assert order == [
        "provider-start",
        "client.complete",
        "raw-response",
        "assistant-thread",
        "outcome:COMPLETED",
        "transport-metadata",
        "audit",
    ]
    attempt = store.get_review(review_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert field in attempt


def test_q03ja_continuation_records_observation_after_outcome_before_audit(tmp_path) -> None:
    order: list[str] = []
    client = ObservedNaturalClient(order)
    service, store, jobs, base, target = _make_ordered_natural_service(tmp_path, client, order)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    service.transmit_review(review_id)
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(jobs)
    order.clear()

    service.continue_message(review_id, "Continue the bounded review.")
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(jobs)

    assert order == [
        "provider-start",
        "client.complete",
        "raw-response",
        "assistant-thread",
        "outcome:COMPLETED",
        "transport-metadata",
        "audit",
    ]
    attempt = store.get_review(review_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert field in attempt


@pytest.mark.parametrize(
    ("error_type", "terminal_state", "expected_outcome"),
    [
        (OXProtocolError, ReviewState.REVIEWED, AttemptOutcome.COMPLETED.value),
        (OXProviderUnavailableError, ReviewState.FAILED, AttemptOutcome.REJECTED.value),
    ],
)
def test_q03ja_observed_provider_errors_record_outcome_then_metadata_then_audit(
    tmp_path,
    error_type,
    terminal_state: ReviewState,
    expected_outcome: str,
) -> None:
    order: list[str] = []
    client = ObservedErrorClient(error_type, order)
    service, store, jobs, base, target = _make_ordered_natural_service(tmp_path, client, order)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    order.clear()

    service.transmit_review(review_id)
    wait_for_state(store, review_id, terminal_state)
    wait_for_lane_release(jobs)

    assert order == [
        "provider-start",
        "client.complete",
        f"outcome:{expected_outcome}",
        "transport-metadata",
        "audit",
    ]
    attempt = store.get_review(review_id)["attempts"][-1]
    assert attempt["outcome"] == expected_outcome
    for field in Q03JA_FIELDS:
        assert field in attempt


def test_q03ja_service_generated_protocol_error_preserves_result_observation(tmp_path) -> None:
    order: list[str] = []
    client = ObservedNaturalClient(order, content="   ")
    service, store, jobs, base, target = _make_ordered_natural_service(tmp_path, client, order)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    order.clear()

    service.transmit_review(review_id)
    wait_for_state(store, review_id, ReviewState.FAILED)
    wait_for_lane_release(jobs)

    attempt = store.get_review(review_id)["attempts"][-1]
    assert attempt["outcome"] == AttemptOutcome.REJECTED.value
    for field in Q03JA_FIELDS:
        assert field in attempt
    assert order.index("outcome:REJECTED") < order.index("transport-metadata") < order.index("audit")


def test_q03ja_blind_revalidation_records_observation(tmp_path) -> None:
    client = ObservedNaturalClient()
    service, store, jobs, repository_path, base, target = make_revalidation_service(
        tmp_path,
        client,
    )
    review_id = establish_initial_review(service, store, jobs, base, target)
    revalidation_id = prepare_revalidation(
        service,
        repository_path,
        review_id,
        target,
    )

    service.transmit_blind_revalidation(revalidation_id)
    wait_for_revalidation_state(store, revalidation_id, ReviewState.BLIND_REVALIDATED)
    wait_for_revalidation_lane_release(jobs)

    attempt = store.get_revalidation(revalidation_id)["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert field in attempt


def test_q03ja_public_attempt_projection_does_not_expose_diagnostics(tmp_path) -> None:
    client = ObservedNaturalClient()
    service, store, jobs, base, target = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])

    service.transmit_review(review_id)
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(jobs)

    public_attempt = service.get_review(review_id, view="attempts")["attempts"][-1]
    for field in Q03JA_FIELDS:
        assert field not in public_attempt
