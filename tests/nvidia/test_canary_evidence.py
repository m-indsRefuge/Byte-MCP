from __future__ import annotations

from pathlib import Path

import pytest
from byte_mcp.nvidia.canary_evidence import (
    NVIDIA_CANARY_SCHEMA,
    NvidiaCanaryEvidenceStore,
    NvidiaCanaryManifest,
    NvidiaCanarySnapshot,
)


def _manifest(**overrides: object) -> NvidiaCanaryManifest:
    values: dict[str, object] = {
        "schema": NVIDIA_CANARY_SCHEMA,
        "canary_id": "NVC-000001",
        "provider_id": "nvidia-api-catalog",
        "model_id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "method": "POST",
        "target_origin": "https://integrate.api.nvidia.com",
        "endpoint_path": "/v1/chat/completions",
        "payload_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "body_bytes": 128,
        "prepared_at": "2026-09-09T12:00:00+00:00",
        "probe_expected_text": "BYTE_NVIDIA_CANARY_OK",
        "qualified_predecessor_sha": "29daea6ef68ebb3d46031ce302b0108617bd1221",
    }
    values.update(overrides)
    return NvidiaCanaryManifest(**values)  # type: ignore[arg-type]


def test_store_uses_explicit_evidence_root(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"BYTE_MCP_NVIDIA_EVIDENCE_DIR": str(root)},
        platform_name="win32",
        home=tmp_path / "home",
    )
    assert store.root == root.resolve(strict=False)


def test_store_uses_windows_default(tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"LOCALAPPDATA": str(local_app_data)},
        platform_name="win32",
        home=tmp_path / "home",
    )
    assert store.root == (local_app_data / "Byte-MCP" / "nvidia").resolve(strict=False)


def test_store_uses_windows_home_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = NvidiaCanaryEvidenceStore.from_environment(
        {},
        platform_name="win32",
        home=home,
    )
    assert store.root == (home / "AppData" / "Local" / "Byte-MCP" / "nvidia").resolve(
        strict=False
    )


def test_store_uses_xdg_default(tmp_path: Path) -> None:
    xdg_root = tmp_path / "xdg"
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"XDG_DATA_HOME": str(xdg_root)},
        platform_name="linux",
        home=tmp_path / "home",
    )
    assert store.root == (xdg_root / "byte-mcp" / "nvidia").resolve(strict=False)


def test_store_uses_home_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = NvidiaCanaryEvidenceStore.from_environment(
        {},
        platform_name="linux",
        home=home,
    )
    assert store.root == (home / ".local" / "share" / "byte-mcp" / "nvidia").resolve(
        strict=False
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("canary_id", "NVC-1"),
        ("schema", "wrong-schema"),
        ("payload_sha256", "A" * 64),
        ("request_sha256", "b" * 63),
        ("body_bytes", -1),
        ("body_bytes", 4_000_001),
        ("prepared_at", "2026-09-09T12:00:00"),
        ("qualified_predecessor_sha", "c" * 63),
    ],
)
def test_manifest_rejects_invalid_identity_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError):
        _manifest(**{field_name: invalid_value})


def test_manifest_rejects_invalid_provider_request_metadata() -> None:
    invalid_cases = (
        {"provider_id": "other-provider"},
        {"model_id": "other/model"},
        {"method": "GET"},
        {"target_origin": "https://example.com"},
        {"endpoint_path": "/v1/models"},
    )
    for overrides in invalid_cases:
        with pytest.raises(ValueError):
            _manifest(**overrides)


def test_manifest_and_snapshot_repr_hide_request_body() -> None:
    manifest = _manifest()
    body = b'{"messages":[{"content":"DO-NOT-RENDER"}]}'
    snapshot = NvidiaCanarySnapshot(
        manifest=manifest,
        request_body=body,
        events=(),
        authorized_at=None,
        provider_started_at=None,
        terminal_event=None,
    )

    assert "DO-NOT-RENDER" not in repr(manifest)
    assert "DO-NOT-RENDER" not in repr(snapshot)
    assert "request_body=" not in repr(snapshot)


def test_snapshot_requires_valid_lifecycle_timestamps() -> None:
    manifest = _manifest()
    with pytest.raises(ValueError):
        NvidiaCanarySnapshot(
            manifest=manifest,
            request_body=b"{}",
            events=(),
            authorized_at="2026-09-09T12:01:00",
            provider_started_at=None,
            terminal_event=None,
        )
