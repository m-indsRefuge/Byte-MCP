from dataclasses import is_dataclass

import pytest

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.bundles import BundleBuilder, sha256_json
from byte_mcp.ox.repositories import GitRepository, RepositoryRegistry
from tests.ox.helpers import commit_files, create_repository, write_file
from tests.ox.test_repositories import write_registry


def _builder(tmp_path):
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    definition = RepositoryRegistry.load(registry_path).get("fixture")
    return repository_path, base, target, definition, GitRepository.open(definition)


def _verification():
    return [
        {
            "id": "verification-1",
            "kind": "pytest",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "14 passed\n",
            "stderr": "warning retained\n",
            "recorded_at": "2026-08-29T08:00:00Z",
            "provenance": "operator-supplied",
        }
    ]


def test_prepare_builds_complete_stable_committed_packet(tmp_path):
    repository_path, base, target, definition, reader = _builder(tmp_path)
    write_file(repository_path, "src/alpha.py", b"value = 'dirty'\n")

    prepared = BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
        definition.subsystems["validation"],
        target,
        base,
        _verification(),
    )
    repeated = BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
        definition.subsystems["validation"],
        target,
        base,
        _verification(),
    )

    assert [artifact.logical_path for artifact in prepared.artifacts] == [
        "README.md",
        "src/alpha.py",
        "src/gamma.py",
        "src/nested/beta.py",
        "tests/test_alpha.py",
    ]
    assert prepared.artifacts[0].categories == ("boundary", "context")
    assert prepared.artifacts[1].provider_text == "value = 'target'\n"
    assert prepared.artifacts[1].sha256 == (
        "50bee01cb1cdb632a06c1f1a773132969c7bf169b105045e1b44857d6bc7b7ba"
    )
    assert prepared.repository_tree == (
        "README.md",
        "src/alpha.py",
        "src/gamma.py",
        "src/nested/beta.py",
        "tests/test_alpha.py",
    )
    assert prepared.diff is not None
    assert "-value = 'base'" in prepared.diff.provider_text
    assert prepared.verification[0]["stdout"] == "14 passed\n"
    assert prepared.verification[0]["stderr"] == "warning retained\n"
    assert prepared.verification[0]["sha256"] == sha256_json(_verification()[0])
    assert prepared.manifest.protocol_version == "ox-review-v1"
    assert {entry.logical_path for entry in prepared.manifest.entries} == {
        "README.md",
        "src/alpha.py",
        "src/gamma.py",
        "src/nested/beta.py",
        "tests/test_alpha.py",
        "__ox__/base-to-target.diff",
        "__ox__/repository-tree.json",
        "__ox__/subsystem-definition.json",
        "__ox__/verification/verification-1.json",
    }
    assert prepared.manifest.manifest_sha256 == repeated.manifest.manifest_sha256
    assert prepared.packet["subsystem_definition_sha256"] == prepared.subsystem_definition_sha256
    assert prepared.packet["manifest"]["manifest_sha256"] == prepared.manifest.manifest_sha256


def test_prepare_requires_all_categories_and_preserves_invalid_utf8(tmp_path):
    repository_path, base, target, definition, reader = _builder(tmp_path)
    write_file(repository_path, "src/invalid.bin", b"\xff")
    committed_target = commit_files(
        repository_path,
        {"src/invalid.bin": b"\xff"},
        b"invalid utf8",
    )

    prepared = BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
        definition.subsystems["validation"],
        committed_target,
        base,
        _verification(),
    )

    invalid = next(
        artifact for artifact in prepared.artifacts if artifact.logical_path == "src/invalid.bin"
    )
    assert invalid.provider_text == "\ufffd"
    assert invalid.text_encoding == "utf-8-replacement"
    assert invalid.sha256 == "a8100ae6aa1940d0b663bb31cd466142ebbdbd5187131b92d93818987832eb89"

    missing_definition = definition.subsystems["validation"].__class__(
        "validation", 1, (), ("tests",), ("README.md",), ("README.md",)
    )
    with pytest.raises(OXBundleError, match="source"):
        BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
            missing_definition, committed_target, base, _verification()
        )


def test_definition_hash_and_bundle_limit_fail_closed(tmp_path):
    _, base, target, definition, reader = _builder(tmp_path)
    builder = BundleBuilder(reader, max_bundle_bytes=100_000)
    prepared = builder.prepare(definition.subsystems["validation"], target, base, _verification())
    changed_definition = definition.subsystems["validation"].__class__(
        "validation", 2, ("src",), ("tests",), ("README.md",), ("README.md",)
    )

    changed = builder.prepare(changed_definition, target, base, _verification())

    assert prepared.subsystem_definition_sha256 != changed.subsystem_definition_sha256
    assert prepared.total_bytes == len(prepared.serialized_packet)
    with pytest.raises(OXBundleError, match="max_bundle_bytes"):
        BundleBuilder(reader, max_bundle_bytes=prepared.total_bytes - 1).prepare(
            definition.subsystems["validation"], target, base, _verification()
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_sha256_json_rejects_non_finite_numbers(value):
    with pytest.raises(OXBundleError, match="canonical JSON"):
        sha256_json({"metadata": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_prepare_rejects_non_finite_verification_metadata(tmp_path, value):
    _, base, target, definition, reader = _builder(tmp_path)
    verification = _verification()
    verification[0]["metadata"] = {"duration": value}

    with pytest.raises(OXBundleError, match="canonical JSON"):
        BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
            definition.subsystems["validation"], target, base, verification
        )


@pytest.mark.parametrize("verification_id", [42, "", ".", "..", "up/one", r"up\one", "x:y"])
def test_prepare_rejects_unsafe_verification_id(tmp_path, verification_id):
    _, base, target, definition, reader = _builder(tmp_path)
    verification = _verification()
    verification[0]["id"] = verification_id

    with pytest.raises(OXBundleError, match="verification ID"):
        BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
            definition.subsystems["validation"], target, base, verification
        )


def test_prepare_rejects_duplicate_verification_ids(tmp_path):
    _, base, target, definition, reader = _builder(tmp_path)
    verification = _verification() * 2

    with pytest.raises(OXBundleError, match="verification ID"):
        BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
            definition.subsystems["validation"], target, base, verification
        )


@pytest.mark.parametrize(
    "contract", ["BundleArtifact", "ManifestEntry", "ReviewManifest", "PreparedBundle"]
)
def test_bundle_contracts_are_immutable_dataclasses(contract):
    from byte_mcp.ox import bundles

    contract_type = getattr(bundles, contract)
    assert is_dataclass(contract_type)
    assert contract_type.__dataclass_params__.frozen
    assert "__slots__" in contract_type.__dict__
