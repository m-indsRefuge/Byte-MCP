import importlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from byte_mcp.nvidia.review_registry import (
    NvidiaReviewGitRepository,
    NvidiaReviewRepositoryRegistry,
)
from tests.ox.helpers import commit_files, create_repository

BASE_TS = datetime(2026, 9, 10, 12, 0, tzinfo=UTC).isoformat()


def review_packet_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_packet")
    assert spec is not None, "NVIDIA review packet module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_packet")


def write_registry(path: Path, repository_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repositories": {
                    "fixture": {
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
                },
            }
        ),
        encoding="utf-8",
    )


def review_fixture(tmp_path: Path):
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "review-repositories.json"
    write_registry(registry_path, repository_path)
    definition = NvidiaReviewRepositoryRegistry.load(registry_path).get("fixture")
    return (
        NvidiaReviewGitRepository.open(definition),
        definition.subsystems["validation"],
        base,
        target,
    )


def verification(stdout: str = "863 passed", stderr: str = "") -> list[dict[str, object]]:
    return [
        {
            "id": "pytest",
            "kind": "test",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": stdout,
            "stderr": stderr,
            "recorded_at": BASE_TS,
            "provenance": "operator",
        }
    ]


def test_packet_is_deterministic_and_binds_exact_review_identity(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, base, target = review_fixture(tmp_path)

    first = module.prepare_review_packet(
        repository,
        subsystem,
        base,
        target,
        "Review regression risk",
        verification(),
    )
    second = module.prepare_review_packet(
        repository,
        subsystem,
        base,
        target,
        "Review regression risk",
        verification(),
    )

    assert first.serialized_packet == second.serialized_packet
    assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256
    assert first.repository_alias == "fixture"
    assert first.subsystem_id == "validation"
    assert first.base_commit == base
    assert first.target_commit == target
    assert first.objective == "Review regression risk"
    assert tuple(artifact.logical_path for artifact in first.artifacts) == (
        "src/alpha.py",
        "src/gamma.py",
    )
    decoded = json.loads(first.serialized_packet)
    assert decoded["base_commit"] == base
    assert decoded["target_commit"] == target
    assert decoded["objective"] == "Review regression risk"
    assert decoded["diff"]["logical_path"] == "__nvidia_review__/base-to-target.diff"
    assert decoded["verification"][0]["sha256"]


def test_packet_rejects_objective_and_verification_bounds(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, base, target = review_fixture(tmp_path)

    with pytest.raises(ValueError, match="objective"):
        module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "x" * 4097,
            verification(),
        )

    with pytest.raises(ValueError, match="verification"):
        module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "Review",
            verification() * 33,
        )

    oversized = verification(stdout="x" * 16385)
    with pytest.raises(ValueError, match="verification"):
        module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "Review",
            oversized,
        )


def test_packet_rejects_incomplete_or_unsafe_verification(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, base, target = review_fixture(tmp_path)
    incomplete = verification()
    del incomplete[0]["provenance"]
    with pytest.raises(ValueError, match="verification"):
        module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "Review",
            incomplete,
        )

    duplicate = verification() + verification()
    with pytest.raises(ValueError, match="verification"):
        module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "Review",
            duplicate,
        )


def test_packet_rejects_non_utf8_changed_target_text(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, _, target = review_fixture(tmp_path)
    non_utf8_target = commit_files(
        repository.definition.path,
        {"src/gamma.py": b"\xff\xfe"},
        b"non-utf8 target",
    )

    with pytest.raises(ValueError, match="UTF-8"):
        module.prepare_review_packet(
            repository,
            subsystem,
            target,
            non_utf8_target,
            "Review",
            verification(),
        )


def test_packet_rejects_oversized_changed_target_text(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, _, target = review_fixture(tmp_path)
    oversized_target = commit_files(
        repository.definition.path,
        {"src/gamma.py": b"x" * 524_289},
        b"oversized target",
    )

    with pytest.raises(ValueError, match="changed target file exceeds maximum size"):
        module.prepare_review_packet(
            repository,
            subsystem,
            target,
            oversized_target,
            "Review",
            verification(),
        )


def test_packet_rejects_more_than_200_scoped_changed_files(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, base, target = review_fixture(tmp_path)
    original = repository.changed_paths
    repository.changed_paths = lambda _base, _target: tuple(
        f"src/file-{index:03d}.py" for index in range(201)
    )
    try:
        with pytest.raises(ValueError, match="changed target files"):
            module.prepare_review_packet(
                repository,
                subsystem,
                base,
                target,
                "Review",
                verification(),
            )
    finally:
        repository.changed_paths = original


def test_packet_omits_changes_outside_subsystem_scope(tmp_path: Path) -> None:
    module = review_packet_module()
    repository, subsystem, base, target = review_fixture(tmp_path)
    base_commit = repository.resolve_commit(base)
    target_commit = repository.resolve_commit(target)
    original = repository.changed_paths
    repository.changed_paths = lambda _base, _target: (
        "docs/unrelated.md",
        "src/alpha.py",
        "src/gamma.py",
    )
    try:
        packet = module.prepare_review_packet(
            repository,
            subsystem,
            base,
            target,
            "Review",
            verification(),
        )
    finally:
        repository.changed_paths = original
    assert tuple(item.logical_path for item in packet.artifacts) == (
        "src/alpha.py",
        "src/gamma.py",
    )
    assert base_commit is not None
    assert target_commit is not None
