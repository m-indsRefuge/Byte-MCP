"""Strict, operator-controlled policy for Byte-MCP writes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import WriteConfigurationError

_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "enabled",
        "root_alias",
        "protected_projects",
        "allow_new_projects",
        "allow_cross_project_moves",
        "allow_binary_writes",
        "snapshot_existing",
        "delete_mode",
        "allow_permanent_delete",
        "require_prepare_commit",
        "allow_self_commit",
        "max_operations",
        "max_file_bytes",
        "max_staged_bytes",
        "max_directory_entries",
        "max_directory_bytes",
        "max_patch_bytes",
        "transaction_ttl_seconds",
        "recovery_retention_days",
        "recovery_max_bytes",
    }
)
_BOUNDED_LIMITS = {
    "max_operations": (1, 10_000),
    "max_file_bytes": (1, 100_000_000),
    "max_staged_bytes": (1, 1_000_000_000),
    "max_directory_entries": (1, 1_000_000),
    "max_directory_bytes": (1, 10_000_000_000),
    "max_patch_bytes": (1, 100_000_000),
    "transaction_ttl_seconds": (1, 86_400),
    "recovery_retention_days": (1, 3_650),
    "recovery_max_bytes": (1, 100_000_000_000),
}


@dataclass(frozen=True, slots=True)
class WritePolicy:
    schema_version: int
    enabled: bool
    root_alias: str
    protected_projects: tuple[str, ...]
    allow_new_projects: bool
    allow_cross_project_moves: bool
    allow_binary_writes: bool
    snapshot_existing: bool
    delete_mode: str
    allow_permanent_delete: bool
    require_prepare_commit: bool
    allow_self_commit: bool
    max_operations: int
    max_file_bytes: int
    max_staged_bytes: int
    max_directory_entries: int
    max_directory_bytes: int
    max_patch_bytes: int
    transaction_ttl_seconds: int
    recovery_retention_days: int
    recovery_max_bytes: int
    _fingerprint: str

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @classmethod
    def load(cls, path: Path) -> WritePolicy:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw, object_pairs_hook=_reject_duplicate_members)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WriteConfigurationError(
                "write policy cannot be read as valid UTF-8 JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise WriteConfigurationError("write policy must be a JSON object")
        if payload.get("schema_version") != 1:
            raise WriteConfigurationError("schema_version must be 1")
        if set(payload) != _POLICY_KEYS:
            raise WriteConfigurationError("write policy keys are incomplete or unsupported")
        _validate(payload)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return cls(
            schema_version=payload["schema_version"],
            enabled=payload["enabled"],
            root_alias=payload["root_alias"],
            protected_projects=tuple(payload["protected_projects"]),
            allow_new_projects=payload["allow_new_projects"],
            allow_cross_project_moves=payload["allow_cross_project_moves"],
            allow_binary_writes=payload["allow_binary_writes"],
            snapshot_existing=payload["snapshot_existing"],
            delete_mode=payload["delete_mode"],
            allow_permanent_delete=payload["allow_permanent_delete"],
            require_prepare_commit=payload["require_prepare_commit"],
            allow_self_commit=payload["allow_self_commit"],
            max_operations=payload["max_operations"],
            max_file_bytes=payload["max_file_bytes"],
            max_staged_bytes=payload["max_staged_bytes"],
            max_directory_entries=payload["max_directory_entries"],
            max_directory_bytes=payload["max_directory_bytes"],
            max_patch_bytes=payload["max_patch_bytes"],
            transaction_ttl_seconds=payload["transaction_ttl_seconds"],
            recovery_retention_days=payload["recovery_retention_days"],
            recovery_max_bytes=payload["recovery_max_bytes"],
            _fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )


def _validate(payload: dict[str, Any]) -> None:
    if payload["schema_version"] != 1:
        raise WriteConfigurationError("schema_version must be 1")
    if payload["enabled"] is not True:
        raise WriteConfigurationError("enabled must be true to enable writes")
    if payload["root_alias"] != "projects":
        raise WriteConfigurationError("root_alias must be projects")
    protected = payload["protected_projects"]
    if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
        raise WriteConfigurationError("protected_projects must be a list of project names")
    if not any(item.casefold() == "byte-mcp" for item in protected):
        raise WriteConfigurationError("protected_projects must include Byte-MCP")
    for key in (
        "allow_new_projects",
        "allow_cross_project_moves",
        "allow_binary_writes",
        "snapshot_existing",
        "allow_permanent_delete",
        "require_prepare_commit",
        "allow_self_commit",
    ):
        if not isinstance(payload[key], bool):
            raise WriteConfigurationError(f"{key} must be boolean")
    if payload["delete_mode"] != "recoverable":
        raise WriteConfigurationError("delete_mode must be recoverable")
    if (
        payload["allow_permanent_delete"]
        or payload["allow_cross_project_moves"]
        or payload["allow_binary_writes"]
    ):
        raise WriteConfigurationError("policy requests unsupported write authority")
    for key, (minimum, maximum) in _BOUNDED_LIMITS.items():
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise WriteConfigurationError(f"{key} must be between {minimum} and {maximum}")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WriteConfigurationError("write policy contains duplicate JSON members")
        result[key] = value
    return result


def load_optional_write_policy(path: Path) -> WritePolicy | None:
    try:
        path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WriteConfigurationError("write policy cannot be accessed") from exc
    return WritePolicy.load(path)
