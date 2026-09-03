import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from byte_mcp.errors import OXEvidenceError, OXTransportFailureKind
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import AttemptOutcome, ReviewState

MANIFEST_SHA256 = "a" * 64
RUNTIME_SESSION_ID = "a" * 32
OTHER_RUNTIME_SESSION_ID = "b" * 32


def _prepare(store: EvidenceStore) -> str:
    return store.persist_prepared_review(
        identity={"repository": "fixture", "subsystem": "validation", "objective": "review"},
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )


def _prepare_revalidation(store: EvidenceStore, review_id: str) -> str:
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
    return revalidation_id


def test_persisted_review_ids_are_monotonic_across_store_restart(tmp_path):
    first = _prepare(EvidenceStore(tmp_path))
    second = _prepare(EvidenceStore(tmp_path))
    restarted = EvidenceStore(tmp_path)

    assert first == "OX-000001"
    assert second == "OX-000002"
    assert restarted.allocate_revalidation_id(first) == "OX-000001-RV001"


def test_prepared_json_is_immutable_and_history_is_canonical_jsonl(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    with pytest.raises(OXEvidenceError, match="immutable"):
        store.persist_prepared_review(
            identity={"review_id": review_id},
            manifest={"manifest_sha256": MANIFEST_SHA256},
            bundle={"packet": "replacement"},
        )
    store.append_thread_message(review_id, "initial", {"role": "user", "content": "hello"})
    store.append_thread_message(review_id, "initial", {"content": "world", "role": "assistant"})

    history = (tmp_path / "reviews" / review_id / "threads" / "initial.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert history == [
        '{"content":"hello","role":"user"}',
        '{"content":"world","role":"assistant"}',
    ]


def test_get_review_ignores_and_reports_a_torn_trailing_event(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"event_type":"TRANSMISSION_INTENT"')

    review = store.get_review(review_id)

    assert review["state"] == ReviewState.PREPARED
    assert review["recovery_warnings"] == ["ignored malformed trailing events record"]
    assert review["attempts"] == []


def test_findings_recorded_distinguishes_missing_from_explicit_empty_artifact(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    assert store.findings_recorded(review_id) is False

    store.persist_findings(
        review_id,
        {
            "protocol_version": "byte-derived-findings-v1",
            "review_id": review_id,
            "findings": [],
        },
    )

    assert store.findings_recorded(review_id) is True


def test_provider_messages_and_adjudication_are_separate_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    store.append_thread_message(review_id, "initial", {"role": "user", "content": "review"})
    store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    store.persist_provider_response(review_id, "OX-000001-A001", {"content": "finding"})
    store.append_adjudication(
        review_id,
        {"finding_id": "OX-000001-F001", "status": "CONFIRMED", "rationale": "reproduced"},
    )

    review_dir = tmp_path / "reviews" / review_id
    assert (review_dir / "responses" / "OX-000001-A001.json").is_file()
    assert (review_dir / "adjudication.jsonl").is_file()
    assert not (review_dir / "threads" / "initial.jsonl").read_text(encoding="utf-8").count(
        "CONFIRMED"
    )


def test_provider_response_requires_current_transmitting_attempt(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    response_path = (
        tmp_path / "reviews" / review_id / "responses" / f"{review_id}-A001.json"
    )

    with pytest.raises(OXEvidenceError, match="unknown|transmitting|current"):
        store.persist_provider_response(review_id, f"{review_id}-A001", {"content": "premature"})
    assert not response_path.exists()

    first = store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    store.persist_provider_response(review_id, first["attempt_id"], {"content": "first"})
    first_response = response_path.read_bytes()
    store.record_attempt_outcome(review_id, first["attempt_id"], AttemptOutcome.NOT_SENT)
    second = store.claim_retry_transmission(
        review_id, MANIFEST_SHA256, renewed_approval=True
    )

    with pytest.raises(OXEvidenceError, match="current"):
        store.persist_provider_response(review_id, first["attempt_id"], {"content": "stale"})
    assert response_path.read_bytes() == first_response
    store.persist_provider_response(review_id, second["attempt_id"], {"content": "second"})


def test_attempt_outcome_requires_latest_transmitting_attempt(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    store.record_attempt_outcome(review_id, first["attempt_id"], AttemptOutcome.NOT_SENT)
    second = store.claim_retry_transmission(
        review_id, MANIFEST_SHA256, renewed_approval=True
    )

    with pytest.raises(OXEvidenceError, match="current"):
        store.record_attempt_outcome(review_id, first["attempt_id"], AttemptOutcome.REJECTED)

    store.record_attempt_outcome(review_id, second["attempt_id"], AttemptOutcome.REJECTED)
    assert store.get_review(review_id)["attempts"] == [
        {
            "attempt_id": first["attempt_id"],
            "manifest_sha256": MANIFEST_SHA256,
            "outcome": AttemptOutcome.NOT_SENT.value,
        },
        {
            "attempt_id": second["attempt_id"],
            "manifest_sha256": MANIFEST_SHA256,
            "outcome": AttemptOutcome.REJECTED.value,
        },
    ]


def test_initial_claim_rechecks_digest_and_appends_one_transmission_intent(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    with pytest.raises(OXEvidenceError, match="manifest"):
        store.claim_initial_transmission(review_id, "b" * 64)
    attempt = store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    review = store.get_review(review_id)

    assert attempt["attempt_id"] == "OX-000001-A001"
    assert review["state"] == ReviewState.TRANSMITTING
    assert review["attempts"] == [
        {"attempt_id": "OX-000001-A001", "manifest_sha256": MANIFEST_SHA256}
    ]


@pytest.mark.parametrize(
    "outcome", [AttemptOutcome.NOT_SENT, AttemptOutcome.REJECTED, AttemptOutcome.OUTCOME_UNKNOWN]
)
def test_retry_requires_renewed_approval_and_preserves_prior_attempt(tmp_path, outcome):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    store.record_attempt_outcome(review_id, first["attempt_id"], outcome)

    with pytest.raises(OXEvidenceError, match="renewed approval"):
        store.claim_retry_transmission(review_id, MANIFEST_SHA256, renewed_approval=False)
    retry = store.claim_retry_transmission(review_id, MANIFEST_SHA256, renewed_approval=True)
    review = store.get_review(review_id)

    assert retry["attempt_id"] == "OX-000001-A002"
    assert [attempt["attempt_id"] for attempt in review["attempts"]] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]
    assert {attempt["manifest_sha256"] for attempt in review["attempts"]} == {MANIFEST_SHA256}


def test_retry_rejects_completed_attempt(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    store.record_attempt_outcome(review_id, first["attempt_id"], AttemptOutcome.COMPLETED)

    with pytest.raises(OXEvidenceError, match="eligible"):
        store.claim_retry_transmission(review_id, MANIFEST_SHA256, renewed_approval=True)


def test_two_initial_claims_racing_yield_exactly_one_winner(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    barrier = threading.Barrier(2)
    winners = []
    errors = []

    def claim() -> None:
        barrier.wait()
        try:
            winners.append(store.claim_initial_transmission(review_id, MANIFEST_SHA256))
        except OXEvidenceError as error:
            errors.append(str(error))

    threads = [threading.Thread(target=claim), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [winner["attempt_id"] for winner in winners] == ["OX-000001-A001"]
    assert len(errors) == 1
    assert store.get_review(review_id)["state"] == ReviewState.TRANSMITTING


def test_immutable_files_contain_canonical_json(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    review_path = tmp_path / "reviews" / review_id / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))

    assert review["review_id"] == review_id
    assert review["state"] == "PREPARED"


@pytest.mark.parametrize("operation", ["thread", "adjudication"])
def test_jsonl_mutation_failures_are_sanitized(tmp_path, monkeypatch, operation):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    def fail(*_args, **_kwargs):
        raise OSError("secret filesystem path")

    monkeypatch.setattr(EvidenceStore, "_append_jsonl", staticmethod(fail))
    with pytest.raises(OXEvidenceError) as raised:
        if operation == "thread":
            store.append_thread_message(review_id, "initial", {"role": "user"})
        else:
            store.append_adjudication(review_id, {"finding_id": "F1", "status": "CONFIRMED"})

    expected = (
        ("unable to append thread message",)
        if operation == "thread"
        else ("unable to append adjudication",)
    )
    assert raised.value.args == expected
    assert "secret filesystem path" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_manifest_verification_failure_is_sanitized(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    def fail(*_args, **_kwargs):
        raise ValueError("secret serialized manifest")

    monkeypatch.setattr(EvidenceStore, "_read_json", staticmethod(fail))
    with pytest.raises(OXEvidenceError) as raised:
        store._verify_manifest_digest(review_id, MANIFEST_SHA256)

    assert raised.value.args == ("unable to verify manifest digest",)
    assert "secret serialized manifest" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_failed_preparation_leaves_no_incomplete_review(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    original_append = EvidenceStore._append_jsonl

    def fail_events(path, value):
        if path.name == "events.jsonl":
            raise OSError("disk full")
        return original_append(path, value)

    monkeypatch.setattr(EvidenceStore, "_append_jsonl", staticmethod(fail_events))
    with pytest.raises(OXEvidenceError):
        _prepare(store)

    assert not (tmp_path / "reviews" / "OX-000001").exists()
    assert not (tmp_path / "reviews" / ".OX-000001.reserve").exists()

    monkeypatch.setattr(EvidenceStore, "_append_jsonl", staticmethod(original_append))
    assert _prepare(EvidenceStore(tmp_path)) == "OX-000001"


def test_concurrent_preparations_reserve_distinct_review_ids(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path)
    original_allocate = EvidenceStore._allocate_review_id
    allocation_barrier = threading.Barrier(2, timeout=5)
    results = []
    errors = []

    def delayed_allocate(current_store):
        review_id = original_allocate(current_store)
        allocation_barrier.wait()
        return review_id

    monkeypatch.setattr(EvidenceStore, "_allocate_review_id", delayed_allocate)

    def prepare() -> None:
        try:
            results.append(_prepare(store))
        except Exception as error:  # pragma: no cover - assertion below reports unexpected errors
            errors.append(error)

    threads = [
        threading.Thread(target=prepare, daemon=True),
        threading.Thread(target=prepare, daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads), (results, errors)
    assert errors == []
    assert sorted(results) == ["OX-000001", "OX-000002"]
    monkeypatch.undo()
    assert _prepare(EvidenceStore(tmp_path)) == "OX-000003"


def test_recovered_event_log_blocks_later_mutation(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"event_type":"TRANSMISSION_INTENT"')
    original = events_path.read_bytes()

    with pytest.raises(OXEvidenceError, match="recovery"):
        store.append_thread_message(review_id, "initial", {"role": "user"})

    assert events_path.read_bytes() == original


def test_revalidation_allocation_rejects_recovered_event_log(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"event_type":"TRANSMISSION_INTENT"')

    with pytest.raises(OXEvidenceError, match="recovery"):
        store.allocate_revalidation_id(review_id)

    assert not (events_path.parent / "revalidations").exists()


@pytest.mark.parametrize("operation", ["thread", "adjudication", "provider", "findings"])
def test_mutation_reconstruction_failures_are_sanitized(tmp_path, monkeypatch, operation):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    def fail(*_args, **_kwargs):
        raise OSError("secret reconstruction path")

    monkeypatch.setattr(EvidenceStore, "_reconstruct", fail)
    with pytest.raises(OXEvidenceError) as raised:
        if operation == "thread":
            store.append_thread_message(review_id, "initial", {"role": "user"})
        elif operation == "adjudication":
            store.append_adjudication(review_id, {"finding_id": "F1", "status": "CONFIRMED"})
        elif operation == "provider":
            store.persist_provider_response(review_id, "OX-000001-A001", {"content": "finding"})
        else:
            store.persist_findings(review_id, {"finding": "value"})

    assert "secret reconstruction path" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("history", ["missing", "empty"])
def test_missing_or_empty_event_history_cannot_be_used_as_prepared(tmp_path, history):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    if history == "missing":
        events_path.unlink()
    else:
        events_path.write_bytes(b"")

    with pytest.raises(OXEvidenceError, match="malformed"):
        store.get_review(review_id)
    with pytest.raises(OXEvidenceError, match="malformed"):
        store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    with pytest.raises(OXEvidenceError, match="malformed"):
        store.append_thread_message(review_id, "initial", {"role": "user"})

    assert not (events_path.parent / "threads" / "initial.jsonl").exists()


@pytest.mark.parametrize(
    "event",
    [
        {
            "event_type": "TRANSMISSION_INTENT",
            "attempt_id": "OX-000002-A001",
            "manifest_sha256": MANIFEST_SHA256,
        },
        {
            "event_type": "TRANSMISSION_INTENT",
            "attempt_id": "OX-000001-A001",
            "manifest_sha256": "b" * 64,
        },
    ],
)
def test_reconstruction_rejects_unbound_transmission_events(tmp_path, event):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(
            json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        )

    with pytest.raises(OXEvidenceError, match="malformed|manifest|attempt"):
        store.get_review(review_id)


def test_q03h_ac05_claimed_attempt_persists_runtime_session_id(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    initial = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert initial["runtime_session_id"] == RUNTIME_SESSION_ID
    assert store.get_review(review_id)["attempts"][-1]["runtime_session_id"] == RUNTIME_SESSION_ID

    store.record_attempt_outcome(review_id, initial["attempt_id"], AttemptOutcome.NOT_SENT)
    retry = store.claim_retry_transmission(
        review_id,
        MANIFEST_SHA256,
        renewed_approval=True,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert retry["runtime_session_id"] == RUNTIME_SESSION_ID
    store.record_attempt_outcome(review_id, retry["attempt_id"], AttemptOutcome.COMPLETED)

    continuation = store.claim_continuation_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert continuation["runtime_session_id"] == RUNTIME_SESSION_ID
    store.record_attempt_outcome(
        review_id,
        continuation["attempt_id"],
        AttemptOutcome.NOT_SENT,
    )
    continuation_retry = store.claim_continuation_retry(
        review_id,
        MANIFEST_SHA256,
        continuation["attempt_id"],
        renewed_approval=True,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert continuation_retry["runtime_session_id"] == RUNTIME_SESSION_ID
    store.record_attempt_outcome(
        review_id,
        continuation_retry["attempt_id"],
        AttemptOutcome.COMPLETED,
    )

    revalidation_id = _prepare_revalidation(store, review_id)
    blind = store.claim_revalidation_transmission(
        revalidation_id,
        phase="blind",
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert blind["runtime_session_id"] == RUNTIME_SESSION_ID
    reconstructed_blind = store.get_revalidation(revalidation_id)["attempts"][-1]
    assert reconstructed_blind["runtime_session_id"] == RUNTIME_SESSION_ID
    store.record_revalidation_attempt_outcome(
        revalidation_id,
        blind["attempt_id"],
        AttemptOutcome.COMPLETED,
    )
    targeted = store.claim_revalidation_transmission(
        revalidation_id,
        phase="targeted",
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert targeted["runtime_session_id"] == RUNTIME_SESSION_ID
    store.record_revalidation_attempt_outcome(
        revalidation_id,
        targeted["attempt_id"],
        AttemptOutcome.NOT_SENT,
    )
    revalidation_retry = store.claim_revalidation_retry(
        revalidation_id,
        targeted["attempt_id"],
        renewed_approval=True,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    assert revalidation_retry["runtime_session_id"] == RUNTIME_SESSION_ID

    review_attempts = store.get_review(review_id)["attempts"]
    assert all(attempt["runtime_session_id"] == RUNTIME_SESSION_ID for attempt in review_attempts)
    revalidation_attempts = store.get_revalidation(revalidation_id)["attempts"]
    assert all(
        attempt["runtime_session_id"] == RUNTIME_SESSION_ID
        for attempt in revalidation_attempts
    )


def test_live_claim_rejects_invalid_runtime_session_before_intent(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    before = events_path.read_bytes()

    for invalid in (None, "", "x" * 33, "not-hex-runtime-owner"):
        with pytest.raises(OXEvidenceError, match="runtime session"):
            store.claim_initial_transmission(
                review_id,
                MANIFEST_SHA256,
                runtime_session_id=invalid,
            )
        assert events_path.read_bytes() == before

    with pytest.raises(TypeError):
        store.claim_initial_transmission(review_id, MANIFEST_SHA256)
    assert events_path.read_bytes() == before


def test_provider_started_event_is_unique_and_bound_to_current_attempt(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )

    store.record_provider_request_started(
        review_id,
        first["attempt_id"],
        runtime_session_id=RUNTIME_SESSION_ID,
        phase="initial",
    )
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    started = [event for event in events if event.get("event_type") == "PROVIDER_REQUEST_STARTED"]
    assert len(started) == 1
    assert set(started[0]) == {
        "attempt_id",
        "event_type",
        "phase",
        "recorded_at",
        "runtime_session_id",
    }
    assert started[0]["attempt_id"] == first["attempt_id"]
    assert started[0]["runtime_session_id"] == RUNTIME_SESSION_ID
    assert started[0]["phase"] == "initial"
    assert store.get_review(review_id)["attempts"][-1]["provider_started_at"] == started[0][
        "recorded_at"
    ]

    with pytest.raises(OXEvidenceError, match="already|duplicate"):
        store.record_provider_request_started(
            review_id,
            first["attempt_id"],
            runtime_session_id=RUNTIME_SESSION_ID,
            phase="initial",
        )

    other_review = _prepare(store)
    other = store.claim_initial_transmission(
        other_review,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    with pytest.raises(OXEvidenceError, match="runtime session|owner"):
        store.record_provider_request_started(
            other_review,
            other["attempt_id"],
            runtime_session_id=OTHER_RUNTIME_SESSION_ID,
            phase="initial",
        )
    with pytest.raises(OXEvidenceError, match="phase"):
        store.record_provider_request_started(
            other_review,
            other["attempt_id"],
            runtime_session_id=RUNTIME_SESSION_ID,
            phase="blind",
        )

    stale_review = _prepare(store)
    stale = store.claim_initial_transmission(
        stale_review,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    store.record_attempt_outcome(stale_review, stale["attempt_id"], AttemptOutcome.NOT_SENT)
    current = store.claim_retry_transmission(
        stale_review,
        MANIFEST_SHA256,
        renewed_approval=True,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    with pytest.raises(OXEvidenceError, match="current"):
        store.record_provider_request_started(
            stale_review,
            stale["attempt_id"],
            runtime_session_id=RUNTIME_SESSION_ID,
            phase="initial",
        )
    assert current["attempt_id"] != stale["attempt_id"]


def test_transport_metadata_is_bounded_terminal_and_owner_bound(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    attempt = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    store.record_provider_request_started(
        review_id,
        attempt["attempt_id"],
        runtime_session_id=RUNTIME_SESSION_ID,
        phase="initial",
    )
    finished_at = datetime.now(UTC).isoformat()

    with pytest.raises(OXEvidenceError, match="terminal|outcome"):
        store.record_provider_transport_metadata(
            review_id,
            attempt["attempt_id"],
            runtime_session_id=RUNTIME_SESSION_ID,
            provider_finished_at=finished_at,
            elapsed_ms=17,
            transport_failure_kind=OXTransportFailureKind.READ_ERROR,
        )

    store.record_attempt_outcome(
        review_id,
        attempt["attempt_id"],
        AttemptOutcome.OUTCOME_UNKNOWN,
    )
    store.record_provider_transport_metadata(
        review_id,
        attempt["attempt_id"],
        runtime_session_id=RUNTIME_SESSION_ID,
        provider_finished_at=finished_at,
        elapsed_ms=17,
        transport_failure_kind=OXTransportFailureKind.READ_ERROR,
    )
    reconstructed = store.get_review(review_id)["attempts"][-1]
    assert reconstructed["provider_finished_at"] == finished_at
    assert reconstructed["elapsed_ms"] == 17
    assert reconstructed["transport_failure_kind"] == OXTransportFailureKind.READ_ERROR.value

    with pytest.raises(OXEvidenceError, match="already|duplicate"):
        store.record_provider_transport_metadata(
            review_id,
            attempt["attempt_id"],
            runtime_session_id=RUNTIME_SESSION_ID,
            provider_finished_at=finished_at,
            elapsed_ms=17,
            transport_failure_kind=OXTransportFailureKind.READ_ERROR,
        )


def test_q03h_ac19_legacy_q03g_evidence_reads_without_migration(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    legacy_intent = {
        "attempt_id": f"{review_id}-A001",
        "event_type": "TRANSMISSION_INTENT",
        "manifest_sha256": MANIFEST_SHA256,
        "recorded_at": "2026-09-01T00:00:00+00:00",
    }
    with events_path.open("ab") as handle:
        handle.write(
            json.dumps(legacy_intent, separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
        )
    before_read = events_path.read_bytes()

    review = store.get_review(review_id)

    assert events_path.read_bytes() == before_read
    assert review["state"] == ReviewState.TRANSMITTING.value
    assert review["attempts"] == [
        {
            "attempt_id": f"{review_id}-A001",
            "manifest_sha256": MANIFEST_SHA256,
        }
    ]
    assert "runtime_session_id" not in review["attempts"][0]
    assert "provider_started_at" not in review["attempts"][0]
    assert "transport_failure_kind" not in review["attempts"][0]

    recovered = store.recover_stale_transmissions(
        stale_after=timedelta(minutes=30),
        runtime_session_id=OTHER_RUNTIME_SESSION_ID,
        now=datetime(2026, 9, 3, tzinfo=UTC),
    )
    assert recovered == (f"{review_id}-A001",)
    legacy_attempt = store.get_review(review_id)["attempts"][-1]
    assert legacy_attempt["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value
