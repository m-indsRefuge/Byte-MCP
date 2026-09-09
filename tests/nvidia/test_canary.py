from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from byte_mcp.nvidia.canary_evidence import NvidiaCanaryEvidenceStore
from byte_mcp.nvidia.settings import NvidiaHostedSettings


EXPECTED_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
EXPECTED_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
QUALIFIED_PREDECESSOR = "29daea6ef68ebb3d46031ce302b0108617bd1221"
FIXED_NOW = datetime(2026, 9, 9, 18, 0, 0, tzinfo=UTC)


def _canary_module():
    return import_module("byte_mcp.nvidia.canary")


def _forbid_http_client(*args: object, **kwargs: object) -> None:
    raise AssertionError("Task 3 must not construct an HTTP client")


def _forbid_settings_load(cls: type[NvidiaHostedSettings]) -> NvidiaHostedSettings:
    raise AssertionError("Task 3 must not load NVIDIA hosted settings")


def _evidence_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_task3_api_exports_exact_frozen_constants() -> None:
    canary = _canary_module()

    assert canary.NVIDIA_LIGHTNING_CANARY_MODEL_ID == EXPECTED_MODEL_ID
    assert canary.NVIDIA_LIGHTNING_CANARY_PROMPT == EXPECTED_PROMPT
    assert canary.NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT == EXPECTED_TEXT
    assert canary.NVIDIA_01_QUALIFIED_SHA == QUALIFIED_PREDECESSOR


def test_prepare_lightning_canary_persists_exact_fixed_request_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = _canary_module()
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(import_module("httpx"), "AsyncClient", _forbid_http_client)
    monkeypatch.setattr(
        NvidiaHostedSettings,
        "load",
        classmethod(_forbid_settings_load),
    )
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")

    receipt = canary.prepare_lightning_canary(store, now=lambda: FIXED_NOW)
    snapshot = store.load(receipt.canary_id)
    body = json.loads(snapshot.request_body)

    assert body == {
        "max_tokens": 64,
        "messages": [{"content": EXPECTED_PROMPT, "role": "user"}],
        "model": EXPECTED_MODEL_ID,
        "n": 1,
        "stream": False,
        "temperature": 1.0,
        "top_p": 0.95,
    }
    assert snapshot.manifest.probe_expected_text == EXPECTED_TEXT
    assert snapshot.manifest.qualified_predecessor_sha == QUALIFIED_PREDECESSOR
    assert receipt.canary_id == "NVC-000001"
    assert receipt.provider_id == "nvidia-api-catalog"
    assert receipt.model_id == EXPECTED_MODEL_ID
    assert receipt.payload_sha256 == snapshot.manifest.payload_sha256
    assert receipt.request_sha256 == snapshot.manifest.request_sha256
    assert receipt.body_bytes == len(snapshot.request_body)
    assert receipt.prepared_at == FIXED_NOW.isoformat()
    assert receipt.evidence_root == str(store.root)


def test_inspect_lightning_canary_is_read_only_and_credential_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = _canary_module()
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = canary.prepare_lightning_canary(store, now=lambda: FIXED_NOW)
    before = _evidence_bytes(store.root)

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(import_module("httpx"), "AsyncClient", _forbid_http_client)
    monkeypatch.setattr(
        NvidiaHostedSettings,
        "load",
        classmethod(_forbid_settings_load),
    )

    inspection = canary.inspect_lightning_canary(store, receipt.canary_id)
    after = _evidence_bytes(store.root)

    assert inspection.canary_id == receipt.canary_id
    assert inspection.provider_id == "nvidia-api-catalog"
    assert inspection.model_id == EXPECTED_MODEL_ID
    assert inspection.payload_sha256 == receipt.payload_sha256
    assert inspection.request_sha256 == receipt.request_sha256
    assert inspection.body_bytes == receipt.body_bytes
    assert inspection.prepared_at == FIXED_NOW.isoformat()
    assert inspection.probe_text == EXPECTED_TEXT
    assert inspection.provider_started_at is None
    assert inspection.has_terminal_event is False
    assert after == before


def test_task3_api_is_reexported_from_nvidia_package() -> None:
    package = import_module("byte_mcp.nvidia")

    assert package.NVIDIA_LIGHTNING_CANARY_MODEL_ID == EXPECTED_MODEL_ID
    assert package.NVIDIA_LIGHTNING_CANARY_PROMPT == EXPECTED_PROMPT
    assert package.NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT == EXPECTED_TEXT
    assert package.NVIDIA_01_QUALIFIED_SHA == QUALIFIED_PREDECESSOR
    assert callable(package.prepare_lightning_canary)
    assert callable(package.inspect_lightning_canary)
