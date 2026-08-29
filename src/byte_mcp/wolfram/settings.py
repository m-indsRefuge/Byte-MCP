"""Configuration for the bounded Wolfram capability."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from byte_mcp.errors import WolframConfigurationError

_ENDPOINT = "https://www.wolframalpha.com/api/v1/llm-api"


def _resolve_usage_file(repo_root: Path) -> Path:
    raw = os.getenv("BYTE_MCP_WOLFRAM_USAGE_FILE")
    if raw is None or not raw.strip():
        return (repo_root / "data" / "wolfram-usage.json").resolve()
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _load_soft_limit() -> int:
    raw = os.getenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "1800")
    try:
        value = int(raw)
    except ValueError as exc:
        raise WolframConfigurationError(
            "BYTE_MCP_WOLFRAM_SOFT_LIMIT must be an integer between 1 and 1800."
        ) from exc
    if not 1 <= value <= 1800:
        raise WolframConfigurationError(
            "BYTE_MCP_WOLFRAM_SOFT_LIMIT must be between 1 and 1800."
        )
    return value


@dataclass(frozen=True, slots=True, repr=False)
class WolframSettings:
    repo_root: Path
    usage_file: Path
    app_id: str | None
    endpoint: str = _ENDPOINT
    max_input_chars: int = 8_000
    min_response_chars: int = 250
    default_max_chars: int = 6_800
    max_response_chars: int = 6_800
    soft_monthly_limit: int = 1_800
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0

    @classmethod
    def load(cls, repo_root: Path) -> WolframSettings:
        app_id = os.getenv("WOLFRAM_APP_ID")
        app_id = app_id.strip() if app_id is not None else None
        if not app_id:
            app_id = None
        return cls(
            repo_root=repo_root.resolve(),
            usage_file=_resolve_usage_file(repo_root),
            app_id=app_id,
            soft_monthly_limit=_load_soft_limit(),
        )

    def apply_max_chars(self, requested: int | None) -> int:
        if requested is None:
            return self.default_max_chars
        return max(self.min_response_chars, min(int(requested), self.max_response_chars))

    def __repr__(self) -> str:
        return (
            "WolframSettings("
            f"repo_root={self.repo_root!r}, "
            f"usage_file={self.usage_file!r}, "
            f"app_id_configured={self.app_id is not None}, "
            f"endpoint={self.endpoint!r}, "
            f"soft_monthly_limit={self.soft_monthly_limit}"
            ")"
        )
