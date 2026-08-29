from datetime import UTC, datetime
from pathlib import Path
from threading import Thread

import pytest

from byte_mcp.errors import WolframQuotaError
from byte_mcp.wolfram.quota import WolframQuotaLedger


def test_quota_reserves_before_outbound_attempt(tmp_path: Path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=2)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    assert ledger.reserve_attempt(now).period_count == 1
    assert ledger.reserve_attempt(now).period_count == 2
    with pytest.raises(WolframQuotaError):
        ledger.reserve_attempt(now)


def test_month_rollover_resets_count(tmp_path: Path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=3)
    ledger.reserve_attempt(datetime(2026, 8, 31, 23, tzinfo=UTC))
    reservation = ledger.reserve_attempt(datetime(2026, 9, 1, 0, tzinfo=UTC))
    assert reservation.period_utc == "2026-09"
    assert reservation.period_count == 1


def test_snapshot_reports_remaining(tmp_path: Path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=3)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    ledger.reserve_attempt(now)
    snap = ledger.snapshot(now)
    assert snap.period_count == 1
    assert snap.remaining == 2
    assert snap.soft_limit == 3


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text("{not-json", encoding="utf-8")
    ledger = WolframQuotaLedger(path, soft_limit=3)
    with pytest.raises(WolframQuotaError, match="invalid"):
        ledger.snapshot(datetime(2026, 8, 30, tzinfo=UTC))
    with pytest.raises(WolframQuotaError, match="invalid"):
        ledger.reserve_attempt(datetime(2026, 8, 30, tzinfo=UTC))


def test_wrong_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text('{"schema_version":2,"period_utc":"2026-08","attempt_count":1}', encoding="utf-8")
    with pytest.raises(WolframQuotaError, match="invalid"):
        WolframQuotaLedger(path, soft_limit=3).snapshot(datetime(2026, 8, 30, tzinfo=UTC))


def test_atomic_write_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    ledger = WolframQuotaLedger(path, soft_limit=3)
    ledger.reserve_attempt(datetime(2026, 8, 30, tzinfo=UTC))
    assert path.is_file()
    assert list(tmp_path.glob("usage.json.*.tmp")) == []


def test_two_threads_receive_unique_counts(tmp_path: Path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=10)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    counts: list[int] = []

    def reserve() -> None:
        counts.append(ledger.reserve_attempt(now).period_count)

    threads = [Thread(target=reserve) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(counts) == [1, 2, 3, 4, 5, 6]
    assert ledger.snapshot(now).period_count == 6
