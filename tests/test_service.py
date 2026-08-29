import json
from pathlib import Path

import pytest

from byte_mcp.errors import (
    AccessDeniedError,
    ByteMCPError,
    LimitExceededError,
    NotFoundError,
    UnsupportedFileError,
)
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

    fetched = service.fetch(search_result["results"][0]["ref"])
    assert fetched["content"] == "Kernel result: 42\nPASS"
    assert len(fetched["sha256"]) == 64


def test_fetch_enforces_configured_file_size_limit(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    report = approved / "large.txt"
    report.write_text("abcdef", encoding="utf-8")
    settings = Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=5,
        max_response_chars=60_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
    )
    service = FileService(settings, {"downloads": approved.resolve()})
    reference = service.search("large", root="downloads")["results"][0]["ref"]

    with pytest.raises(LimitExceededError, match="V1 limit"):
        service.fetch(reference)


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


def test_content_search_skips_corrupt_supported_files(tmp_path: Path) -> None:
    approved = tmp_path / "documents"
    approved.mkdir()
    (approved / "a-corrupt.zip").write_bytes(b"not a zip archive")
    (approved / "b-notes.txt").write_text(
        "target phrase is here",
        encoding="utf-8",
    )

    service = FileService(
        make_settings(tmp_path),
        {"documents": approved.resolve()},
    )

    result = service.search(
        "target phrase",
        root="documents",
        search_contents=True,
    )

    assert [item["name"] for item in result["results"]] == ["b-notes.txt"]


def test_fetch_normalizes_corrupt_document_errors(tmp_path: Path) -> None:
    approved = tmp_path / "documents"
    approved.mkdir()
    corrupt = approved / "corrupt.zip"
    corrupt.write_bytes(b"not a zip archive")

    service = FileService(
        make_settings(tmp_path),
        {"documents": approved.resolve()},
    )
    reference = service.search("corrupt", root="documents")["results"][0]["ref"]

    with pytest.raises(UnsupportedFileError, match="Extraction failed"):
        service.fetch(reference)


def test_search_scan_count_never_exceeds_configured_cap(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (approved / name).write_text("ok", encoding="utf-8")

    settings = Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=2,
        content_search_max_bytes=100_000,
    )
    service = FileService(
        settings,
        {"projects": approved.resolve()},
    )

    result = service.search("missing", root="projects")

    assert result["scanned_files"] == 2
    assert result["truncated"] is True
    event = read_audit(settings)[-1]
    assert event["scanned"] == 2


def test_search_exact_result_bound_is_not_truncated(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    for name in ("match-a.txt", "match-b.txt"):
        (approved / name).write_text("ok", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    result = service.search("match", root="projects", max_results=2)

    assert len(result["results"]) == 2
    assert result["truncated"] is False


def test_search_more_than_result_bound_is_truncated(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    for name in ("match-a.txt", "match-b.txt", "match-c.txt"):
        (approved / name).write_text("ok", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    result = service.search("match", root="projects", max_results=2)

    assert len(result["results"]) == 2
    assert result["truncated"] is True


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


def test_list_directory_exact_entry_bound_is_not_truncated(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    for name in ("a.txt", "b.txt"):
        (approved / name).write_text("ok", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"downloads": approved.resolve()},
    )

    result = service.list_directory("downloads", max_entries=2)

    assert len(result["entries"]) == 2
    assert result["truncated"] is False


def test_list_directory_skips_entry_that_vanishes_during_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    (approved / "stable.txt").write_text("ok", encoding="utf-8")
    vanished = approved / "vanished.txt"
    vanished.write_text("gone", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"downloads": approved.resolve()},
    )
    original_stat = Path.stat

    def fake_stat(self: Path, *, follow_symlinks: bool = True):  # type: ignore[no-untyped-def]
        if self == vanished:
            raise FileNotFoundError(self)
        return original_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", fake_stat)

    result = service.list_directory("downloads")

    assert [entry["name"] for entry in result["entries"]] == ["stable.txt"]


def test_list_roots_does_not_expose_absolute_paths(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    result = service.list_roots()

    assert result["roots"] == [{"alias": "projects"}]


def test_search_metadata_does_not_expose_absolute_paths(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    report = approved / "status.txt"
    report.write_text("ok", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    result = service.search("status", root="projects")
    metadata = result["results"][0]

    assert "absolute_path" not in metadata
    assert metadata["relative_path"] == "status.txt"


def test_fetch_metadata_does_not_expose_absolute_paths(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    report = approved / "status.txt"
    report.write_text("ok", encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    search_result = service.search("status", root="projects")
    fetched = service.fetch(search_result["results"][0]["ref"])

    assert "absolute_path" not in fetched
    assert fetched["relative_path"] == "status.txt"


def test_fetch_reports_applied_character_limit(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    report = approved / "status.txt"
    report.write_text("x" * 2_000, encoding="utf-8")

    service = FileService(
        make_settings(tmp_path),
        {"projects": approved.resolve()},
    )

    reference = service.search("status", root="projects")["results"][0]["ref"]
    fetched = service.fetch(reference, max_chars=200)

    assert fetched["max_chars_applied"] == 1_000
    assert len(fetched["content"]) == 1_000
    assert fetched["content_truncated"] is True


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


def test_audit_write_failure_is_fail_closed_domain_error(tmp_path: Path) -> None:
    approved = tmp_path / "downloads"
    approved.mkdir()
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    settings = make_settings(tmp_path)
    settings = Settings(
        repo_root=settings.repo_root,
        roots_file=settings.roots_file,
        audit_file=blocked_parent / "audit.jsonl",
        max_file_bytes=settings.max_file_bytes,
        max_response_chars=settings.max_response_chars,
        max_search_files=settings.max_search_files,
        content_search_max_bytes=settings.content_search_max_bytes,
    )
    service = FileService(settings, {"downloads": approved.resolve()})

    with pytest.raises(ByteMCPError, match="Audit persistence failed"):
        service.list_roots()
