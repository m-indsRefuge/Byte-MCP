from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from byte_mcp.errors import WriteIntegrityError, WriteStaleStateError
from byte_mcp.write.policy import WritePolicy
from byte_mcp.write.recovery import RecoveryStore


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_file_snapshot_is_same_pass_verified_and_materializable(write_env) -> None:
    source = write_env.projects / "demo.txt"
    source.write_bytes(b"hello\r\n")
    source.chmod(0o640)
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    store = RecoveryStore(write_env.state_dir)

    item = store.snapshot_file(
        source,
        source_relative="demo/demo.txt",
        expected_sha256=_sha(b"hello\r\n"),
        transaction_id="TX-0123456789abcdef",
        created_at=now,
    )

    assert item.recovery_id.startswith("RCV-")
    assert item.source_relative == "demo/demo.txt"
    assert item.source_sha256 == _sha(b"hello\r\n")
    assert item.byte_count == 7
    assert item.transaction_id == "TX-0123456789abcdef"
    assert store.verify(item.recovery_id) == item

    destination = write_env.private / "restored.txt"
    store.materialize(item.recovery_id, destination)
    assert destination.read_bytes() == b"hello\r\n"
    assert destination.stat().st_mode & 0o777 == source.stat().st_mode & 0o777


def test_file_snapshot_rejects_wrong_sha_and_source_drift(write_env, monkeypatch) -> None:
    import byte_mcp.write.recovery as recovery_module

    source = write_env.projects / "demo.txt"
    source.write_bytes(b"before")
    store = RecoveryStore(write_env.state_dir)

    with pytest.raises(WriteStaleStateError, match="SHA"):
        store.snapshot_file(
            source,
            source_relative="demo/demo.txt",
            expected_sha256="0" * 64,
            transaction_id="TX-0123456789abcdef",
        )

    original_copy = recovery_module._copy_file_payload

    def copy_then_change(*args, **kwargs):
        result = original_copy(*args, **kwargs)
        source.write_bytes(b"after")
        return result

    monkeypatch.setattr(recovery_module, "_copy_file_payload", copy_then_change)
    source.write_bytes(b"before")
    with pytest.raises(WriteStaleStateError, match="changed"):
        store.snapshot_file(
            source,
            source_relative="demo/demo.txt",
            expected_sha256=_sha(b"before"),
            transaction_id="TX-0123456789abcdef",
        )


def test_directory_snapshot_binds_digest_and_detects_drift(write_env, monkeypatch) -> None:
    import byte_mcp.write.recovery as recovery_module

    source = write_env.projects / "demo"
    (source / "src").mkdir(parents=True)
    (source / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    store = RecoveryStore(write_env.state_dir)

    item = store.snapshot_directory(
        source,
        source_relative="demo/src-tree",
        transaction_id="TX-0123456789abcdef",
        max_entries=20,
        max_bytes=1_000,
        require_text=True,
    )
    assert item.source_directory_digest is not None
    assert store.verify(item.recovery_id) == item

    destination = write_env.private / "restored-tree"
    store.materialize(item.recovery_id, destination)
    assert (destination / "src" / "a.py").read_text(encoding="utf-8") == "print('a')\n"

    original_copy = recovery_module._copy_directory_payload

    def copy_then_change(*args, **kwargs):
        result = original_copy(*args, **kwargs)
        (source / "src" / "a.py").write_text("print('changed')\n", encoding="utf-8")
        return result

    monkeypatch.setattr(recovery_module, "_copy_directory_payload", copy_then_change)
    with pytest.raises(WriteStaleStateError, match="changed"):
        store.snapshot_directory(
            source,
            source_relative="demo/src-tree",
            transaction_id="TX-fedcba9876543210",
            max_entries=20,
            max_bytes=1_000,
            require_text=True,
        )


def test_recovery_verify_detects_payload_tampering(write_env) -> None:
    source = write_env.projects / "demo.txt"
    source.write_bytes(b"original")
    store = RecoveryStore(write_env.state_dir)
    item = store.snapshot_file(
        source,
        source_relative="demo/demo.txt",
        expected_sha256=_sha(b"original"),
        transaction_id="TX-0123456789abcdef",
    )

    payload = write_env.state_dir / "recovery" / item.recovery_id / "payload"
    payload.write_bytes(b"tampered")

    with pytest.raises(WriteIntegrityError, match="recovery"):
        store.verify(item.recovery_id)


def test_recovery_prune_respects_protection_age_and_store_limit(write_env) -> None:
    store = RecoveryStore(write_env.state_dir)
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

    old_source = write_env.projects / "old.txt"
    old_source.write_bytes(b"old!")
    old = store.snapshot_file(
        old_source,
        source_relative="demo/old.txt",
        expected_sha256=_sha(b"old!"),
        transaction_id="TX-old000000000000",
        created_at=now - timedelta(days=60),
    )

    protected_source = write_env.projects / "protected.txt"
    protected_source.write_bytes(b"123456")
    protected = store.snapshot_file(
        protected_source,
        source_relative="demo/protected.txt",
        expected_sha256=_sha(b"123456"),
        transaction_id="TX-protected000000",
        created_at=now - timedelta(days=1),
    )

    policy = replace(
        WritePolicy.load(write_env.policy_file),
        recovery_retention_days=30,
        recovery_max_bytes=5,
    )
    report = store.prune(now, policy, frozenset({protected.recovery_id}))

    assert old.recovery_id in report.removed_ids
    assert protected.recovery_id not in report.removed_ids
    assert report.limit_exceeded is True
    assert report.bytes_after == 6
    assert store.verify(protected.recovery_id) == protected
