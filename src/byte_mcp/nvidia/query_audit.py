"""Metadata-only audit events for governed NVIDIA queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


class NvidiaQueryAuditRecorder(Protocol):
    def record(
        self,
        action: str,
        *,
        outcome: str = "allowed",
        **fields: object,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NvidiaQueryAuditEvent:
    surface: str
    model_alias: str | None
    provider_model_id: str | None
    request_sha256: str | None
    provider_started: bool
    status_code: int | None
    finish_reason: str | None
    request_bytes: int | None
    response_bytes: int | None
    duration_ms: int
    outcome: str
    error_code: str | None = None


def record_nvidia_query_audit(
    audit: NvidiaQueryAuditRecorder | None,
    event: NvidiaQueryAuditEvent,
) -> None:
    """Persist only bounded operational metadata; never prompt/response text."""
    if audit is None:
        return
    fields = asdict(event)
    outcome = str(fields.pop("outcome"))
    audit.record("nvidia_query", outcome=outcome, **fields)
