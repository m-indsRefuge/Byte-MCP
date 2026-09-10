"""Provider-free local settings for NVIDIA routine code reviews."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .review_evidence import NvidiaReviewEvidenceStore

_REPOSITORIES_FILE_ENV = "BYTE_MCP_NVIDIA_REVIEW_REPOSITORIES_FILE"


@dataclass(frozen=True, slots=True)
class NvidiaReviewSettings:
    """Local-only configuration for the NVIDIA review service."""

    repositories_file: Path

    def __post_init__(self) -> None:
        if not isinstance(self.repositories_file, Path) or not self.repositories_file.is_absolute():
            raise ValueError("repositories_file must be an absolute path")

    @classmethod
    def load(cls, repo_root: Path) -> NvidiaReviewSettings:
        """Resolve local review configuration without reading provider credentials."""

        if not isinstance(repo_root, Path):
            raise ValueError("repo_root is invalid")
        explicit = os.getenv(_REPOSITORIES_FILE_ENV, "").strip()
        if explicit:
            repositories_file = Path(explicit)
        else:
            repositories_file = (
                NvidiaReviewEvidenceStore.from_environment().root / "review-repositories.json"
            )
        return cls(repositories_file.expanduser().resolve(strict=False))
