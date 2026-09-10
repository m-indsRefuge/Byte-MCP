import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from byte_mcp.nvidia.review_evidence import NvidiaReviewEvidenceStore
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from tests.ox.helpers import create_repository


def review_service_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_service")
    assert spec is not None, "NVIDIA review service module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_service")


def review_settings_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_settings")
    assert spec is not None, "NVIDIA review settings module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_settings")


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


def service_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repository_path, base, target = create_repository(tmp_path / "repo")
    registry_path = tmp_path / "review-repositories.json"
    write_registry(registry_path, repository_path)
    monkeypatch.setenv("BYTE_MCP_NVIDIA_REVIEW_REPOSITORIES_FILE", str(registry_path))
    module = review_service_module()
    store = NvidiaReviewEvidenceStore(tmp_path / "evidence")
    service = module.NvidiaReviewService.initialize(tmp_path, evidence_store=store)
    return service, store, base, target


def verification() -> list[dict[str, object]]:
    return [
        {
            "id": "pytest",
            "kind": "test",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "907 passed",
            "stderr": "",
            "recorded_at": "2026-09-10T12:00:00+00:00",
            "provenance": "operator",
        }
    ]


def test_review_settings_resolve_explicit_and_default_registry_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = review_settings_module()
    explicit = tmp_path / "explicit.json"
    monkeypatch.setenv("BYTE_MCP_NVIDIA_REVIEW_REPOSITORIES_FILE", str(explicit))
    settings = module.NvidiaReviewSettings.load(tmp_path)
    assert settings.repositories_file == explicit.resolve()
    assert "api_key" not in repr(settings).lower()

    monkeypatch.delenv("BYTE_MCP_NVIDIA_REVIEW_REPOSITORIES_FILE")
    monkeypatch.setenv("BYTE_MCP_NVIDIA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    default = module.NvidiaReviewSettings.load(tmp_path)
    expected = (tmp_path / "evidence" / "review-repositories.json").resolve()
    assert default.repositories_file == expected


def test_prepare_review_persists_one_exact_provider_free_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, base, target = service_fixture(tmp_path, monkeypatch)

    prepared = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review correctness and regression risk",
        verification=verification(),
    )

    assert prepared["review_id"] == "NVR-000001"
    assert prepared["repository_alias"] == "fixture"
    assert prepared["subsystem_id"] == "validation"
    assert prepared["base_commit"] == base
    assert prepared["target_commit"] == target
    assert prepared["model_id"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert len(prepared["packet_sha256"]) == 64
    assert len(prepared["manifest_sha256"]) == 64
    assert len(prepared["payload_sha256"]) == 64
    assert len(prepared["request_sha256"]) == 64

    snapshot = store.load("NVR-000001")
    assert snapshot.manifest.request_sha256 == prepared["request_sha256"]
    assert snapshot.provider_started_at is None
    assert snapshot.terminal_event is None


def test_prepare_and_read_paths_never_load_hosted_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "DO_NOT_READ_NVIDIA_SECRET"
    monkeypatch.setenv("NVIDIA_API_KEY", sentinel)

    def forbidden_load(cls):
        raise AssertionError("hosted credential loader must not run in prepare/read paths")

    monkeypatch.setattr(NvidiaHostedSettings, "load", classmethod(forbidden_load))
    service, store, base, target = service_fixture(tmp_path, monkeypatch)
    prepared = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review",
        verification=verification(),
    )
    summary = service.get_review(prepared["review_id"], view="summary")
    manifest = service.get_review(prepared["review_id"], view="manifest")

    rendered = json.dumps({"prepared": prepared, "summary": summary, "manifest": manifest})
    assert sentinel not in rendered
    durable = b"".join(
        path.read_bytes()
        for path in (store.root / "reviews" / prepared["review_id"]).iterdir()
        if path.is_file()
    )
    assert sentinel.encode() not in durable


def test_get_review_exposes_bounded_read_only_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _store, base, target = service_fixture(tmp_path, monkeypatch)
    prepared = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review",
        verification=verification(),
    )
    review_id = prepared["review_id"]

    summary = service.get_review(review_id, view="summary")
    assert summary["state"] == "PREPARED"
    assert summary["provider_started_at"] is None
    assert summary["has_terminal_event"] is False
    assert "request_body" not in summary
    assert "review_packet" not in summary

    findings = service.get_review(review_id, view="findings")
    assert findings == {
        "review_id": review_id,
        "review_result_status": None,
        "decision": None,
        "summary": None,
        "findings": [],
    }

    attempt = service.get_review(review_id, view="attempt")
    assert attempt["review_id"] == review_id
    assert attempt["authorized_at"] is None
    assert attempt["provider_started_at"] is None
    assert attempt["provider_finished_at"] is None
    assert attempt["attempt_outcome"] is None
    assert attempt["review_result_status"] is None

    manifest = service.get_review(review_id, view="manifest")
    assert manifest["review_id"] == review_id
    assert manifest["request_sha256"] == prepared["request_sha256"]
    assert "request_body" not in manifest
    assert "review_packet" not in manifest


def test_prepare_rejects_unknown_repository_or_subsystem_and_get_rejects_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _store, base, target = service_fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="repository"):
        service.prepare_review(
            repository="unknown",
            subsystem="validation",
            target_commit=target,
            base_commit=base,
            objective="Review",
            verification=verification(),
        )
    with pytest.raises(ValueError, match="subsystem"):
        service.prepare_review(
            repository="fixture",
            subsystem="unknown",
            target_commit=target,
            base_commit=base,
            objective="Review",
            verification=verification(),
        )

    prepared = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review",
        verification=verification(),
    )
    with pytest.raises(ValueError, match="view"):
        service.get_review(prepared["review_id"], view="raw")
