import json
import threading

import pytest

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import AttemptOutcome, ReviewState

MANIFEST_SHA256 = "a" * 64


def _prepare(store: EvidenceStore) -> str:
    return store.persist_prepared_review(
        identity={"repository": "fixture", "subsystem": "validation", "objective": "review"},
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )


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


def test_provider_messages_and_adjudication_are_separate_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    store.append_thread_message(review_id, "initial", {"role": "user", "content": "review"})
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
