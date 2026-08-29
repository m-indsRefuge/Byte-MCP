"""Fail-isolated construction of the Wolfram capability."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframConfigurationError
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import WolframAvailability
from byte_mcp.wolfram.policy import WolframOutboundPolicy
from byte_mcp.wolfram.quota import WolframQuotaLedger
from byte_mcp.wolfram.service import WolframService
from byte_mcp.wolfram.settings import WolframSettings


@dataclass(frozen=True, slots=True)
class WolframRuntime:
    availability: WolframAvailability
    service: WolframService | None
    safe_error: str | None

    @classmethod
    def load(cls, repo_root: Path, audit: AuditLog) -> "WolframRuntime":
        try:
            settings = WolframSettings.load(repo_root)
        except WolframConfigurationError as exc:
            safe_error = str(exc)[:300]
            return cls(
                availability=WolframAvailability.MISCONFIGURED,
                service=None,
                safe_error=safe_error,
            )

        if settings.app_id is None:
            return cls(
                availability=WolframAvailability.DISABLED,
                service=None,
                safe_error=None,
            )

        policy = WolframOutboundPolicy(
            max_input_chars=settings.max_input_chars,
            user_profile=Path.home(),
        )
        quota = WolframQuotaLedger(settings.usage_file, settings.soft_monthly_limit)
        client = WolframLLMClient(settings)
        service = WolframService(settings, audit, policy, quota, client)
        return cls(
            availability=WolframAvailability.AVAILABLE,
            service=service,
            safe_error=None,
        )
