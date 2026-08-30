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
