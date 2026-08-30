from __future__ import annotations

import subprocess
import sys
import time

import pytest

from byte_mcp.errors import WriteLockError
from byte_mcp.write.locking import ProjectWriteLock


def test_project_lock_release_allows_reacquire(write_env) -> None:
    manager = ProjectWriteLock(write_env.state_dir)
    held = manager.acquire("demo", "TX-0123456789abcdef")
    assert held.project == "demo"
    assert held.transaction_id == "TX-0123456789abcdef"
    assert held.owner_token

    with pytest.raises(WriteLockError, match="lock"):
        manager.acquire("demo", "TX-fedcba9876543210")

    held.release()
    reacquired = manager.acquire("demo", "TX-fedcba9876543210")
    reacquired.release()


def test_kernel_lock_is_project_scoped_and_crash_releases_ownership(write_env) -> None:
    helper = """
from pathlib import Path
import sys
from byte_mcp.write.locking import ProjectWriteLock
held = ProjectWriteLock(Path(sys.argv[1])).acquire(sys.argv[2], sys.argv[3])
print('READY', flush=True)
sys.stdin.readline()
held.release()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            helper,
            str(write_env.state_dir),
            "demo",
            "TX-helper0123456789",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"

        manager = ProjectWriteLock(write_env.state_dir)
        with pytest.raises(WriteLockError, match="lock"):
            manager.acquire("demo", "TX-parent0123456789")

        other = manager.acquire("other", "TX-other0123456789")
        other.release()

        process.kill()
        process.wait(timeout=10)

        locks = list((write_env.state_dir / "locks").glob("*.lock"))
        assert locks, "lock metadata file should remain after process death"

        deadline = time.monotonic() + 5
        while True:
            try:
                reacquired = manager.acquire("demo", "TX-parent0123456789")
                break
            except WriteLockError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        reacquired.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
