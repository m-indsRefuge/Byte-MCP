import pytest

from scripts import pytest_manifest


def _manifest(predecessor_sha: str) -> dict:
    return {
        'predecessor_sha': predecessor_sha,
        'signature_version': pytest_manifest.SIGNATURE_VERSION,
        'collected_count': 1,
        'passed_count': 1,
        'failed_count': 0,
        'skipped_count': 0,
        'nodes': [
            {
                'nodeid': 'tests/test_example.py::test_example',
                'outcome': 'passed',
            }
        ],
    }


def test_compare_manifests_rejects_predecessor_provenance_mismatch() -> None:
    baseline = _manifest('a' * 40)
    candidate = _manifest('')

    with pytest.raises(ValueError, match='predecessor SHA mismatch'):
        pytest_manifest.compare_manifests(baseline, candidate)
