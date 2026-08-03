"""Configuration loading for Byte-MCP."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ByteMCPError

_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _resolve_config_path(repo_root: Path, variable: str, default: str) -> Path:
    raw = os.getenv(variable, default)
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ByteMCPError(f"{name} must be between {minimum} and {maximum}.")
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
        )


def load_roots(settings: Settings) -> dict[str, Path]:
    if not settings.roots_file.is_file():
        raise ByteMCPError(f"Roots configuration is missing: {settings.roots_file}")

    payload = json.loads(settings.roots_file.read_text(encoding="utf-8"))
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

        path = Path(os.path.expandvars(raw_path)).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ByteMCPError(f"Approved root is not a directory: {path}")
        roots[alias] = path

    return roots
