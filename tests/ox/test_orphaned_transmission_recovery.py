import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox import runtime
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import AttemptOutcome, OXAvailability, ReviewState
from byte_mcp.ox.settings import OXSettings

MANIFEST_SHA256 = "a" * 64
RUNTIME_SESSION_A = "a" * 32
RUNTIME_SESSION_B = "b" * 32
NOW = datetime(2026, 9, 2, 10, 0, 0, tzinfo=UTC)
HORIZON = timedelta(minutes=30)
OLD = NOW - timedelta(hours=2)
FRESH = NOW - timedelta(minutes=10)


def _prepare(store: EvidenceStore) -> str:
    return store.persist_prepared_review(
        identity={
            "repository": "fixture",
            "subsystem": "orphan-recovery",
            "objective": "local recovery test",
        },
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )


def _events_path(root: Path, review_id: str) -> Path:
    return root / "reviews" / review_id / "events.jsonl"


def _revalidation_events_path(root: Path, review_id: str, revalidation_id: str) -> Path:
    return (
        root
        / "reviews"
        / review_id
        / "revalidations"
        / revalidation_id
        / "events.jsonl"
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rewrite_intent_recorded_at(
    path: Path,
    *,
    event_type: str,
    recorded_at: datetime,
) -> None:
    events = _read_jsonl(path)
    matches = [event for event in events if event.get("event_type") == event_type]
    assert len(matches) == 1
    matches[0]["recorded_at"] = recorded_at.isoformat()
    path.write_text(
        "".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def _remove_intent_recorded_at(path: Path, *, event_type: str) -> None:
    events = _read_jsonl(path)
    matches = [event for event in events if event.get("event_type") == event_type]
    assert len(matches) == 1
    assert "recorded_at" in matches[0]
    del matches[0]["recorded_at"]
    path.write_text(
        "".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def _persist_legacy_attempt_identity(
    root: Path,
    review_id: str,
    attempt_id: str,
    *,
    recorded_at: datetime,
) -> None:
    attempts = root / "reviews" / review_id / "attempts"
    attempts.mkdir(exist_ok=True)
    (attempts / f"{attempt_id}.json").write_text(
        json.dumps(
            {
                "attempt_id": attempt_id,
                "history_sha256": "b" * 64,
                "manifest_sha256": MANIFEST_SHA256,
                "phase": "initial",
                "recorded_at": recorded_at.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _prepare_blind_revalidation(store: EvidenceStore, review_id: str) -> str:
    revalidation_id = store.allocate_revalidation_id(review_id)
    store.persist_prepared_revalidation(
        review_id,
        revalidation_id,
        identity={
            "repository": "fixture",
            "subsystem": "orphan-recovery",
            "target_commit": "c" * 40,
            "base_commit": "d" * 40,
        },
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "revalidation"},
    )
    return revalidation_id


def test_new_review_transmission_intent_records_durable_utc_timestamp(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)

    store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )

    events = _read_jsonl(_events_path(tmp_path, review_id))
    intent = next(event for event in events if event["event_type"] == "TRANSMISSION_INTENT")
    recorded_at = datetime.fromisoformat(str(intent["recorded_at"]))

    assert recorded_at.tzinfo is not None
    assert recorded_at.utcoffset() == timedelta(0)


def test_new_revalidation_transmission_intent_records_durable_utc_timestamp(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    revalidation_id = _prepare_blind_revalidation(store, review_id)

    store.claim_revalidation_transmission(
        revalidation_id,
        phase="blind",
        runtime_session_id=RUNTIME_SESSION_A,
    )

    events = _read_jsonl(_revalidation_events_path(tmp_path, review_id, revalidation_id))
    intent = next(
        event
        for event in events
        if event["event_type"] == "REVALIDATION_TRANSMISSION_INTENT"
    )
    recorded_at = datetime.fromisoformat(str(intent["recorded_at"]))

    assert recorded_at.tzinfo is not None
    assert recorded_at.utcoffset() == timedelta(0)


def test_recovery_leaves_fresh_transmitting_review_untouched(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _events_path(tmp_path, review_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="TRANSMISSION_INTENT",
        recorded_at=FRESH,
    )
    before = path.read_bytes()

    recovered = store.recover_stale_transmissions(now=NOW, stale_after=HORIZON)

    assert recovered == ()
    assert path.read_bytes() == before
    assert store.get_review(review_id)["state"] == ReviewState.TRANSMITTING.value
    assert store.get_review(review_id)["attempts"] == [
        {
            "attempt_id": first["attempt_id"],
            "manifest_sha256": MANIFEST_SHA256,
            "runtime_session_id": RUNTIME_SESSION_A,
        }
    ]


def test_recovery_marks_stale_review_outcome_unknown_without_retry(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _events_path(tmp_path, review_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="TRANSMISSION_INTENT",
        recorded_at=OLD,
    )

    recovered = store.recover_stale_transmissions(now=NOW, stale_after=HORIZON)
    review = store.get_review(review_id)

    assert recovered == (first["attempt_id"],)
    assert review["state"] == ReviewState.OUTCOME_UNKNOWN.value
    assert len(review["attempts"]) == 1
    assert review["attempts"][0]["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value
    assert "NOT_SENT" not in path.read_text(encoding="utf-8")


def test_recovery_uses_legacy_attempt_identity_timestamp_when_intent_has_none(
    tmp_path,
) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )

    # Simulate the pre-Q03E format: intent has no timestamp, but the service's
    # immutable attempt identity contains recorded_at.
    _remove_intent_recorded_at(
        _events_path(tmp_path, review_id),
        event_type="TRANSMISSION_INTENT",
    )
    _persist_legacy_attempt_identity(
        tmp_path,
        review_id,
        first["attempt_id"],
        recorded_at=OLD,
    )

    recovered = store.recover_stale_transmissions(now=NOW, stale_after=HORIZON)

    assert recovered == (first["attempt_id"],)
    assert store.get_review(review_id)["state"] == ReviewState.OUTCOME_UNKNOWN.value


def test_recovery_marks_stale_revalidation_outcome_unknown_without_retry(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    revalidation_id = _prepare_blind_revalidation(store, review_id)
    first = store.claim_revalidation_transmission(
        revalidation_id,
        phase="blind",
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _revalidation_events_path(tmp_path, review_id, revalidation_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="REVALIDATION_TRANSMISSION_INTENT",
        recorded_at=OLD,
    )

    recovered = store.recover_stale_transmissions(now=NOW, stale_after=HORIZON)
    revalidation = store.get_revalidation(revalidation_id)

    assert recovered == (first["attempt_id"],)
    assert revalidation["state"] == ReviewState.OUTCOME_UNKNOWN.value
    assert len(revalidation["attempts"]) == 1
    assert revalidation["attempts"][0]["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value
    assert "NOT_SENT" not in path.read_text(encoding="utf-8")


def test_recovery_is_idempotent_and_never_relabels_terminal_unknown(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _events_path(tmp_path, review_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="TRANSMISSION_INTENT",
        recorded_at=OLD,
    )

    assert store.recover_stale_transmissions(now=NOW, stale_after=HORIZON) == (
        first["attempt_id"],
    )
    terminal = path.read_bytes()

    assert store.recover_stale_transmissions(
        now=NOW + timedelta(days=1),
        stale_after=HORIZON,
    ) == ()
    assert path.read_bytes() == terminal
    assert store.get_review(review_id)["attempts"][-1]["outcome"] == "OUTCOME_UNKNOWN"


def test_recovered_unknown_still_requires_new_explicit_retry_approval(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    _rewrite_intent_recorded_at(
        _events_path(tmp_path, review_id),
        event_type="TRANSMISSION_INTENT",
        recorded_at=OLD,
    )
    store.recover_stale_transmissions(now=NOW, stale_after=HORIZON)

    with pytest.raises(OXEvidenceError, match="renewed approval"):
        store.claim_retry_transmission(
            review_id,
            MANIFEST_SHA256,
            renewed_approval=False,
            runtime_session_id=RUNTIME_SESSION_A,
        )

    assert len(store.get_review(review_id)["attempts"]) == 1

    retry = store.claim_retry_transmission(
        review_id,
        MANIFEST_SHA256,
        renewed_approval=True,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    assert retry["attempt_id"] != first["attempt_id"]
    assert len(store.get_review(review_id)["attempts"]) == 2


def test_existing_terminal_unknown_is_byte_immutable_under_recovery(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    store.record_attempt_outcome(
        review_id,
        first["attempt_id"],
        AttemptOutcome.OUTCOME_UNKNOWN,
    )
    path = _events_path(tmp_path, review_id)
    before = path.read_bytes()

    recovered = store.recover_stale_transmissions(
        now=NOW + timedelta(days=30),
        stale_after=HORIZON,
    )

    assert recovered == ()
    assert path.read_bytes() == before
    assert store.get_review(review_id)["state"] == ReviewState.OUTCOME_UNKNOWN.value


def test_settings_define_conservative_orphan_recovery_horizon(tmp_path) -> None:
    settings = OXSettings(
        api_key=None,
        repositories_file=tmp_path / "repositories.json",
        evidence_root=tmp_path / "evidence",
    )

    assert settings.orphan_recovery_seconds == 1800
    assert settings.orphan_recovery_seconds > 900


def test_runtime_initialization_runs_local_recovery_before_exposing_service(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[tuple[timedelta, str]] = []
    injected_jobs: list[object] = []

    class FakeStore:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "evidence"

        def recover_stale_transmissions(
            self,
            *,
            stale_after: timedelta,
            runtime_session_id: str,
            now: datetime | None = None,
        ) -> tuple[str, ...]:
            assert now is None
            calls.append((stale_after, runtime_session_id))
            return ()

    def fake_service(settings, evidence, client, audit, jobs):
        injected_jobs.append(jobs)
        return object()

    monkeypatch.setattr(runtime, "validate_ox_local_config", lambda settings: None)
    monkeypatch.setattr(runtime, "EvidenceStore", FakeStore)
    monkeypatch.setattr(runtime, "OXClient", lambda settings: object())
    monkeypatch.setattr(runtime, "OXReviewService", fake_service)

    settings = OXSettings(
        api_key="local-test-key",
        repositories_file=tmp_path / "repositories.json",
        evidence_root=tmp_path / "evidence",
    )

    initialized = runtime.OXRuntime.initialize(settings, audit=object())

    assert initialized.state is OXAvailability.AVAILABLE
    assert len(injected_jobs) == 1
    assert calls == [
        (
            timedelta(seconds=1800),
            injected_jobs[0].runtime_session_id,
        )
    ]


def test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _events_path(tmp_path, review_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="TRANSMISSION_INTENT",
        recorded_at=FRESH,
    )

    recovered = store.recover_stale_transmissions(
        now=NOW,
        stale_after=HORIZON,
        runtime_session_id=RUNTIME_SESSION_B,
    )
    review = store.get_review(review_id)

    assert recovered == (first["attempt_id"],)
    assert review["state"] == ReviewState.OUTCOME_UNKNOWN.value
    assert review["attempts"] == [
        {
            "attempt_id": first["attempt_id"],
            "manifest_sha256": MANIFEST_SHA256,
            "runtime_session_id": RUNTIME_SESSION_A,
            "outcome": AttemptOutcome.OUTCOME_UNKNOWN.value,
        }
    ]
    assert not any(attempt["attempt_id"].endswith("A002") for attempt in review["attempts"])
    assert store.recover_stale_transmissions(
        now=NOW + timedelta(hours=1),
        stale_after=HORIZON,
        runtime_session_id=RUNTIME_SESSION_B,
    ) == ()


def test_q03h_current_runtime_transmission_is_not_recovered_as_orphan(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    first = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _events_path(tmp_path, review_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="TRANSMISSION_INTENT",
        recorded_at=OLD,
    )
    before = path.read_bytes()

    recovered = store.recover_stale_transmissions(
        now=NOW,
        stale_after=HORIZON,
        runtime_session_id=RUNTIME_SESSION_A,
    )

    assert recovered == ()
    assert path.read_bytes() == before
    assert store.get_review(review_id)["attempts"] == [
        {
            "attempt_id": first["attempt_id"],
            "manifest_sha256": MANIFEST_SHA256,
            "runtime_session_id": RUNTIME_SESSION_A,
        }
    ]


def test_q03h_prior_runtime_revalidation_recovers_unknown_immediately(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id = _prepare(store)
    revalidation_id = _prepare_blind_revalidation(store, review_id)
    attempt = store.claim_revalidation_transmission(
        revalidation_id,
        phase="blind",
        runtime_session_id=RUNTIME_SESSION_A,
    )
    path = _revalidation_events_path(tmp_path, review_id, revalidation_id)
    _rewrite_intent_recorded_at(
        path,
        event_type="REVALIDATION_TRANSMISSION_INTENT",
        recorded_at=FRESH,
    )

    recovered = store.recover_stale_transmissions(
        now=NOW,
        stale_after=HORIZON,
        runtime_session_id=RUNTIME_SESSION_B,
    )

    assert recovered == (attempt["attempt_id"],)
    revalidation = store.get_revalidation(revalidation_id)
    assert revalidation["state"] == ReviewState.OUTCOME_UNKNOWN.value
    assert revalidation["attempts"][-1]["runtime_session_id"] == RUNTIME_SESSION_A
    assert revalidation["attempts"][-1]["outcome"] == AttemptOutcome.OUTCOME_UNKNOWN.value
