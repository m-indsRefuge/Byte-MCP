"""Conservative local accounting for Wolfram outbound attempts."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from byte_mcp.errors import WolframQuotaError

_SCHEMA_VERSION = 1


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
    remaining: int


class WolframQuotaLedger:
    def __init__(self, path: Path, soft_limit: int) -> None:
        if soft_limit < 1:
            raise WolframQuotaError("Wolfram soft limit must be positive.")
        self.path = path
        self.soft_limit = soft_limit
        self._lock = threading.Lock()

    @staticmethod
    def _period(now: datetime | None) -> str:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        return f"{current.year:04d}-{current.month:02d}"

    def _read(self, current_period: str) -> tuple[str, int]:
        if not self.path.exists():
            return current_period, 0
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WolframQuotaError("Wolfram quota ledger is invalid.") from exc

        if not isinstance(payload, dict):
            raise WolframQuotaError("Wolfram quota ledger is invalid.")
        if set(payload) != {"schema_version", "period_utc", "attempt_count"}:
            raise WolframQuotaError("Wolfram quota ledger is invalid.")
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise WolframQuotaError("Wolfram quota ledger is invalid.")
        period = payload.get("period_utc")
        count = payload.get("attempt_count")
        if not isinstance(period, str) or len(period) != 7:
            raise WolframQuotaError("Wolfram quota ledger is invalid.")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise WolframQuotaError("Wolfram quota ledger is invalid.")
        if period != current_period:
            return current_period, 0
        return period, count

    def _write(self, period: str, count: int) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "period_utc": period,
            "attempt_count": count,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except OSError as exc:
            raise WolframQuotaError("Wolfram quota ledger persistence failed.") from exc
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def reserve_attempt(self, now: datetime | None = None) -> QuotaReservation:
        period = self._period(now)
        with self._lock:
            _, count = self._read(period)
            if count >= self.soft_limit:
                raise WolframQuotaError("Wolfram local soft quota is exhausted for this UTC month.")
            count += 1
            self._write(period, count)
            return QuotaReservation(period, count, self.soft_limit)

    def snapshot(self, now: datetime | None = None) -> QuotaSnapshot:
        period = self._period(now)
        with self._lock:
            _, count = self._read(period)
            return QuotaSnapshot(
                period_utc=period,
                period_count=count,
                soft_limit=self.soft_limit,
                remaining=max(0, self.soft_limit - count),
            )
