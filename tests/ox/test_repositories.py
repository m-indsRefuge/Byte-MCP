import json
from pathlib import Path

import pytest
from dulwich.objects import Blob

from byte_mcp.ox.repositories import (
    GitRepository,
    RepositoryRegistry,
    validate_ox_local_config,
)
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository, write_file


def write_registry(path: Path, repository_path: Path, **overrides: object) -> None:
    repository = {
        "path": str(repository_path),
        "subsystems": {
            "validation": {
                "version": 1,
                "source_roots": ["src"],
                "test_roots": ["tests"],
                "boundary_files": ["README.md"],
                "context_files": ["README.md"],
            }
        },
    }
    repository.update(overrides)
    path.write_text(
        json.dumps({"version": 1, "repositories": {"fixture": repository}}), encoding="utf-8"
    )


def settings(registry_path: Path, evidence_root: Path) -> OXSettings:
    return OXSettings(None, registry_path, evidence_root)


def test_registry_returns_configured_definition_and_denies_unknown_alias(tmp_path):
    repository_path, _, _ = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)

    registry = RepositoryRegistry.load(registry_path)

    assert registry.get("fixture").path == repository_path
    assert registry.get("fixture").subsystems["validation"].source_roots == ("src",)
    with pytest.raises(ValueError, match="unknown repository alias"):
        registry.get("unconfigured")


def test_registry_accepts_utf8_bom_from_windows_json_writer(tmp_path):
    repository_path, _, _ = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    registry_path.write_bytes(b"\xef\xbb\xbf" + registry_path.read_bytes())

    registry = RepositoryRegistry.load(registry_path)

    assert registry.get("fixture").path == repository_path


@pytest.mark.parametrize(
    "repository_path", [Path("relative-repository"), Path("missing-repository")]
)
def test_registry_rejects_relative_or_missing_repository_paths(tmp_path, repository_path):
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)

    with pytest.raises(ValueError, match="absolute existing Git repository"):
        RepositoryRegistry.load(registry_path)


def test_registry_rejects_non_git_directory(tmp_path):
    directory = tmp_path / "not-a-repository"
    directory.mkdir()
    registry_path = tmp_path / "repositories.json"
    write_registry(
        registry_path,
        directory,
    )

    with pytest.raises(ValueError, match="absolute existing Git repository"):
        RepositoryRegistry.load(registry_path)


@pytest.mark.parametrize(
    "logical_path", ["src\\nested", "src/../secret", "tests\\..\\secret", "C:/drive", ""]
)
def test_registry_rejects_invalid_logical_paths(tmp_path, logical_path):
    repository_path, _, _ = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(
        registry_path,
        repository_path,
        subsystems={
            "invalid": {
                "version": 1,
                "source_roots": [logical_path],
                "test_roots": ["tests"],
                "boundary_files": ["README.md"],
                "context_files": ["README.md"],
            }
        },
    )

    with pytest.raises(ValueError, match="logical Git path"):
        RepositoryRegistry.load(registry_path)


def test_config_validation_rejects_evidence_root_repository_overlap(tmp_path):
    repository_path, _, _ = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)

    with pytest.raises(ValueError, match="evidence root must not overlap"):
        validate_ox_local_config(settings(registry_path, repository_path / "evidence"))
    with pytest.raises(ValueError, match="evidence root must not overlap"):
        validate_ox_local_config(settings(registry_path, repository_path.parent))


def test_reader_requires_exact_commit_sha_and_ignores_dirty_worktree(tmp_path):
    repository_path, _, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    reader = GitRepository.open(RepositoryRegistry.load(registry_path).get("fixture"))
    write_file(repository_path, "src/alpha.py", b"value = 'dirty'\n")

    commit = reader.resolve_commit(target)

    assert reader.read_file(commit, "src/alpha.py") == b"value = 'target'\n"
    for invalid_sha in ("HEAD", target[:-1], target + "0"):
        with pytest.raises(ValueError, match="exact 40-hex commit SHA"):
            reader.resolve_commit(invalid_sha)


def test_reader_expands_roots_in_stable_posix_order_and_requires_matches(tmp_path):
    repository_path, _, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    reader = GitRepository.open(RepositoryRegistry.load(registry_path).get("fixture"))
    commit = reader.resolve_commit(target)

    assert list(reader.iter_root_files(commit, "src")) == [
        "src/alpha.py",
        "src/gamma.py",
        "src/nested/beta.py",
    ]
    assert reader.read_file(commit, "README.md") == b"base readme\n"
    with pytest.raises(ValueError, match="mandatory root"):
        list(reader.iter_root_files(commit, "missing"))
    with pytest.raises(ValueError, match="mandatory file"):
        reader.read_file(commit, "missing.txt")


def test_reader_rejects_required_symlink_and_submodule_entries(tmp_path):
    repository_path, _, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    reader = GitRepository.open(RepositoryRegistry.load(registry_path).get("fixture"))
    commit = reader.resolve_commit(target)

    store = reader.repo.object_store
    tree = store[commit.tree]
    link = Blob.from_string(b"src/alpha.py")
    store.add_object(link)
    tree.add(b"linked", 0o120000, link.id)
    tree.add(b"submodule", 0o160000, target.encode("ascii"))
    store.add_object(tree)
    commit.tree = tree.id
    store.add_object(commit)

    unsafe_commit = reader.resolve_commit(commit.id.decode("ascii"))
    with pytest.raises(ValueError, match="unsafe Git entry"):
        reader.read_file(unsafe_commit, "linked")
    with pytest.raises(ValueError, match="unsafe Git entry"):
        list(reader.iter_root_files(unsafe_commit, "submodule"))


def test_reader_returns_committed_tree_and_git_tree_diff(tmp_path):
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    reader = GitRepository.open(RepositoryRegistry.load(registry_path).get("fixture"))

    tree = reader.repository_tree(reader.resolve_commit(target))
    diff = reader.diff(reader.resolve_commit(base), reader.resolve_commit(target))

    assert tree == [
        "README.md",
        "src/alpha.py",
        "src/gamma.py",
        "src/nested/beta.py",
        "tests/test_alpha.py",
    ]
    assert b"-value = 'base'" in diff
    assert b"+value = 'target'" in diff
