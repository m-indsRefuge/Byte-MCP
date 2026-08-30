from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from byte_mcp.errors import WriteIntegrityError, WriteStaleStateError, WriteTransactionError
from byte_mcp.write.journal import TransactionJournal, TransactionStatus


def test_journal_generates_random_transaction_id_and_persists_lifecycle(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    created = journal.create("demo", {"manifest_sha256": "a" * 64})

    assert created.transaction_id.startswith("TX-")
    assert len(created.transaction_id) == 35
    assert created.status is TransactionStatus.REQUESTED
    assert created.project == "demo"
    assert journal.read(created.transaction_id) == created

    validating = journal.transition(
        created.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.VALIDATING,
    )
    prepared = journal.transition(
        created.transaction_id,
        TransactionStatus.VALIDATING,
        TransactionStatus.PREPARED,
        metadata_updates={"policy_fingerprint": "b" * 64},
    )
    committing = journal.transition(
        created.transaction_id,
        TransactionStatus.PREPARED,
        TransactionStatus.COMMITTING,
    )
    committed = journal.transition(
        created.transaction_id,
        TransactionStatus.COMMITTING,
        TransactionStatus.COMMITTED,
        result={"result_sha256": "c" * 64},
    )

    assert validating.updated_at >= created.updated_at
    assert prepared.metadata["policy_fingerprint"] == "b" * 64
    assert committing.status is TransactionStatus.COMMITTING
    assert committed.result == {"result_sha256": "c" * 64}
    assert journal.read(created.transaction_id) == committed


def test_journal_rejects_illegal_and_stale_transitions(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    record = journal.create("demo")

    with pytest.raises(WriteTransactionError, match="transition"):
        journal.transition(
            record.transaction_id,
            TransactionStatus.REQUESTED,
            TransactionStatus.COMMITTED,
        )

    with pytest.raises(WriteStaleStateError, match="state"):
        journal.transition(
            record.transaction_id,
            TransactionStatus.PREPARED,
            TransactionStatus.COMMITTING,
        )


def test_journal_append_step_is_durable_and_expected_state_bound(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    record = journal.create("demo")
    record = journal.transition(
        record.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.VALIDATING,
    )

    with_step = journal.append_step(
        record.transaction_id,
        TransactionStatus.VALIDATING,
        {"operation_index": 0, "phase": "validated", "sha256": "d" * 64},
    )
    assert with_step.steps == (
        {"operation_index": 0, "phase": "validated", "sha256": "d" * 64},
    )
    assert journal.read(record.transaction_id).steps == with_step.steps

    with pytest.raises(WriteStaleStateError):
        journal.append_step(
            record.transaction_id,
            TransactionStatus.PREPARED,
            {"operation_index": 1},
        )


def test_journal_rejects_content_bodies(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    with pytest.raises(WriteIntegrityError, match="content"):
        journal.create("demo", {"content": "must never be journaled"})


def test_journal_torn_or_digest_mismatched_file_fails_closed(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    record = journal.create("demo")
    path = write_env.state_dir / "journal" / f"{record.transaction_id}.json"

    path.write_text("{", encoding="utf-8")
    with pytest.raises(WriteIntegrityError, match="journal"):
        journal.read(record.transaction_id)

    replacement = journal.create("other")
    replacement_path = write_env.state_dir / "journal" / f"{replacement.transaction_id}.json"
    payload = json.loads(replacement_path.read_text(encoding="utf-8"))
    payload["journal"]["project"] = "tampered"
    replacement_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WriteIntegrityError, match="integrity"):
        journal.read(replacement.transaction_id)


def test_journal_incomplete_returns_only_recovery_relevant_states(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    prepared = journal.create("prepared")
    prepared = journal.transition(
        prepared.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.VALIDATING,
    )
    prepared = journal.transition(
        prepared.transaction_id,
        TransactionStatus.VALIDATING,
        TransactionStatus.PREPARED,
    )

    committed = journal.create("committed")
    committed = journal.transition(
        committed.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.VALIDATING,
    )
    committed = journal.transition(
        committed.transaction_id,
        TransactionStatus.VALIDATING,
        TransactionStatus.PREPARED,
    )
    committed = journal.transition(
        committed.transaction_id,
        TransactionStatus.PREPARED,
        TransactionStatus.COMMITTING,
    )
    journal.transition(
        committed.transaction_id,
        TransactionStatus.COMMITTING,
        TransactionStatus.COMMITTED,
    )

    failed = journal.create("failed")
    failed = journal.transition(
        failed.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.VALIDATING,
    )
    journal.transition(
        failed.transaction_id,
        TransactionStatus.VALIDATING,
        TransactionStatus.FAILED,
    )

    incomplete = journal.incomplete()
    assert {record.transaction_id for record in incomplete} == {
        prepared.transaction_id,
        failed.transaction_id,
    }


def test_journal_atomic_replacements_leave_no_temporary_files(write_env) -> None:
    journal = TransactionJournal(write_env.state_dir)
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    record = journal.create("demo", now=now)
    journal.transition(
        record.transaction_id,
        TransactionStatus.REQUESTED,
        TransactionStatus.REJECTED,
        now=now,
        result={"error": "denied"},
    )

    journal_dir = write_env.state_dir / "journal"
    assert [path.name for path in journal_dir.iterdir()] == [f"{record.transaction_id}.json"]
