"""Fail-isolated construction of the Wolfram capability."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframConfigurationError, WolframUnavailableError
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import WolframAvailability
from byte_mcp.wolfram.policy import WolframOutboundPolicy
from byte_mcp.wolfram.quota import WolframQuotaLedger
from byte_mcp.wolfram.service import WolframService
from byte_mcp.wolfram.settings import WolframSettings


@dataclass(slots=True)
class WolframRuntime:
    availability: WolframAvailability
    service: WolframService | None = None
    error: str | None = None

    @classmethod
    def load(cls, repo_root: Path, audit: AuditLog) -> WolframRuntime:
        try:
            settings = WolframSettings.load(repo_root)
        except WolframConfigurationError as exc:
            return cls(WolframAvailability.MISCONFIGURED, error=str(exc))

        if settings.app_id is None:
            return cls(WolframAvailability.DISABLED)

        policy = WolframOutboundPolicy(max_input_chars=settings.max_input_chars)
        quota = WolframQuotaLedger(settings.usage_file, settings.soft_monthly_limit)
        client = WolframLLMClient(settings)
        service = WolframService(settings, audit, policy, quota, client)
        return cls(WolframAvailability.AVAILABLE, service=service)

    def require_service(self) -> WolframService:
        if self.service is not None:
            return self.service
        if self.availability is WolframAvailability.MISCONFIGURED:
            raise WolframConfigurationError(self.error or "Wolfram configuration is invalid.")
        raise WolframUnavailableError("Wolfram AppID is not configured.")
