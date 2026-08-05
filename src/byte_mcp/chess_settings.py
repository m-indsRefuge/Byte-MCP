"""Configuration for the isolated Byte-MCP chess capability."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from .errors import ByteMCPError

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SUPPORTED_TRANSPORTS = frozenset({"streamable-http"})
_ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ByteMCPError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ByteMCPError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _env_choice(name: str, default: str, choices: frozenset[str]) -> str:
    value = os.getenv(name, default).strip().casefold()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ByteMCPError(f"{name} must be one of: {allowed}.")
    return value


def _env_loopback_host(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().casefold()
    if value not in _LOOPBACK_HOSTS:
        raise ByteMCPError(
            f"{name} must remain loopback-only: 127.0.0.1, localhost, or ::1."
        )
    return value


def _resolve_path(repo_root: Path, variable: str, default: str) -> Path:
    raw = os.getenv(variable, default)
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _arena_base_url() -> str:
    value = os.getenv(
        "BYTE_MCP_CHESS_ARENA_BASE_URL",
        "http://127.0.0.1:8787/api/v1",
    ).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http":
        raise ByteMCPError("BYTE_MCP_CHESS_ARENA_BASE_URL must use http.")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        raise ByteMCPError("BYTE_MCP_CHESS_ARENA_BASE_URL must remain loopback-only.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ByteMCPError("BYTE_MCP_CHESS_ARENA_BASE_URL contains unsupported components.")
    if parsed.path.rstrip("/") != "/api/v1":
        raise ByteMCPError("BYTE_MCP_CHESS_ARENA_BASE_URL must end with /api/v1.")
    return value


def _match_id() -> UUID:
    raw = os.getenv("BYTE_MCP_CHESS_MATCH_ID", "").strip()
    if not raw:
        raise ByteMCPError("BYTE_MCP_CHESS_MATCH_ID is required.")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ByteMCPError("BYTE_MCP_CHESS_MATCH_ID must be a valid UUID.") from exc


def _actor() -> str:
    value = os.getenv("BYTE_MCP_CHESS_ACTOR", "byte").strip()
    if not _ACTOR_RE.fullmatch(value):
        raise ByteMCPError(
            "BYTE_MCP_CHESS_ACTOR must be 1-128 safe identity characters."
        )
    return value


@dataclass(frozen=True, slots=True)
class ChessSettings:
    repo_root: Path
    arena_base_url: str
    match_id: UUID
    actor: str
    audit_file: Path
    idempotency_file: Path
    request_timeout_seconds: int
    server_host: str = "127.0.0.1"
    server_port: int = 8001
    transport: str = "streamable-http"

    @property
    def mcp_url(self) -> str:
        host = f"[{self.server_host}]" if self.server_host == "::1" else self.server_host
        return f"http://{host}:{self.server_port}/mcp"

    @classmethod
    def load(cls) -> ChessSettings:
        repo_root = Path(__file__).resolve().parents[2]
        return cls(
            repo_root=repo_root,
            arena_base_url=_arena_base_url(),
            match_id=_match_id(),
            actor=_actor(),
            audit_file=_resolve_path(
                repo_root,
                "BYTE_MCP_CHESS_AUDIT_FILE",
                "data/chess-audit.jsonl",
            ),
            idempotency_file=_resolve_path(
                repo_root,
                "BYTE_MCP_CHESS_IDEMPOTENCY_FILE",
                "data/chess-idempotency.json",
            ),
            request_timeout_seconds=_env_int(
                "BYTE_MCP_CHESS_TIMEOUT_SECONDS",
                10,
                1,
                120,
            ),
            server_host=_env_loopback_host(
                "BYTE_MCP_CHESS_HOST",
                "127.0.0.1",
            ),
            server_port=_env_int(
                "BYTE_MCP_CHESS_PORT",
                8001,
                1024,
                65535,
            ),
            transport=_env_choice(
                "BYTE_MCP_CHESS_TRANSPORT",
                "streamable-http",
                _SUPPORTED_TRANSPORTS,
            ),
        )
