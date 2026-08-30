"""Configuration loading for Byte-MCP."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ByteMCPError

_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SUPPORTED_TRANSPORTS = frozenset({"streamable-http"})


def _resolve_config_path(repo_root: Path, variable: str, default: str) -> Path:
    raw = os.getenv(variable, default)
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


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
            f"{name} must remain loopback-only in V1: "
            "127.0.0.1, localhost, or ::1."
        )
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    repo_root: Path
    roots_file: Path
    audit_file: Path
    max_file_bytes: int
    max_response_chars: int
    max_search_files: int
    content_search_max_bytes: int
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    transport: str = "streamable-http"
    write_policy_file: Path | None = None
    write_state_dir: Path | None = None

    @property
    def mcp_url(self) -> str:
        host = f"[{self.server_host}]" if self.server_host == "::1" else self.server_host
        return f"http://{host}:{self.server_port}/mcp"

    @classmethod
    def load(cls) -> Settings:
        repo_root = Path(__file__).resolve().parents[2]
        return cls(
            repo_root=repo_root,
            roots_file=_resolve_config_path(
                repo_root,
                "BYTE_MCP_ROOTS_FILE",
                "config/roots.local.json",
            ),
            audit_file=_resolve_config_path(
                repo_root,
                "BYTE_MCP_AUDIT_FILE",
                "data/audit.jsonl",
            ),
            max_file_bytes=_env_int(
                "BYTE_MCP_MAX_FILE_BYTES",
                10_000_000,
                1_024,
                100_000_000,
            ),
            max_response_chars=_env_int(
                "BYTE_MCP_MAX_RESPONSE_CHARS",
                60_000,
                1_000,
                500_000,
            ),
            max_search_files=_env_int(
                "BYTE_MCP_MAX_SEARCH_FILES",
                20_000,
                100,
                500_000,
            ),
            content_search_max_bytes=_env_int(
                "BYTE_MCP_CONTENT_SEARCH_MAX_BYTES",
                1_000_000,
                1_024,
                10_000_000,
            ),
            server_host=_env_loopback_host(
                "BYTE_MCP_HOST",
                "127.0.0.1",
            ),
            server_port=_env_int(
                "BYTE_MCP_PORT",
                8000,
                1024,
                65535,
            ),
            transport=_env_choice(
                "BYTE_MCP_TRANSPORT",
                "streamable-http",
                _SUPPORTED_TRANSPORTS,
            ),
            write_policy_file=_resolve_config_path(
                repo_root,
                "BYTE_MCP_WRITE_POLICY_FILE",
                "~/.byte-mcp/write/policy.json",
            ),
            write_state_dir=_resolve_config_path(
                repo_root,
                "BYTE_MCP_WRITE_STATE_DIR",
                "~/.byte-mcp/write/state",
            ),
        )


def load_roots(settings: Settings) -> dict[str, Path]:
    if not settings.roots_file.is_file():
        raise ByteMCPError(f"Roots configuration is missing: {settings.roots_file}")

    try:
        raw = settings.roots_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ByteMCPError(
            f"Roots configuration cannot be read as UTF-8: {settings.roots_file}"
        ) from exc
    except OSError as exc:
        raise ByteMCPError(
            f"Roots configuration cannot be read: {settings.roots_file}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ByteMCPError(
            f"Roots configuration contains invalid JSON: {settings.roots_file}"
        ) from exc

    raw_roots = payload.get("roots")
    if not isinstance(raw_roots, dict) or not raw_roots:
        raise ByteMCPError(
            "roots.local.json must contain a non-empty 'roots' object."
        )

    roots: dict[str, Path] = {}
    for alias, raw_path in raw_roots.items():
        if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
            raise ByteMCPError(f"Invalid root alias: {alias!r}")
        if not isinstance(raw_path, str):
            raise ByteMCPError(f"Root path for {alias!r} must be a string.")

        try:
            path = Path(os.path.expandvars(raw_path)).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ByteMCPError(
                f"Approved root cannot be resolved for {alias!r}: {raw_path}"
            ) from exc

        if not path.is_dir():
            raise ByteMCPError(f"Approved root is not a directory: {path}")
        roots[alias] = path

    return roots
