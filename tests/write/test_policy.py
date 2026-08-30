import json
from pathlib import Path

import pytest

from byte_mcp.errors import WriteConfigurationError
from byte_mcp.write.policy import WritePolicy, load_optional_write_policy


def test_missing_policy_disables_writes(tmp_path: Path) -> None:
    assert load_optional_write_policy(tmp_path / "missing.json") is None


def test_policy_rejects_unsupported_version(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(WriteConfigurationError, match="schema_version"):
        WritePolicy.load(path)


def test_policy_fingerprint_changes_when_authority_changes(write_policy_file: Path) -> None:
    original = WritePolicy.load(write_policy_file)
    raw = write_policy_file.read_text(encoding="utf-8")
    write_policy_file.write_text(
        raw.replace('"max_operations": 200', '"max_operations": 199'), encoding="utf-8"
    )
    changed = WritePolicy.load(write_policy_file)
    assert original.fingerprint != changed.fingerprint


def test_policy_rejects_unknown_key(write_policy_file: Path) -> None:
    payload = json.loads(write_policy_file.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    write_policy_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(write_policy_file)


def test_policy_rejects_missing_key(write_policy_file: Path) -> None:
    payload = json.loads(write_policy_file.read_text(encoding="utf-8"))
    del payload["max_patch_bytes"]
    write_policy_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(write_policy_file)


def test_policy_rejects_malformed_json_and_utf8(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(malformed)
    malformed.write_bytes(b"\xff")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(malformed)


def test_policy_rejects_duplicate_members(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    payload = json.dumps(
        {
            "schema_version": 1,
            "enabled": True,
            "root_alias": "projects",
            "protected_projects": ["Byte-MCP"],
            "allow_new_projects": True,
            "allow_cross_project_moves": False,
            "allow_binary_writes": True,
            "snapshot_existing": True,
            "delete_mode": "recoverable",
            "allow_permanent_delete": False,
            "require_prepare_commit": True,
            "allow_self_commit": True,
            "max_operations": 200,
            "max_file_bytes": 1_000_000,
            "max_staged_bytes": 20_000_000,
            "max_directory_entries": 20_000,
            "max_directory_bytes": 250_000_000,
            "max_patch_bytes": 1_000_000,
            "transaction_ttl_seconds": 900,
            "recovery_retention_days": 30,
            "recovery_max_bytes": 2_147_483_648,
        }
    )
    payload = payload.replace(
        '"allow_binary_writes": true',
        '"allow_binary_writes": true, "allow_binary_writes": false',
    )
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("root_alias", "other"),
        ("protected_projects", ["Other"]),
        ("delete_mode", "permanent"),
        ("allow_permanent_delete", True),
        ("allow_cross_project_moves", True),
        ("allow_binary_writes", True),
        ("enabled", False),
        ("snapshot_existing", "yes"),
    ],
)
def test_policy_rejects_unsafe_or_inconsistent_values(
    write_policy_file: Path, field: str, value: object
) -> None:
    payload = json.loads(write_policy_file.read_text(encoding="utf-8"))
    payload[field] = value
    write_policy_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(write_policy_file)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_operations", 0),
        ("max_file_bytes", -1),
        ("max_patch_bytes", True),
        ("transaction_ttl_seconds", "900"),
    ],
)
def test_policy_rejects_invalid_limits(
    write_policy_file: Path, field: str, value: object
) -> None:
    payload = json.loads(write_policy_file.read_text(encoding="utf-8"))
    payload[field] = value
    write_policy_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WriteConfigurationError):
        WritePolicy.load(write_policy_file)
