import importlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from byte_mcp.nvidia.review_packet import prepare_review_packet
from byte_mcp.nvidia.review_protocol import (
    NvidiaReviewFinding,
    NvidiaReviewResult,
    prepare_nvidia_review_request,
)
from byte_mcp.nvidia.review_registry import (
    NvidiaReviewGitRepository,
    NvidiaReviewRepositoryRegistry,
)
from tests.ox.helpers import create_repository

TS = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def review_evidence_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_evidence")
    assert spec is not None, "NVIDIA review evidence module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_evidence")


def stamp(offset: int = 0) -> str:
    return (TS + timedelta(seconds=offset)).isoformat()


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


def prepared_components(tmp_path: Path):
    repository_path, base, target = create_repository(tmp_path / "repo")
    registry_path = tmp_path / "review-repositories.json"
    write_registry(registry_path, repository_path)
    definition = NvidiaReviewRepositoryRegistry.load(registry_path).get("fixture")
    repository = NvidiaReviewGitRepository.open(definition)
    packet = prepare_review_packet(
        repository,
        definition.subsystems["validation"],
        base,
        target,
        "Review regression and correctness risk",
        [
            {
                "id": "pytest",
                "kind": "test",
                "command": "python -m pytest",
                "exit_code": 0,
                "stdout": "898 passed",
                "stderr": "",
                "recorded_at": stamp(),
                "provenance": "operator",
            }
        ],
    )
    request = prepare_nvidia_review_request(packet)
    return packet, request


def valid_result() -> NvidiaReviewResult:
    return NvidiaReviewResult(
        decision="FINDINGS",
        summary="One bounded finding.",
        findings=(
            NvidiaReviewFinding(
                severity="MEDIUM",
                path="src/alpha.py",
                line=1,
                title="Regression risk",
                explanation="The changed value may alter the expected behavior.",
                recommendation="Verify the changed behavior with a regression test.",
            ),
        ),
    )


def terminal_event(snapshot, *, result_status: str, result_sha256: str | None):
    return {
        "event_type": "REVIEW_TERMINAL",
        "review_id": snapshot.manifest.review_id,
        "request_sha256": snapshot.manifest.request_sha256,
        "provider_id": snapshot.manifest.provider_id,
        "model_id": snapshot.manifest.model_id,
        "provider_started_at": snapshot.provider_started_at,
        "provider_finished_at": stamp(3),
        "attempt_outcome": "COMPLETED",
        "nvidia_failure_kind": None,
        "transport_failure_kind": None,
        "http_status_code": 200,
        "response_headers_received": True,
        "response_body_started": True,
        "decoded_body_bytes_received": 128,
        "elapsed_ms": 42,
        "finish_reason": "stop",
        "response_id": "review-response",
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "total_tokens": 125,
        "review_result_status": result_status,
        "result_sha256": result_sha256,
        "recorded_at": stamp(3),
    }


