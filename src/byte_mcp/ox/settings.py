"""Fixed configuration for the clean-room OX provider path."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from byte_mcp.providers.transport import ProviderTimeoutPolicy

OX_REVIEW_ID_PREFIX = "OX-"
OX_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
OX_MODEL_ID = "zai/glm-5.3-flash"
OX_SNAPSHOT_POLICY_VERSION = "ox-snapshot-v1"
OX_PACKET_POLICY_VERSION = "ox-packet-v1"
OX_MAX_ARTIFACT_BYTES = 1_000_000
OX_MAX_ARTIFACTS = 5_000
OX_MAX_SNAPSHOT_CONTENT_BYTES = 3_250_000
OX_MAX_PACKET_BYTES = 3_500_000
OX_TIMEOUT_POLICY = ProviderTimeoutPolicy(
    connect_seconds=10.0,
    write_seconds=30.0,
    read_seconds=600.0,
    pool_seconds=10.0,
    absolute_deadline_seconds=600.0,
)


def _default_evidence_root() -> Path:
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Byte-MCP" / "ox"
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "byte-mcp" / "ox"


def _resolve_evidence_root(raw: str | None) -> Path:
    value = Path(os.path.expandvars(raw)).expanduser() if raw else _default_evidence_root()
    return value.resolve()


@dataclass(frozen=True, slots=True, repr=False)
class OXSettings:
    api_key: str | None = field(repr=False)
    evidence_root: Path

    def __repr__(self) -> str:
        return (
            "OXSettings("
            f"api_key_configured={self.api_key is not None}, evidence_root={self.evidence_root!r})"
        )

    @classmethod
    def load(cls) -> OXSettings:
        key = os.getenv("AI_GATEWAY_API_KEY", "").strip() or None
        evidence_root = _resolve_evidence_root(os.getenv("BYTE_MCP_OX_EVIDENCE_DIR"))
        return cls(api_key=key, evidence_root=evidence_root)
