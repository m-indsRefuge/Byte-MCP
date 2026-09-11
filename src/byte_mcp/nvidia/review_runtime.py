"""Lazy, fail-isolated runtime for NVIDIA routine code reviews."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .review_service import NvidiaReviewService


@dataclass(slots=True)
class NvidiaReviewRuntime:
    service: NvidiaReviewService | None = None
    error_type: str | None = None

    @classmethod
    def load(cls, repo_root: Path) -> NvidiaReviewRuntime:
        """Load local review configuration without affecting core server startup."""
        try:
            service = NvidiaReviewService.initialize(repo_root)
        except (OSError, TypeError, ValueError) as error:
            return cls(error_type=type(error).__name__)
        return cls(service=service)

    def require_service(self) -> NvidiaReviewService:
        if self.service is None:
            raise ValueError("NVIDIA review runtime is unavailable")
        return self.service
