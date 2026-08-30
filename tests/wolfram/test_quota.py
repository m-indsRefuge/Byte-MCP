from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from byte_mcp.errors import WolframQuotaError
from byte_mcp.wolfram.quota import WolframQuotaLedger


def test_quota_reserves_before_outbound_attempt(tmp_path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=2)
    now = datetime(2026, 8, 30, tzinfo=UTC)

    first = ledger.reserve_attempt(now)
    second = ledger.reserve_attempt(now)

    assert first.period_count == 1
    assert second.period_count == 2
    with pytest.raises(WolframQuotaError, match="soft limit"):
        ledger.reserve_attempt(now)


def test_quota_rolls_over_on_utc_month_boundary(tmp_path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=3)
    ledger.reserve_attempt(datetime(2026, 8, 31, 23, 59, tzinfo=UTC))
    snapshot = ledger.snapshot(datetime(2026, 9, 1, tzinfo=UTC))
    assert snapshot.period_utc == "2026-09"
    assert snapshot.period_count == 0


def test_malformed_ledger_fails_closed(tmp_path) -> None:
    path = tmp_path / "usage.json"
    path.write_text("{not-json", encoding="utf-8")
    ledger = WolframQuotaLedger(path, soft_limit=3)
    with pytest.raises(WolframQuotaError, match="malformed"):
        ledger.reserve_attempt(datetime(2026, 8, 30, tzinfo=UTC))


def test_reservations_are_serialized_across_threads(tmp_path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=20)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    with ThreadPoolExecutor(max_workers=5) as executor:
        counts = sorted(executor.map(lambda _: ledger.reserve_attempt(now).period_count, range(10)))
    assert counts == list(range(1, 11))
    assert ledger.snapshot(now).period_count == 10
    assert not (tmp_path / "usage.json.tmp").exists()
