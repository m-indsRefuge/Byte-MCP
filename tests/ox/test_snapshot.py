from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from byte_mcp.errors import OXBundleError
from byte_mcp.ox import snapshot as snapshot_module
from byte_mcp.ox.models import OXReviewMode, OXReviewScope
from byte_mcp.ox.scope import OXResolvedRepository
from byte_mcp.ox.settings import (
    OX_MAX_ARTIFACT_BYTES,
    OX_MAX_ARTIFACTS,
    OX_MAX_SNAPSHOT_CONTENT_BYTES,
    OX_SNAPSHOT_POLICY_VERSION,
)
from byte_mcp.ox.snapshot import freeze_snapshot


def _repository(tmp_path: Path) -> tuple[Path, OXResolvedRepository]:
    path = tmp_path / "example"
    path.mkdir()
    return path, OXResolvedRepository(alias="example", path=path.resolve())


def _full_scope() -> OXReviewScope:
    return OXReviewScope(
        repository="example",
        mode=OXReviewMode.FULL_REPOSITORY,
        paths=(),
        objective="Review the complete current repository",
    )


def _bounded_scope(*paths: str) -> OXReviewScope:
    return OXReviewScope(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        paths=paths,
        objective="Review the selected current repository material",
    )


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repository(repository: Path) -> None:
    _git(repository, "init")
    _git(repository, "config", "user.email", "snapshot-tests@example.invalid")
    _git(repository, "config", "user.name", "Snapshot Tests")


def _artifact_map(snapshot: object) -> dict[str, bytes]:
    return {artifact.logical_path: artifact.content for artifact in snapshot.artifacts}


def _exclusion_paths(snapshot: object) -> set[str]:
    return {exclusion.logical_path for exclusion in snapshot.exclusions}


def test_snapshot_uses_current_filesystem_bytes_for_tracked_staged_and_untracked_files(
    tmp_path: Path,
) -> None:
    repository_path, repository = _repository(tmp_path)
    _init_git_repository(repository_path)

    tracked = repository_path / "tracked.txt"
    tracked.write_bytes(b"committed\n")
    _git(repository_path, "add", "tracked.txt")
    _git(repository_path, "commit", "-m", "initial")

    tracked.write_bytes(b"current unstaged bytes\n")
    staged = repository_path / "staged.txt"
    staged.write_bytes(b"current staged bytes\n")
    _git(repository_path, "add", "staged.txt")
    untracked = repository_path / "untracked.txt"
    untracked.write_bytes(b"current untracked bytes\n")

    snapshot = freeze_snapshot(repository, _full_scope())
    artifacts = _artifact_map(snapshot)

    assert artifacts["tracked.txt"] == b"current unstaged bytes\n"
    assert artifacts["staged.txt"] == b"current staged bytes\n"
    assert artifacts["untracked.txt"] == b"current untracked bytes\n"

    tracked.write_bytes(b"edited after freeze\n")
    assert artifacts["tracked.txt"] == b"current unstaged bytes\n"


def test_bounded_snapshot_includes_only_selected_material_without_duplicates(
    tmp_path: Path,
) -> None:
    repository_path, repository = _repository(tmp_path)
    source = repository_path / "src"
    source.mkdir()
    (source / "a.py").write_text("A = 1\n", encoding="utf-8")
    (source / "b.py").write_text("B = 2\n", encoding="utf-8")
    (repository_path / "outside.py").write_text("OUTSIDE = True\n", encoding="utf-8")

    snapshot = freeze_snapshot(repository, _bounded_scope("src", "src/a.py"))

    assert [artifact.logical_path for artifact in snapshot.artifacts] == [
        "src/a.py",
        "src/b.py",
    ]
    assert snapshot.requested_paths == ("src", "src/a.py")
    assert snapshot.mode is OXReviewMode.BOUNDED


