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
