from pathlib import Path

from byte_mcp.service import FileService
from byte_mcp.settings import Settings


def _settings(tmp_path: Path, *, max_search_files: int = 1) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=max_search_files,
        content_search_max_bytes=100_000,
    )


def test_listed_file_ref_remains_fetchable_when_search_cap_blocks_discovery(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "projects"
    approved.mkdir()
    (approved / "a-first.txt").write_text("occupies the search budget", encoding="utf-8")
    target_dir = approved / "Byte-MCP" / "qualification" / "wolfram"
    target_dir.mkdir(parents=True)
    target = target_dir / "llm-api-v2.json"
    target.write_text('{"campaign_id":"wolfram-llm-api-v2"}', encoding="utf-8")

    service = FileService(
        _settings(tmp_path),
        {"projects": approved.resolve()},
    )

    search_result = service.search("llm-api-v2.json", root="projects")
    assert search_result["results"] == []
    assert search_result["scanned_files"] == 1
    assert search_result["truncated"] is True

    listing = service.list_directory(
        "projects",
        "Byte-MCP/qualification/wolfram",
    )
    entry = next(item for item in listing["entries"] if item["name"] == target.name)

    assert entry["kind"] == "file"
    assert isinstance(entry.get("ref"), str)
    assert entry["ref"]

    fetched = service.fetch(entry["ref"])
    assert fetched["relative_path"] == "Byte-MCP/qualification/wolfram/llm-api-v2.json"
    assert fetched["content"] == '{"campaign_id":"wolfram-llm-api-v2"}'
    assert len(fetched["sha256"]) == 64


def test_list_directory_does_not_issue_fetch_refs_for_directories(tmp_path: Path) -> None:
    approved = tmp_path / "projects"
    child = approved / "nested"
    child.mkdir(parents=True)

    service = FileService(
        _settings(tmp_path, max_search_files=10),
        {"projects": approved.resolve()},
    )

    listing = service.list_directory("projects")
    entry = next(item for item in listing["entries"] if item["name"] == "nested")

    assert entry["kind"] == "directory"
    assert "ref" not in entry
