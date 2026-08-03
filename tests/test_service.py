from pathlib import Path

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
