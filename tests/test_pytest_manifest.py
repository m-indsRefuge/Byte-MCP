from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pytest_manifest_under_test", REPO / "scripts" / "pytest_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
pytest_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pytest_manifest)


def _patch_windows_root(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    monkeypatch.setattr(pytest_manifest.os, "getcwd", lambda: root)
    monkeypatch.setattr(pytest_manifest.os.path, "abspath", lambda value: value)
    monkeypatch.setattr(pytest_manifest.os.path, "normcase", lambda value: value.lower())


def _manifest(nodes: list[dict[str, str]], *, version: str = "repo-root-v1") -> dict:
    return {
        "predecessor_sha": "baseline",
        "signature_version": version,
        "collected_count": len(nodes),
        "passed_count": sum(node["outcome"] == "passed" for node in nodes),
        "failed_count": sum(node["outcome"] == "failed" for node in nodes),
        "skipped_count": sum(node["outcome"] == "skipped" for node in nodes),
        "nodes": nodes,
    }


def test_normalizes_raw_checkout_root_without_erasing_semantic_content(monkeypatch) -> None:
    root = r"C:\qualification\candidate"
    _patch_windows_root(monkeypatch, root)
    value = root + r"\src\byte_mcp\server.py:123 AssertionError: expected tool"

    signature = pytest_manifest._normalize_signature(value)

    assert signature == r"<REPO>\src\byte_mcp\server.py:123 AssertionError: expected tool"


def test_normalizes_repr_escaped_checkout_root(monkeypatch) -> None:
    root = r"C:\qualification\candidate"
    _patch_windows_root(monkeypatch, root)
    escaped_root = root.replace("\\", "\\\\")
    value = (
        "AttributeError: <module 'byte_mcp.server' from '"
        + escaped_root
        + r"\\src\\byte_mcp\\server.py'> has no attribute '_ox_service'"
    )

    signature = pytest_manifest._normalize_signature(value)

    assert escaped_root.lower() not in signature.lower()
    assert "<REPO>" in signature
    assert r"src\\byte_mcp\\server.py" in signature
    assert "has no attribute '_ox_service'" in signature


def test_normalizes_unordered_pytest_set_diff_items() -> None:
    predecessor = """
E AssertionError: assert {'fetch', ...} == {'fetch'}
Extra items in the left set:
'nvidia_get_review'
'nvidia_review'
'nvidia_query'
Full diff:
{
    'fetch',
+   'nvidia_get_review',
+   'nvidia_query',
+   'nvidia_review',
}
"""
    candidate = """
E AssertionError: assert {'fetch', ...} == {'fetch'}
Extra items in the left set:
'nvidia_query'
'nvidia_review'
'nvidia_get_review'
Full diff:
{
    'fetch',
+   'nvidia_get_review',
+   'nvidia_query',
+   'nvidia_review',
}
"""

    predecessor_signature = pytest_manifest._normalize_signature(predecessor)
    candidate_signature = pytest_manifest._normalize_signature(candidate)

    assert predecessor_signature == candidate_signature


def test_comparator_rejects_signature_version_mismatch() -> None:
    baseline = _manifest([{"nodeid": "test_a", "outcome": "passed"}], version="v1")
    candidate = _manifest([{"nodeid": "test_a", "outcome": "passed"}], version="v2")

    with pytest.raises(ValueError, match="signature normalization version mismatch"):
        pytest_manifest.compare_manifests(baseline, candidate)


def test_comparator_rejects_predecessor_test_disappearance() -> None:
    baseline = _manifest([{"nodeid": "test_a", "outcome": "passed"}])
    candidate = _manifest([])

    with pytest.raises(ValueError, match="predecessor outcome mismatch: test_a"):
        pytest_manifest.compare_manifests(baseline, candidate)


def test_comparator_rejects_passed_to_skipped() -> None:
    baseline = _manifest([{"nodeid": "test_a", "outcome": "passed"}])
    candidate = _manifest([{"nodeid": "test_a", "outcome": "skipped"}])

    with pytest.raises(ValueError, match="predecessor outcome mismatch: test_a"):
        pytest_manifest.compare_manifests(baseline, candidate)


def test_comparator_rejects_candidate_only_failure() -> None:
    baseline = _manifest([{"nodeid": "test_a", "outcome": "passed"}])
    candidate = _manifest(
        [
            {"nodeid": "test_a", "outcome": "passed"},
            {"nodeid": "test_new", "outcome": "failed", "failure_signature": "boom"},
        ]
    )

    with pytest.raises(ValueError, match="candidate-only failures: test_new"):
        pytest_manifest.compare_manifests(baseline, candidate)


def test_comparator_rejects_semantic_failure_signature_drift() -> None:
    baseline = _manifest(
        [{"nodeid": "test_a", "outcome": "failed", "failure_signature": "AssertionError: A"}]
    )
    candidate = _manifest(
        [{"nodeid": "test_a", "outcome": "failed", "failure_signature": "AssertionError: B"}]
    )

    with pytest.raises(ValueError, match="failure signature drift: test_a"):
        pytest_manifest.compare_manifests(baseline, candidate)


def test_comparator_allows_new_passing_test() -> None:
    baseline = _manifest([{"nodeid": "test_a", "outcome": "passed"}])
    candidate = _manifest(
        [
            {"nodeid": "test_a", "outcome": "passed"},
            {"nodeid": "test_new", "outcome": "passed"},
        ]
    )

    assert pytest_manifest.compare_manifests(baseline, candidate) is True