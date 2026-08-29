"""Safe orchestration for bounded Wolfram queries."""
from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from byte_mcp.audit import AuditLog
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import WolframQueryRequest
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

    def query(self, request: WolframQueryRequest) -> dict[str, object]:
        request_id = str(uuid4())
        max_chars = self.settings.apply_max_chars(request.max_chars)
        prepared = self.policy.prepare(request.input)
        reservation = self.quota.reserve_attempt()

        fields: dict[str, object] = {
            "provider": "wolfram",
            "purpose": request.purpose.value,
            "route_reason": request.route_reason.value,
            "request_id": request_id,
            "input_sha256": prepared.sha256,
            "input_chars": prepared.original_chars,
            "transmitted_chars": prepared.transmitted_chars,
            "paths_sanitized": prepared.paths_sanitized,
            "max_chars_applied": max_chars,
            "period_utc": reservation.period_utc,
            "period_count": reservation.period_count,
        }
        if request.source_finding_id is not None:
            fields["source_finding_id"] = request.source_finding_id

        self.audit.record("wolfram_query", outcome="transmitting", **fields)

        started = perf_counter()
        try:
            provider_result = self.client.query(prepared.text, max_chars)
        except Exception as exc:
            duration_ms = max(0, round((perf_counter() - started) * 1000))
            self.audit.record(
                "wolfram_query",
                outcome="error",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                **fields,
            )
            raise

        duration_ms = max(0, round((perf_counter() - started) * 1000))
        self.audit.record(
            "wolfram_query",
            outcome="success",
            response_chars=provider_result.response_chars,
            duration_ms=duration_ms,
            **fields,
        )

        return {
            "status": "success",
            "provider": "Wolfram|Alpha",
            "purpose": request.purpose.value,
            "route_reason": request.route_reason.value,
            "result": provider_result.text,
            "result_url": provider_result.result_url,
            "response_chars": provider_result.response_chars,
            "response_at_limit": provider_result.response_at_limit,
            "usage": {
                "local_period_utc": reservation.period_utc,
                "local_period_count": reservation.period_count,
                "soft_limit": reservation.soft_limit,
            },
        }
