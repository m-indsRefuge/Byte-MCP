import json
from pathlib import Path

from byte_mcp.audit import AuditLog


def test_audit_serializes_path_fields_defensively(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    audit = AuditLog(audit_file)
    sample_path = tmp_path / "sample.txt"

    audit.record("test", path=sample_path)

    event = json.loads(audit_file.read_text(encoding="utf-8"))
    assert event["path"] == str(sample_path)
