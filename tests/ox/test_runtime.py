import json
from pathlib import Path

import pytest
from byte_mcp.ox.runtime import OXRuntime

from byte_mcp.errors import OXUnavailableError
from byte_mcp.ox.models import OXAvailability
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository


class FakeAudit:
    def record(self, *args, **kwargs) -> None:
        pass


def write_registry(path: Path, repository_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repositories": {
                    "fixture": {
                        "path": str(repository_path.resolve()),
                        "subsystems": {
                            "validation": {
                                "version": 1,
                                "source_roots": ["src"],
                                "test_roots": ["tests"],
                                "boundary_files": ["src/alpha.py"],
                                "context_files": ["README.md"],
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_missing_key_is_disabled_without_validating_local_registry(tmp_path) -> None:
    settings = OXSettings(
        None,
        tmp_path / "missing-registry.json",
        tmp_path / "evidence",
    )

    runtime = OXRuntime.initialize(settings, FakeAudit())

    assert runtime.state is OXAvailability.DISABLED
    with pytest.raises(OXUnavailableError):
        runtime.require_service()


def test_invalid_registry_is_misconfigured_and_never_constructs_service(tmp_path) -> None:
    registry = tmp_path / "repositories.json"
    registry.write_text("not-json", encoding="utf-8")
    settings = OXSettings("FAKE-KEY", registry, tmp_path / "evidence")

    runtime = OXRuntime.initialize(settings, FakeAudit())

    assert runtime.state is OXAvailability.MISCONFIGURED
    with pytest.raises(OXUnavailableError):
        runtime.require_service()


def test_evidence_root_overlap_is_misconfigured(tmp_path) -> None:
    repository_path, _, _ = create_repository(tmp_path)
    registry = tmp_path / "repositories.json"
    write_registry(registry, repository_path)
    settings = OXSettings("FAKE-KEY", registry, repository_path / ".ox-evidence")

    runtime = OXRuntime.initialize(settings, FakeAudit())

    assert runtime.state is OXAvailability.MISCONFIGURED
    with pytest.raises(OXUnavailableError):
        runtime.require_service()


def test_valid_local_configuration_is_available_without_network_call(tmp_path) -> None:
    repository_path, _, _ = create_repository(tmp_path)
    registry = tmp_path / "repositories.json"
    write_registry(registry, repository_path)
    settings = OXSettings("FAKE-KEY", registry, tmp_path / "evidence")

    runtime = OXRuntime.initialize(settings, FakeAudit())

    assert runtime.state is OXAvailability.AVAILABLE
    assert isinstance(runtime.require_service(), OXReviewService)
    assert not settings.evidence_root.exists()
