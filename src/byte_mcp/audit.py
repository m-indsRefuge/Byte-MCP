"""Append-only local audit logging."""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        *,
        outcome: str = "allowed",
        **fields: Any,
    ) -> None:
        event = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "action": action,
            "outcome": outcome,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
