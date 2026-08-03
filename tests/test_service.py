import json
from pathlib import Path

import pytest

from byte_mcp.errors import AccessDeniedError, NotFoundError
from byte_mcp.service import FileService
from byte_mcp.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
    )


def read_audit(settings: Settings) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in settings.audit_file.read_text(encoding="utf-8").splitlines()
    ]


def test_search_then_fetch(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    report = approved / "cuda-smoke-report.txt"
    report.write_text(
        "Kernel result: 42\nPASS",
        encoding="utf-8",
    )

    service = FileService(
        make_settings(tmp_path),
        {"downloads": approved.resolve()},
    )

    search_result = service.search(
        "cuda",
        root="downloads",
    )
    assert len(search_result["results"]) == 1

    fetched = service.fetch(
        search_result["results"][0]["ref"]
    )
    assert fetched["content"] == (
        "Kernel result: 42\nPASS"
    )
    assert len(fetched["sha256"]) == 64


def test_content_search(tmp_path: Path) -> None:
    approved = tmp_path / "documents"
    approved.mkdir()
    (approved / "notes.md").write_text(
        "The compact baseline manifest is present.",
        encoding="utf-8",
    )

    service = FileService(
        make_settings(tmp_path),
        {"documents": approved.resolve()},
    )

    result = service.search(
        "baseline manifest",
        search_contents=True,
    )
    assert result["results"][0]["name"] == "notes.md"


def test_list_directory_excludes_blocked_material(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    (approved / "visible.txt").write_text("ok", encoding="utf-8")
    (approved / ".env").write_text("TEST_ONLY=1", encoding="utf-8")
    (approved / "test-only.key").write_text("not a key", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"downloads": approved.resolve()},
    )

    result = service.list_directory("downloads")
    names = {entry["name"] for entry in result["entries"]}

    assert names == {"visible.txt"}


def test_unknown_root_is_denied_and_audited(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    settings = make_settings(tmp_path)
    service = FileService(
        settings,
        {"downloads": approved.resolve()},
    )

    with pytest.raises(NotFoundError):
        service.list_directory("c_drive")

    event = read_audit(settings)[-1]
    assert event["action"] == "list_directory"
    assert event["outcome"] == "denied"
    assert event["error_type"] == "NotFoundError"


def test_parent_traversal_is_denied_and_audited(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    settings = make_settings(tmp_path)
    service = FileService(
        settings,
        {"downloads": approved.resolve()},
    )

    with pytest.raises(AccessDeniedError):
        service.list_directory("downloads", "../outside")

    event = read_audit(settings)[-1]
    assert event["action"] == "list_directory"
    assert event["outcome"] == "denied"
    assert event["error_type"] == "AccessDeniedError"


def test_search_audit_fingerprints_query_without_storing_it(tmp_path: Path) -> None:
    approved = tmp_path / "documents"
    approved.mkdir()
    settings = make_settings(tmp_path)
    service = FileService(
        settings,
        {"documents": approved.resolve()},
    )
    query = "private test phrase"

    service.search(query, root="documents")

    raw_audit = settings.audit_file.read_text(encoding="utf-8")
    event = read_audit(settings)[-1]
    assert query not in raw_audit
    assert event["action"] == "search"
    assert event["outcome"] == "allowed"
    assert event["query_length"] == len(query)
    assert len(str(event["query_sha256"])) == 64


def test_malformed_reference_is_denied_and_audited(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    settings = make_settings(tmp_path)
    service = FileService(
        settings,
        {"downloads": approved.resolve()},
    )

    with pytest.raises(AccessDeniedError):
        service.fetch("not-a-valid-reference")

    event = read_audit(settings)[-1]
    assert event["action"] == "fetch"
    assert event["outcome"] == "denied"
    assert event["error_type"] == "AccessDeniedError"
    assert "not-a-valid-reference" not in settings.audit_file.read_text(
        encoding="utf-8"
    )
