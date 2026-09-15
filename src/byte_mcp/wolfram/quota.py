"""Conservative local quota accounting for Wolfram calls."""
from __future__ import annotations

import json
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from byte_mcp.errors import WolframQuotaError


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    period_utc: str
    period_count: int
    soft_limit: int


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    period_utc: str
    period_count: int
    soft_limit: int


class WolframQuotaLedger:
    def __init__(self, path: Path, soft_limit: int) -> None:
        if soft_limit < 1:
            raise WolframQuotaError("Wolfram soft limit must be positive.")
        self.path = path
        self.soft_limit = soft_limit
        self._lock = threading.Lock()

    @staticmethod
    def _period(now: datetime) -> str:
        value = now.astimezone(UTC)
        return f"{value.year:04d}-{value.month:02d}"

    def _read(self, period: str) -> int:
        if not self.path.exists():
            return 0
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WolframQuotaError("Wolfram usage ledger is malformed or unreadable.") from exc
        if payload.get("schema_version") != 1:
            raise WolframQuotaError("Wolfram usage ledger schema is unsupported.")
        stored_period = payload.get("period_utc")
        count = payload.get("attempt_count")
        if not isinstance(stored_period, str) or not isinstance(count, int) or count < 0:
            raise WolframQuotaError("Wolfram usage ledger is malformed or unreadable.")
        return count if stored_period == period else 0

    def _write(self, period: str, count: int) -> None:
        payload = {
            "schema_version": 1,
            "period_utc": period,
            "attempt_count": count,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except OSError as exc:
            with suppress(OSError):
                temp.unlink(missing_ok=True)
            raise WolframQuotaError("Wolfram usage ledger could not be persisted.") from exc

    def reserve_attempt(self, now: datetime | None = None) -> QuotaReservation:
        current = now or datetime.now(UTC)
        period = self._period(current)
        with self._lock:
            count = self._read(period)
            if count >= self.soft_limit:
                raise WolframQuotaError("Local Wolfram monthly soft limit reached.")
            count += 1
            self._write(period, count)
            return QuotaReservation(period, count, self.soft_limit)

    def snapshot(self, now: datetime | None = None) -> QuotaSnapshot:
        current = now or datetime.now(UTC)
        period = self._period(current)
        with self._lock:
            count = self._read(period)
        return QuotaSnapshot(period, count, self.soft_limit)
