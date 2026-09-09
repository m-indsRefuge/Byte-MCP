"""Durable evidence contracts for the governed NVIDIA canary lifecycle."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from byte_mcp.errors import ByteMCPError

NVIDIA_CANARY_SCHEMA = "byte-mcp-nvidia-canary-v1"
NVIDIA_CANARY_ID_PATTERN = r"NVC-[0-9]{6}"
_MAX_PREPARED_BODY_BYTES = 4_000_000
_CANARY_ID = re.compile(rf"{NVIDIA_CANARY_ID_PATTERN}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}\Z")

_NVIDIA_PROVIDER_ID = "nvidia-api-catalog"
_NVIDIA_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
_NVIDIA_METHOD = "POST"
_NVIDIA_TARGET_ORIGIN = "https://integrate.api.nvidia.com"
_NVIDIA_ENDPOINT_PATH = "/v1/chat/completions"


def _require_aware_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    return value


def _require_digest(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class NvidiaCanaryManifest:
    schema: str
    canary_id: str
    provider_id: str
    model_id: str
    method: str
    target_origin: str
    endpoint_path: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    probe_expected_text: str
    qualified_predecessor_sha: str

    def __post_init__(self) -> None:
        if self.schema != NVIDIA_CANARY_SCHEMA:
            raise ValueError("schema is invalid")
        if not isinstance(self.canary_id, str) or _CANARY_ID.fullmatch(self.canary_id) is None:
            raise ValueError("canary_id is invalid")
        if self.provider_id != _NVIDIA_PROVIDER_ID:
            raise ValueError("provider_id is invalid")
        if self.model_id != _NVIDIA_MODEL_ID:
            raise ValueError("model_id is invalid")
        if self.method != _NVIDIA_METHOD:
            raise ValueError("method is invalid")
        if self.target_origin != _NVIDIA_TARGET_ORIGIN:
            raise ValueError("target_origin is invalid")
        if self.endpoint_path != _NVIDIA_ENDPOINT_PATH:
            raise ValueError("endpoint_path is invalid")
        _require_digest(self.payload_sha256, "payload_sha256", _SHA256)
        _require_digest(self.request_sha256, "request_sha256", _SHA256)
        if (
            isinstance(self.body_bytes, bool)
            or not isinstance(self.body_bytes, int)
            or not 1 <= self.body_bytes <= _MAX_PREPARED_BODY_BYTES
        ):
            raise ValueError("body_bytes is invalid")
        _require_aware_timestamp(self.prepared_at, "prepared_at")
        if not isinstance(self.probe_expected_text, str) or not self.probe_expected_text:
            raise ValueError("probe_expected_text is invalid")
        _require_digest(self.qualified_predecessor_sha, "qualified_predecessor_sha", _GIT_SHA1)


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanarySnapshot:
    manifest: NvidiaCanaryManifest
    request_body: bytes = field(repr=False)
    events: tuple[dict[str, object], ...]
    authorized_at: str | None
    provider_started_at: str | None
    terminal_event: dict[str, object] | None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, NvidiaCanaryManifest):
            raise ValueError("manifest is invalid")
        if not isinstance(self.request_body, bytes):
            raise ValueError("request_body is invalid")
        if not isinstance(self.events, tuple) or any(not isinstance(event, dict) for event in self.events):
            raise ValueError("events are invalid")
        if self.authorized_at is not None:
            _require_aware_timestamp(self.authorized_at, "authorized_at")
        if self.provider_started_at is not None:
            _require_aware_timestamp(self.provider_started_at, "provider_started_at")
        if self.terminal_event is not None and not isinstance(self.terminal_event, dict):
            raise ValueError("terminal_event is invalid")

    def __repr__(self) -> str:
        return (
            "NvidiaCanarySnapshot("
            f"manifest={self.manifest!r}, request_body_bytes={len(self.request_body)!r}, "
            f"events={len(self.events)!r}, authorized_at={self.authorized_at!r}, "
            f"provider_started_at={self.provider_started_at!r}, "
            f"terminal_event_present={self.terminal_event is not None!r})"
        )


class NvidiaCanaryEvidenceError(ByteMCPError):
    """Raised when durable NVIDIA canary evidence is invalid or unavailable."""


class NvidiaCanaryLockError(ByteMCPError):
    """Raised when exclusive NVIDIA canary ownership cannot be acquired safely."""


class NvidiaCanaryEvidenceStore:
    """Resolve the local NVIDIA canary evidence root without touching credentials."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise ValueError("root is invalid")
        self.root = root.expanduser().resolve(strict=False)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        platform_name: str | None = None,
        home: Path | None = None,
    ) -> NvidiaCanaryEvidenceStore:
        environment = os.environ if environ is None else environ
        platform = sys.platform if platform_name is None else platform_name
        home_path = Path.home() if home is None else home

        explicit = environment.get("BYTE_MCP_NVIDIA_EVIDENCE_DIR", "").strip()
        if explicit:
            return cls(Path(explicit))

        if platform == "win32":
            local_app_data = environment.get("LOCALAPPDATA", "").strip()
            base = Path(local_app_data) if local_app_data else home_path / "AppData" / "Local"
            return cls(base / "Byte-MCP" / "nvidia")

        xdg_data_home = environment.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg_data_home) if xdg_data_home else home_path / ".local" / "share"
        return cls(base / "byte-mcp" / "nvidia")
