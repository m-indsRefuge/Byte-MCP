from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import byte_mcp

REPO_ROOT = Path(byte_mcp.__file__).resolve().parents[2]
FAILURE_MAP = REPO_ROOT / "FAILURE_MAP.md"
QUALIFICATION_SCRIPT = REPO_ROOT / "scripts/nvidia_n05_offline_qualification.py"
QUALIFICATION_ARTIFACT = REPO_ROOT / "qualification/nvidia-n05/offline-qualification.json"
REQUIRED_FAILURE_IDS = tuple(f"F{number:02d}" for number in range(1, 22))


def _qualification_module():
    spec = importlib.util.spec_from_file_location(
        "nvidia_n05_offline_qualification",
        QUALIFICATION_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_map_covers_all_n05_failure_boundaries() -> None:
    assert FAILURE_MAP.is_file()
    text = FAILURE_MAP.read_text(encoding="utf-8")

    for failure_id in REQUIRED_FAILURE_IDS:
        assert f"| {failure_id} |" in text

    for required in (
        "No automatic retry.",
        "No automatic fallback.",
        "No dynamic `/v1/models` discovery",
        "Credentials are acquired only at the settings/transmit boundary.",
        "Prompt text, response text, credentials",
        "OUTCOME_UNKNOWN",
        "append-only evidence",
        "Hosted request dialect drift",
    ):
        assert required in text


def test_offline_qualification_is_provider_and_credential_free(monkeypatch) -> None:
    qualification = _qualification_module()
    settings = __import__(
        "byte_mcp.nvidia.settings",
        fromlist=["NvidiaHostedSettings"],
    )

    def forbidden_load(cls):
        raise AssertionError("N05 offline qualification must not load credentials")

    monkeypatch.setattr(
        settings.NvidiaHostedSettings,
        "load",
        classmethod(forbidden_load),
    )

    report = qualification.build_report(REPO_ROOT)

    assert report["status"] == "PASS"
    assert report["provider_calls"] == 0
    assert report["credential_status"] == "DEFERRED_TO_TRANSMIT"
    assert report["query_qualification"] == {
        "nemotron-ultra": "OFFLINE_QUALIFIED",
        "lightning": "OFFLINE_QUALIFIED",
    }
    assert report["expected_mcp_surface_names"] == [
        "nvidia_get_review",
        "nvidia_query",
        "nvidia_review",
    ]
    assert all(value == "PASS" for value in report["checks"].values())
    assert report["checks"]["query_no_dynamic_model_discovery"] == "PASS"
    assert report["checks"]["qualification_no_hosted_settings_loader"] == "PASS"


def test_offline_qualification_runner_has_no_network_or_secret_access() -> None:
    source = QUALIFICATION_SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "httpx",
        "requests",
        "urllib",
        "socket",
    ):
        assert forbidden not in source


def test_committed_qualification_artifact_matches_fresh_report() -> None:
    qualification = _qualification_module()
    fresh = qualification.build_report(REPO_ROOT)

    assert QUALIFICATION_ARTIFACT.is_file()
    committed = json.loads(QUALIFICATION_ARTIFACT.read_text(encoding="utf-8"))

    assert committed == fresh
    assert committed["schema_version"] == "nvidia-n05-offline-qualification-v1"
    assert committed["status"] == "PASS"
    assert committed["provider_calls"] == 0


def test_failure_map_references_real_coverage_files() -> None:
    qualification = _qualification_module()

    for relative in qualification.REQUIRED_COVERAGE_FILES:
        assert (REPO_ROOT / relative).is_file(), relative


@pytest.mark.parametrize("failure_id", REQUIRED_FAILURE_IDS)
def test_qualification_report_checks_every_failure_id(failure_id: str) -> None:
    qualification = _qualification_module()
    report = qualification.build_report(REPO_ROOT)

    assert report["checks"][f"failure_map_{failure_id.lower()}"] == "PASS"
