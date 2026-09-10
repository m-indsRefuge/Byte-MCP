import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from dulwich.objects import Blob

from tests.ox.helpers import create_repository, write_file


def review_registry_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_registry")
    assert spec is not None, "NVIDIA review registry module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_registry")


def write_registry(path: Path, repository_path: Path, **overrides: object) -> None:
    repository: dict[str, object] = {
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
        json.dumps({"version": 1, "repositories": {"fixture": repository}}),
        encoding="utf-8",
    )


def test_registry_loads_allowlisted_repository_and_denies_unknown_alias(tmp_path: Path) -> None:
    module = review_registry_module()
    repository_path, _, _ = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)

    registry = module.NvidiaReviewRepositoryRegistry.load(registry_path)

    definition = registry.get("fixture")
    assert definition.path == repository_path
    assert definition.subsystems["validation"].source_roots == ("src",)
    with pytest.raises(ValueError, match="unknown repository alias"):
        registry.get("other")


def test_registry_accepts_utf8_bom_and_rejects_non_git_or_relative_paths(tmp_path: Path) -> None:
    module = review_registry_module()
    repository_path, _, _ = create_repository(tmp_path / "valid")
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    registry_path.write_bytes(b"\xef\xbb\xbf" + registry_path.read_bytes())
    assert module.NvidiaReviewRepositoryRegistry.load(registry_path).get("fixture").path == repository_path

    for invalid_path in (Path("relative-repository"), tmp_path / "missing"):
        write_registry(registry_path, invalid_path)
        with pytest.raises(ValueError, match="absolute existing Git repository"):
            module.NvidiaReviewRepositoryRegistry.load(registry_path)

    non_git = tmp_path / "not-git"
    non_git.mkdir()
    write_registry(registry_path, non_git)
    with pytest.raises(ValueError, match="absolute existing Git repository"):
        module.NvidiaReviewRepositoryRegistry.load(registry_path)


@pytest.mark.parametrize(
    "logical_path",
    ["src\\nested", "src/../secret", "tests\\..\\secret", "C:/drive", "/absolute", ""],
)
def test_registry_rejects_unsafe_logical_paths(tmp_path: Path, logical_path: str) -> None:
    module = review_registry_module()
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
        module.NvidiaReviewRepositoryRegistry.load(registry_path)


def test_git_reader_requires_exact_commit_sha_and_ignores_dirty_worktree(tmp_path: Path) -> None:
    module = review_registry_module()
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    definition = module.NvidiaReviewRepositoryRegistry.load(registry_path).get("fixture")
    reader = module.NvidiaReviewGitRepository.open(definition)

    write_file(repository_path, "src/alpha.py", b"value = 'dirty'\n")
    target_commit = reader.resolve_commit(target)

    assert reader.read_target_text(target_commit, "src/alpha.py") == b"value = 'target'\n"
    assert reader.changed_paths(reader.resolve_commit(base), target_commit) == (
        "src/alpha.py",
        "src/gamma.py",
    )
    diff = reader.diff(reader.resolve_commit(base), target_commit)
    assert b"-value = 'base'" in diff
    assert b"+value = 'target'" in diff

    for invalid_sha in ("HEAD", target[:-1], target + "0"):
        with pytest.raises(ValueError, match="exact 40-hex commit SHA"):
            reader.resolve_commit(invalid_sha)


def test_git_reader_rejects_symlink_and_submodule_target_entries(tmp_path: Path) -> None:
    module = review_registry_module()
    repository_path, _, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    reader = module.NvidiaReviewGitRepository.open(
        module.NvidiaReviewRepositoryRegistry.load(registry_path).get("fixture")
    )
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

    unsafe = reader.resolve_commit(commit.id.decode("ascii"))
    with pytest.raises(ValueError, match="unsafe Git entry"):
        reader.read_target_text(unsafe, "linked")
    with pytest.raises(ValueError, match="unsafe Git entry"):
        reader.read_target_text(unsafe, "submodule")
