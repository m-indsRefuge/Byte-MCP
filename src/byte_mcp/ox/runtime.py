"""Lazy, fail-isolated construction of the clean-room OX review service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from byte_mcp.errors import ByteMCPError, OXConfigurationError
from byte_mcp.ox.evidence import OXEvidenceStore
from byte_mcp.ox.scope import OXScopeResolver
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OXSettings, _resolve_evidence_root
from byte_mcp.settings import Settings


@dataclass(slots=True)
class OXRuntime:
    """Construct OX from existing root authority without loading provider credentials."""

    service: OXReviewService | None = None
    error_type: str | None = None

    @classmethod
    def load(cls, settings: Settings, roots: Mapping[str, Path]) -> OXRuntime:
        """Build local OX state lazily while containing configuration failures."""
        try:
            if not isinstance(settings, Settings):
                raise TypeError("settings must be Settings")
            if not isinstance(roots, Mapping):
                raise TypeError("roots must be a mapping")

            projects_root = roots["projects"]
            evidence_root = _resolve_evidence_root(os.getenv("BYTE_MCP_OX_EVIDENCE_DIR"))
            review_service = OXReviewService(
                scope_resolver=OXScopeResolver(projects_root),
                evidence_store=OXEvidenceStore(evidence_root),
                settings_loader=OXSettings.load,
            )
        except (ByteMCPError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            return cls(error_type=type(error).__name__)
        return cls(service=review_service)

    def require_service(self) -> OXReviewService:
        if self.service is None:
            raise OXConfigurationError("OX runtime is unavailable.")
        return self.service
