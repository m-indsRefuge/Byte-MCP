import re
import threading

import pytest

from byte_mcp.errors import OXUnavailableError
from byte_mcp.ox.jobs import (
    OXActiveLaunch,
    OXLaneLease,
    OXLaunchDescriptor,
    OXOperationKey,
    OXProviderJobManager,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _key(
    operation: str = "initial",
    subject_id: str = "OX-000001",
    digest: str = DIGEST_A,
):
    return OXOperationKey(operation=operation, subject_id=subject_id, input_sha256=digest)


def _descriptor(key: OXOperationKey, attempt_id: str = "OX-000001-A001"):
    return OXLaunchDescriptor(
        operation_key=key,
        review_id="OX-000001",
        attempt_id=attempt_id,
        manifest_sha256=DIGEST_A,
        phase=key.operation,
        revalidation_id=None,
        messages=({"role": "user", "content": "review"},),
    )


def _submit(
    manager,
    lease,
    descriptor,
    worker,
    *,
    submission_failure=lambda _d: None,
    crash=lambda _d: None,
):
    manager.submit(
        lease,
        descriptor,
        {"attempt_id": descriptor.attempt_id, "launch_accepted": True},
        worker,
        submission_failure,
        crash,
    )


def test_runtime_session_id_is_bounded_hex_and_read_only():
    manager = OXProviderJobManager()
    assert re.fullmatch(r"[0-9a-f]{32}", manager.runtime_session_id)
    with pytest.raises(AttributeError):
        manager.runtime_session_id = "0" * 32


def test_q03h_ac03_different_operation_is_busy_before_claim():
    manager = OXProviderJobManager()
    key_a = _key()
    key_b = _key(operation="continuation", digest=DIGEST_B)
    lease = manager.reserve(key_a)
    assert isinstance(lease, OXLaneLease)
    claims = []

    with pytest.raises(OXUnavailableError, match="busy"):
        manager.reserve(key_b)
        claims.append("claimed")

    assert claims == []
    assert manager.snapshot() is None
    manager.abandon(lease)


def test_same_key_reservation_is_busy_until_launch_is_accepted():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    with pytest.raises(OXUnavailableError, match="busy"):
        manager.reserve(key)
    manager.abandon(lease)


def test_same_accepted_key_returns_defensive_active_receipt_without_new_worker():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)
    started = threading.Event()
    release = threading.Event()
    worker_calls = []
    receipt = {"attempt_id": descriptor.attempt_id, "launch_accepted": True}

    def worker(_descriptor):
        worker_calls.append(1)
        started.set()
        assert release.wait(2)

    _submit(manager, lease, descriptor, worker)
    assert started.wait(2)
    replay = manager.reserve(key)
    assert isinstance(replay, OXActiveLaunch)
    assert replay.receipt == receipt
    with pytest.raises(TypeError):
        replay.receipt["launch_accepted"] = False
    assert len(worker_calls) == 1
    release.set()


def test_accepted_work_starts_in_background_and_releases_after_success():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def worker(_descriptor):
        started.set()
        assert release.wait(2)
        finished.set()

    _submit(manager, lease, descriptor, worker)
    assert started.wait(2)
    assert manager.snapshot() is not None
    release.set()
    assert finished.wait(2)
    for _ in range(100):
        if manager.snapshot() is None:
            break
        threading.Event().wait(0.001)
    assert manager.snapshot() is None
    assert isinstance(
        manager.reserve(_key(operation="continuation", digest=DIGEST_B)),
        OXLaneLease,
    )


def test_submission_failure_invokes_terminalizer_without_running_worker(monkeypatch):
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)
    worker_calls = []
    callbacks = []

    def fail_start(_thread):
        raise RuntimeError("sentinel-start-error")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    with pytest.raises(OXUnavailableError, match="unable to start") as raised:
        _submit(
            manager,
            lease,
            descriptor,
            lambda _descriptor: worker_calls.append(1),
            submission_failure=lambda current: callbacks.append(current.attempt_id),
        )

    assert "sentinel-start-error" not in str(raised.value)
    assert callbacks == [descriptor.attempt_id]
    assert worker_calls == []
    assert manager.snapshot() is None
    assert isinstance(
        manager.reserve(_key(operation="continuation", digest=DIGEST_B)),
        OXLaneLease,
    )


def test_submission_terminalizer_failure_faults_lane_closed(monkeypatch):
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)

    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError()),
    )

    with pytest.raises(RuntimeError):
        _submit(
            manager,
            lease,
            descriptor,
            lambda _descriptor: None,
            submission_failure=lambda _descriptor: (_ for _ in ()).throw(
                RuntimeError("terminal")
            ),
        )

    with pytest.raises(OXUnavailableError, match="unavailable"):
        manager.reserve(_key(operation="continuation", digest=DIGEST_B))


def test_worker_crash_callback_runs_once_and_successful_terminalizer_releases_lane():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)
    callback = threading.Event()
    crash_ids = []

    def worker(_descriptor):
        raise RuntimeError("worker-secret")

    def crash(current):
        crash_ids.append(current.attempt_id)
        callback.set()

    _submit(manager, lease, descriptor, worker, crash=crash)
    assert callback.wait(2)
    for _ in range(100):
        if manager.snapshot() is None:
            break
        threading.Event().wait(0.001)
    assert crash_ids == [descriptor.attempt_id]
    assert manager.snapshot() is None
    assert isinstance(
        manager.reserve(_key(operation="continuation", digest=DIGEST_B)),
        OXLaneLease,
    )


def test_worker_terminalizer_failure_faults_lane_closed():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    descriptor = _descriptor(key)
    callback = threading.Event()

    def worker(_descriptor):
        raise RuntimeError("worker-secret")

    def crash(_descriptor):
        callback.set()
        raise RuntimeError("terminal-secret")

    _submit(manager, lease, descriptor, worker, crash=crash)
    assert callback.wait(2)
    with pytest.raises(OXUnavailableError, match="unavailable"):
        manager.reserve(_key(operation="continuation", digest=DIGEST_B))


def test_same_attempt_cannot_be_submitted_twice():
    manager = OXProviderJobManager()
    key = _key()
    first_lease = manager.reserve(key)
    assert isinstance(first_lease, OXLaneLease)
    descriptor = _descriptor(key)
    finished = threading.Event()
    _submit(manager, first_lease, descriptor, lambda _descriptor: finished.set())
    assert finished.wait(2)
    for _ in range(100):
        if manager.snapshot() is None:
            break
        threading.Event().wait(0.001)
    second_lease = manager.reserve(key)
    assert isinstance(second_lease, OXLaneLease)
    with pytest.raises(OXUnavailableError, match="already submitted"):
        _submit(manager, second_lease, descriptor, lambda _descriptor: None)
    manager.abandon(second_lease)


def test_abandon_and_fault_closed_require_the_matching_lease():
    manager = OXProviderJobManager()
    key = _key()
    lease = manager.reserve(key)
    assert isinstance(lease, OXLaneLease)
    fake = OXLaneLease(operation_key=key, _token=0)
    with pytest.raises(OXUnavailableError, match="not active"):
        manager.abandon(fake)
    with pytest.raises(OXUnavailableError, match="not active"):
        manager.fault_closed(fake)
    manager.fault_closed(lease)
    with pytest.raises(OXUnavailableError, match="unavailable"):
        manager.reserve(key)
