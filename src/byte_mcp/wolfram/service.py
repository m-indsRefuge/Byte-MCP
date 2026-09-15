"""Byte-owned orchestration for bounded Wolfram queries."""
from __future__ import annotations

import time
import uuid

from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframError, WolframRequestError
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import (
    WolframPurpose,
    WolframQueryRequest,
    WolframRouteReason,
)
from byte_mcp.wolfram.policy import WolframOutboundPolicy
from byte_mcp.wolfram.quota import WolframQuotaLedger
from byte_mcp.wolfram.settings import WolframSettings


class WolframService:
    def __init__(
        self,
        settings: WolframSettings,
        audit: AuditLog,
        policy: WolframOutboundPolicy,
        quota: WolframQuotaLedger,
        client: WolframLLMClient,
    ) -> None:
        self.settings = settings
        self.audit = audit
        self.policy = policy
        self.quota = quota
        self.client = client

    @staticmethod
    def _purpose(value: str) -> WolframPurpose:
        try:
            return WolframPurpose(value.strip().upper())
        except (AttributeError, ValueError) as exc:
            raise WolframRequestError("Unknown Wolfram purpose.") from exc

    @staticmethod
    def _route_reason(value: str) -> WolframRouteReason:
        try:
            return WolframRouteReason(value.strip().upper())
        except (AttributeError, ValueError) as exc:
            raise WolframRequestError("Unknown Wolfram route_reason.") from exc

    def query(
        self,
        input: str,
        max_chars: int | None,
        purpose: str,
        route_reason: str,
        source_finding_id: str | None = None,
    ) -> dict[str, object]:
        request = WolframQueryRequest(
            input=input,
            max_chars=max_chars,
            purpose=self._purpose(purpose),
            route_reason=self._route_reason(route_reason),
            source_finding_id=source_finding_id,
        )
        prepared = self.policy.prepare(request.input)
        applied_max = self.settings.apply_max_chars(request.max_chars)
        reservation = self.quota.reserve_attempt()
        request_id = f"WQ-{uuid.uuid4().hex}"

        base_audit = {
            "provider": "wolfram",
            "purpose": request.purpose.value,
            "route_reason": request.route_reason.value,
            "request_id": request_id,
            "input_sha256": prepared.sha256,
            "input_chars": prepared.original_chars,
            "transmitted_chars": prepared.transmitted_chars,
            "paths_sanitized": prepared.paths_sanitized,
            "max_chars_applied": applied_max,
            "period_utc": reservation.period_utc,
            "period_count": reservation.period_count,
        }
        if request.source_finding_id is not None:
            base_audit["source_finding_id"] = request.source_finding_id

        self.audit.record("wolfram_query", outcome="transmitting", **base_audit)
        started = time.monotonic()
        try:
            result = self.client.query(prepared.text, applied_max)
        except WolframError as exc:
            self.audit.record(
                "wolfram_query",
                outcome="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error_type=type(exc).__name__,
                **base_audit,
            )
            raise

        duration_ms = int((time.monotonic() - started) * 1000)
        result_text = result.result[:applied_max]
        response_at_limit = result.response_at_limit or len(result.result) > applied_max
        self.audit.record(
            "wolfram_query",
            outcome="allowed",
            response_chars=len(result_text),
            duration_ms=duration_ms,
            **base_audit,
        )
        return {
            "status": "success",
            "provider": "Wolfram|Alpha",
            "purpose": request.purpose.value,
            "route_reason": request.route_reason.value,
            "request_id": request_id,
            "result": result_text,
            "result_url": result.result_url,
            "response_chars": len(result_text),
            "response_at_limit": response_at_limit,
            "usage": {
                "local_period_utc": reservation.period_utc,
                "local_period_count": reservation.period_count,
                "soft_limit": reservation.soft_limit,
            },
        }