def test_review_ids_are_monotonic_and_prepare_persists_exact_identity(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")

    first = store.prepare(packet, request, prepared_at=stamp())
    second = store.prepare(packet, request, prepared_at=stamp(1))

    assert first.review_id == "NVR-000001"
    assert second.review_id == "NVR-000002"
    assert first.packet_sha256
    assert first.manifest_sha256 == packet.manifest.manifest_sha256
    review_dir = store.root / "reviews" / first.review_id
    assert (review_dir / "review-packet.json").read_bytes() == packet.serialized_packet
    assert (review_dir / "request-body.bin").read_bytes() == request.body_bytes
    assert (review_dir / "events.jsonl").read_bytes().endswith(b"\n")

    snapshot = store.load(first.review_id)
    assert snapshot.manifest == first
    assert snapshot.review_packet == packet.serialized_packet
    assert snapshot.request_body == request.body_bytes
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None
    assert snapshot.terminal_event is None
    assert snapshot.result is None


def test_prepare_rejects_request_not_derived_from_exact_packet(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    tampered = replace(request, request_sha256="0" * 64)

    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.prepare(packet, tampered, prepared_at=stamp())


def test_load_rejects_tampered_or_truncated_durable_evidence(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)

    for corrupt in ("packet", "request", "manifest", "events"):
        root = tmp_path / corrupt
        store = module.NvidiaReviewEvidenceStore(root)
        manifest = store.prepare(packet, request, prepared_at=stamp())
        review_dir = root / "reviews" / manifest.review_id
        if corrupt == "packet":
            (review_dir / "review-packet.json").write_bytes(b"{}")
        elif corrupt == "request":
            (review_dir / "request-body.bin").write_bytes(b"{}")
        elif corrupt == "manifest":
            (review_dir / "manifest.json").write_text("{}", encoding="utf-8")
        else:
            events = (review_dir / "events.jsonl").read_bytes()
            (review_dir / "events.jsonl").write_bytes(events.rstrip(b"\n"))

        with pytest.raises(module.NvidiaReviewEvidenceError):
            store.load(manifest.review_id)


def test_provider_start_requires_authorization_and_lifecycle_is_append_only(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(packet, request, prepared_at=stamp())

    with pytest.raises(module.NvidiaReviewEvidenceError, match="authorized"):
        store.append_provider_start(
            manifest.review_id,
            request_sha256=manifest.request_sha256,
            recorded_at=stamp(2),
        )

    store.append_authorized(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(1),
    )
    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.append_authorized(
            manifest.review_id,
            request_sha256=manifest.request_sha256,
            recorded_at=stamp(1),
        )

    store.append_provider_start(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(2),
    )
    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.append_provider_start(
            manifest.review_id,
            request_sha256=manifest.request_sha256,
            recorded_at=stamp(2),
        )

    result_sha = store.persist_result(manifest.review_id, valid_result())
    snapshot = store.load(manifest.review_id)
    store.append_terminal(
        manifest.review_id,
        terminal_event(snapshot, result_status="VALID", result_sha256=result_sha),
    )
    terminal = store.load(manifest.review_id)
    assert terminal.terminal_event is not None
    assert terminal.result is not None

    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.append_terminal(
            manifest.review_id,
            terminal_event(terminal, result_status="VALID", result_sha256=result_sha),
        )
    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.append_authorized(
            manifest.review_id,
            request_sha256=manifest.request_sha256,
            recorded_at=stamp(4),
        )


def test_valid_terminal_requires_bound_persisted_result(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(packet, request, prepared_at=stamp())
    store.append_authorized(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(1),
    )
    store.append_provider_start(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(2),
    )
    snapshot = store.load(manifest.review_id)

    with pytest.raises(module.NvidiaReviewEvidenceError, match="result"):
        store.append_terminal(
            manifest.review_id,
            terminal_event(snapshot, result_status="VALID", result_sha256="0" * 64),
        )

    invalid_event = terminal_event(snapshot, result_status="INVALID", result_sha256=None)
    store.append_terminal(manifest.review_id, invalid_event)
    assert store.load(manifest.review_id).terminal_event["review_result_status"] == "INVALID"


def test_result_is_validated_bounded_and_written_only_once(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(packet, request, prepared_at=stamp())
    store.append_authorized(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(1),
    )
    store.append_provider_start(
        manifest.review_id,
        request_sha256=manifest.request_sha256,
        recorded_at=stamp(2),
    )

    digest = store.persist_result(manifest.review_id, valid_result())
    assert len(digest) == 64
    with pytest.raises(module.NvidiaReviewEvidenceError):
        store.persist_result(manifest.review_id, valid_result())

    unsafe = NvidiaReviewResult(
        decision="FINDINGS",
        summary="bad",
        findings=(
            NvidiaReviewFinding(
                severity="HIGH",
                path="src/not-prepared.py",
                line=1,
                title="bad",
                explanation="bad",
                recommendation="bad",
            ),
        ),
    )
    second = store.prepare(packet, request, prepared_at=stamp(4))
    store.append_authorized(
        second.review_id,
        request_sha256=second.request_sha256,
        recorded_at=stamp(5),
    )
    store.append_provider_start(
        second.review_id,
        request_sha256=second.request_sha256,
        recorded_at=stamp(6),
    )
    with pytest.raises(module.NvidiaReviewEvidenceError, match="result"):
        store.persist_result(second.review_id, unsafe)


def test_transmit_lock_excludes_concurrent_owner(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(packet, request, prepared_at=stamp())

    with (
        store.transmit_lock(manifest.review_id),
        pytest.raises(module.NvidiaReviewLockError),
        store.transmit_lock(manifest.review_id),
    ):
        pass


def test_environment_root_policy_matches_nvidia_root_convention(tmp_path: Path) -> None:
    module = review_evidence_module()
    explicit = module.NvidiaReviewEvidenceStore.from_environment(
        {"BYTE_MCP_NVIDIA_EVIDENCE_DIR": str(tmp_path / "explicit")},
        platform_name="linux",
        home=tmp_path,
    )
    assert explicit.root == (tmp_path / "explicit").resolve()

    windows = module.NvidiaReviewEvidenceStore.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        platform_name="win32",
        home=tmp_path,
    )
    assert windows.root == (tmp_path / "local" / "Byte-MCP" / "nvidia").resolve()

    linux = module.NvidiaReviewEvidenceStore.from_environment(
        {"XDG_DATA_HOME": str(tmp_path / "xdg")},
        platform_name="linux",
        home=tmp_path,
    )
    assert linux.root == (tmp_path / "xdg" / "byte-mcp" / "nvidia").resolve()


def test_snapshot_repr_and_evidence_do_not_expose_credentials(tmp_path: Path) -> None:
    module = review_evidence_module()
    packet, request = prepared_components(tmp_path)
    store = module.NvidiaReviewEvidenceStore(tmp_path / "evidence")
    manifest = store.prepare(packet, request, prepared_at=stamp())
    snapshot = store.load(manifest.review_id)

    assert "request_body_bytes=" in repr(snapshot)
    assert request.body_bytes.decode("utf-8") not in repr(snapshot)
    evidence = b"".join(
        path.read_bytes()
        for path in (store.root / "reviews" / manifest.review_id).iterdir()
        if path.is_file()
    )
    assert b"NVIDIA_API_KEY" not in evidence
    assert b"Authorization" not in evidence