def test_snapshot_excludes_sensitive_generated_large_and_non_text_material(
    tmp_path: Path,
) -> None:
    repository_path, repository = _repository(tmp_path)
    (repository_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (repository_path / "secret.pem").write_text("private material\n", encoding="utf-8")
    (repository_path / "data.db").write_text("database material\n", encoding="utf-8")
    (repository_path / "archive.zip").write_text("archive material\n", encoding="utf-8")
    (repository_path / "image.png").write_text("not actually an image\n", encoding="utf-8")
    (repository_path / "nul.txt").write_bytes(b"before\x00after")
    (repository_path / "invalid.txt").write_bytes(b"\xff\xfe")
    (repository_path / "large.txt").write_bytes(b"x" * (OX_MAX_ARTIFACT_BYTES + 1))

    for directory in (
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "evidence",
    ):
        target = repository_path / directory
        target.mkdir()
        (target / "should-not-enter.txt").write_text("excluded\n", encoding="utf-8")

    snapshot = freeze_snapshot(repository, _full_scope())
    artifacts = snapshot.artifacts
    exclusions = _exclusion_paths(snapshot)

    assert [(artifact.logical_path, artifact.classification) for artifact in artifacts] == [
        ("src.py", "text/utf-8")
    ]
    assert {
        ".env",
        "secret.pem",
        "data.db",
        "archive.zip",
        "image.png",
        "nul.txt",
        "invalid.txt",
        "large.txt",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "evidence",
    } <= exclusions
    assert all(exclusion.reason for exclusion in snapshot.exclusions)


def test_traversal_records_links_and_nested_repositories_without_entering_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_path, repository = _repository(tmp_path)
    linked = repository_path / "linked"
    linked.mkdir()
    (linked / "outside.txt").write_text("do not traverse\n", encoding="utf-8")
    nested = repository_path / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    (nested / "inside.py").write_text("NESTED = True\n", encoding="utf-8")
    (repository_path / "kept.py").write_text("KEPT = True\n", encoding="utf-8")

    original = snapshot_module.is_link_or_junction

    def mark_link(path: Path) -> bool:
        return path == linked or original(path)

    monkeypatch.setattr(snapshot_module, "is_link_or_junction", mark_link)

    snapshot = freeze_snapshot(repository, _full_scope())
    artifact_paths = {artifact.logical_path for artifact in snapshot.artifacts}
    exclusion_paths = _exclusion_paths(snapshot)

    assert artifact_paths == {"kept.py"}
    assert {"linked", "nested"} <= exclusion_paths
    assert "linked/outside.txt" not in artifact_paths
    assert "nested/inside.py" not in artifact_paths


def test_directly_selected_link_or_junction_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_path, repository = _repository(tmp_path)
    selected = repository_path / "selected"
    selected.mkdir()
    (selected / "inside.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        snapshot_module,
        "is_link_or_junction",
        lambda path: path == selected,
    )

    with pytest.raises(OXBundleError):
        freeze_snapshot(repository, _bounded_scope("selected"))


def test_snapshot_inventory_is_sorted_and_identity_is_deterministic(tmp_path: Path) -> None:
    repository_path, repository = _repository(tmp_path)
    (repository_path / "b.txt").write_text("B\n", encoding="utf-8")
    (repository_path / "a.txt").write_text("A\n", encoding="utf-8")

    first = freeze_snapshot(repository, _full_scope())
    second = freeze_snapshot(repository, _full_scope())

    assert [artifact.logical_path for artifact in first.artifacts] == ["a.txt", "b.txt"]
    assert first.exclusions == tuple(
        sorted(first.exclusions, key=lambda item: (item.logical_path, item.reason))
    )
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.policy_version == OX_SNAPSHOT_POLICY_VERSION

    for artifact in first.artifacts:
        assert artifact.content_sha256 == hashlib.sha256(artifact.content).hexdigest()
        assert artifact.byte_length == len(artifact.content)


def test_snapshot_identity_changes_for_bytes_inventory_exclusions_and_scope(tmp_path: Path) -> None:
    repository_path, repository = _repository(tmp_path)
    source = repository_path / "source.txt"
    source.write_text("one\n", encoding="utf-8")

    original = freeze_snapshot(repository, _full_scope())

    source.write_text("two\n", encoding="utf-8")
    changed_bytes = freeze_snapshot(repository, _full_scope())
    assert changed_bytes.snapshot_sha256 != original.snapshot_sha256

    (repository_path / "second.txt").write_text("second\n", encoding="utf-8")
    changed_inventory = freeze_snapshot(repository, _full_scope())
    assert changed_inventory.snapshot_sha256 != changed_bytes.snapshot_sha256

    (repository_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    changed_exclusions = freeze_snapshot(repository, _full_scope())
    assert changed_exclusions.snapshot_sha256 != changed_inventory.snapshot_sha256

    single_file_repository_path, single_file_repository = _repository(tmp_path / "other")
    (single_file_repository_path / "only.txt").write_text("same bytes\n", encoding="utf-8")
    full = freeze_snapshot(single_file_repository, _full_scope())
    bounded = freeze_snapshot(single_file_repository, _bounded_scope("only.txt"))
    assert full.snapshot_sha256 != bounded.snapshot_sha256


def test_snapshot_rejects_more_than_maximum_artifact_count(tmp_path: Path) -> None:
    repository_path, repository = _repository(tmp_path)
    for index in range(OX_MAX_ARTIFACTS + 1):
        (repository_path / f"file-{index:05d}.txt").write_text("x", encoding="utf-8")

    with pytest.raises(OXBundleError):
        freeze_snapshot(repository, _full_scope())


def test_snapshot_rejects_aggregate_content_over_hard_limit(tmp_path: Path) -> None:
    repository_path, repository = _repository(tmp_path)
    chunk_size = min(900_000, OX_MAX_ARTIFACT_BYTES)
    file_count = (OX_MAX_SNAPSHOT_CONTENT_BYTES // chunk_size) + 1
    assert chunk_size <= OX_MAX_ARTIFACT_BYTES
    assert chunk_size * file_count > OX_MAX_SNAPSHOT_CONTENT_BYTES

    for index in range(file_count):
        (repository_path / f"chunk-{index}.txt").write_bytes(b"x" * chunk_size)

    with pytest.raises(OXBundleError):
        freeze_snapshot(repository, _full_scope())
