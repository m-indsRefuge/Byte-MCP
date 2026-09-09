from __future__ import annotations

import json
from pathlib import Path

import pytest

from byte_mcp.nvidia.chat import prepare_nvidia_chat_request
from byte_mcp.nvidia.canary_evidence import (
    NVIDIA_CANARY_SCHEMA,
    NvidiaCanaryEvidenceError,
    NvidiaCanaryEvidenceStore,
    NvidiaCanaryLockError,
    NvidiaCanaryManifest,
    NvidiaCanarySnapshot,
)


QUALIFIED_PREDECESSOR = "29daea6ef68ebb3d46031ce302b0108617bd1221"
MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"


def _manifest(**overrides: object) -> NvidiaCanaryManifest:
    values: dict[str, object] = {
        "schema": NVIDIA_CANARY_SCHEMA,
        "canary_id": "NVC-000001",
        "provider_id": "nvidia-api-catalog",
        "model_id": MODEL_ID,
        "method": "POST",
        "target_origin": "https://integrate.api.nvidia.com",
        "endpoint_path": "/v1/chat/completions",
        "payload_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "body_bytes": 128,
        "prepared_at": "2026-09-09T12:00:00+00:00",
        "probe_expected_text": "BYTE_NVIDIA_CANARY_OK",
        "qualified_predecessor_sha": QUALIFIED_PREDECESSOR,
    }
    values.update(overrides)
    return NvidiaCanaryManifest(**values)  # type: ignore[arg-type]


def _prepared_request():
    return prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=1.0,
        top_p=0.95,
        max_tokens=64,
    )


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


def test_prepare_persists_exact_body_manifest_and_prepared_event(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    prepared = _prepared_request()

    manifest = store.prepare(
        prepared,
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )

    canary_dir = store.root / "canaries" / "NVC-000001"
    assert manifest.canary_id == "NVC-000001"
    assert (canary_dir / "request-body.bin").read_bytes() == prepared.body_bytes
    raw_manifest = (canary_dir / "manifest.json").read_bytes()
    assert raw_manifest == json.dumps(
        json.loads(raw_manifest),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    events = (canary_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1
    assert json.loads(events[0])["event_type"] == "CANARY_PREPARED"


def test_prepare_allocates_next_identity_without_overwrite(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    prepared = _prepared_request()
    first = store.prepare(
        prepared,
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )
    second = store.prepare(
        prepared,
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:01:00+00:00",
    )

    assert first.canary_id == "NVC-000001"
    assert second.canary_id == "NVC-000002"


def test_load_reconstructs_and_validates_prepared_identity(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    prepared = _prepared_request()
    manifest = store.prepare(
        prepared,
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )

    snapshot = store.load(manifest.canary_id)

    assert snapshot.manifest == manifest
    assert snapshot.request_body == prepared.body_bytes
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_load_rejects_tampered_body_and_malformed_events(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(
        _prepared_request(),
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )
    canary_dir = store.root / "canaries" / manifest.canary_id

    (canary_dir / "request-body.bin").write_bytes(b"tampered")
    with pytest.raises(NvidiaCanaryEvidenceError):
        store.load(manifest.canary_id)

    (canary_dir / "request-body.bin").write_bytes(_prepared_request().body_bytes)
    (canary_dir / "events.jsonl").write_text("not-json\n", encoding="utf-8")
    with pytest.raises(NvidiaCanaryEvidenceError):
        store.load(manifest.canary_id)


def test_authorized_and_provider_start_events_reconstruct_state(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(
        _prepared_request(),
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )
    store.append_authorized(
        manifest.canary_id,
        request_sha256=manifest.request_sha256,
        recorded_at="2026-09-09T12:01:00+00:00",
    )
    store.append_provider_start(
        manifest.canary_id,
        request_sha256=manifest.request_sha256,
        recorded_at="2026-09-09T12:02:00+00:00",
    )

    snapshot = store.load(manifest.canary_id)

    assert snapshot.authorized_at == "2026-09-09T12:01:00+00:00"
    assert snapshot.provider_started_at == "2026-09-09T12:02:00+00:00"


def test_duplicate_or_out_of_order_lifecycle_events_fail_closed(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(
        _prepared_request(),
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )
    store.append_authorized(
        manifest.canary_id,
        request_sha256=manifest.request_sha256,
        recorded_at="2026-09-09T12:01:00+00:00",
    )
    with pytest.raises(NvidiaCanaryEvidenceError):
        store.append_authorized(
            manifest.canary_id,
            request_sha256=manifest.request_sha256,
            recorded_at="2026-09-09T12:01:30+00:00",
        )


def test_prepare_and_transmit_locks_reject_contention(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    prepared = _prepared_request()
    manifest = store.prepare(
        prepared,
        probe_expected_text="BYTE_NVIDIA_CANARY_OK",
        qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
        prepared_at="2026-09-09T12:00:00+00:00",
    )

    lock_path = store.root / ".prepare.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")
    with pytest.raises(NvidiaCanaryLockError):
        store.prepare(
            prepared,
            probe_expected_text="BYTE_NVIDIA_CANARY_OK",
            qualified_predecessor_sha=QUALIFIED_PREDECESSOR,
            prepared_at="2026-09-09T12:01:00+00:00",
        )
    lock_path.unlink()

    with store.transmit_lock(manifest.canary_id), pytest.raises(NvidiaCanaryLockError):
        with store.transmit_lock(manifest.canary_id):
            raise AssertionError("unreachable")
