"""Append-only local audit logging."""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import AuditError


class AuditLog:
    """Single-process append-only JSONL audit trail.

    V1 intentionally uses an in-process lock only. Multiple Byte-MCP processes
    must not share the same audit file. Rotation is also deferred to a later
    version; operators should monitor the configured file size.
    """

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

        try:
            payload = json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)

            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except (OSError, TypeError, ValueError, RecursionError) as exc:
            raise AuditError("Audit persistence failed.") from exc
