from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox import evidence
from byte_mcp.ox.models import (
    OXArtifact,
    OXPreparedReview,
    OXReviewMode,
    OXReviewScope,
    OXReviewState,
    OXSnapshot,
)
from byte_mcp.ox.packet import build_review_packet, prepare_ox_request
from byte_mcp.ox.settings import OX_SNAPSHOT_POLICY_VERSION


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _scope(*, objective: str = "Review the evidence boundary.") -> OXReviewScope:
    return OXReviewScope(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        paths=("src",),
        objective=objective,
    )


def _snapshot() -> OXSnapshot:
    content = b"VALUE = 1\n"
    artifact = OXArtifact(
        logical_path="src/app.py",
        content=content,
        byte_length=len(content),
        content_sha256=_sha256(content),
        classification="text/utf-8",
        git_state=None,
    )
    return OXSnapshot(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        requested_paths=("src",),
        policy_version=OX_SNAPSHOT_POLICY_VERSION,
        artifacts=(artifact,),
        exclusions=(),
        total_content_bytes=artifact.byte_length,
        snapshot_sha256=_sha256(b"snapshot-identity"),
    )


def _prepared(
    review_id: str,
    *,
    objective: str = "Review the evidence boundary.",
) -> OXPreparedReview:
    scope = _scope(objective=objective)
    snapshot = _snapshot()
    packet_bytes = build_review_packet(scope, snapshot)
    request = prepare_ox_request(packet_bytes)
    return OXPreparedReview(
        review_id=review_id,
        scope=scope,
        snapshot=snapshot,
        packet_bytes=packet_bytes,
        packet_sha256=_sha256(packet_bytes),
        prepared_request=request,
    )


def _review_dir(tmp_path, review_id: str):
    return tmp_path / "reviews" / review_id


def test_allocate_review_id_creates_monotonic_atomic_directories(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)

    first = store.allocate_review_id()
    second = store.allocate_review_id()

    assert first == "OX-000001"
    assert second == "OX-000002"
    assert _review_dir(tmp_path, first).is_dir()
    assert _review_dir(tmp_path, second).is_dir()


def test_persist_prepared_writes_required_layout_without_raw_snapshot_content(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)

    store.persist_prepared(prepared)

    directory = _review_dir(tmp_path, review_id)
    assert (directory / "review.json").is_file()
    assert (directory / "snapshot.json").is_file()
    assert (directory / "packet.bin").read_bytes() == prepared.packet_bytes
    assert (directory / "request.bin").read_bytes() == prepared.prepared_request.body_bytes

    review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    snapshot = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    assert review["state"] == "READY"
    assert review["request_sha256"] == prepared.prepared_request.request_sha256
    assert review["packet_sha256"] == prepared.packet_sha256
    assert snapshot["snapshot_sha256"] == prepared.snapshot.snapshot_sha256
    assert snapshot["artifacts"][0]["logical_path"] == "src/app.py"
    assert "content" not in snapshot["artifacts"][0]
    assert str(tmp_path) not in (directory / "review.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in (directory / "snapshot.json").read_text(encoding="utf-8")


def test_prepared_immutable_evidence_cannot_be_rewritten_with_different_bytes(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    first = _prepared(review_id)
    changed = _prepared(review_id, objective="Review a different objective.")

    store.persist_prepared(first)

    with pytest.raises(OXEvidenceError):
        store.persist_prepared(changed)

    directory = _review_dir(tmp_path, review_id)
    assert (directory / "packet.bin").read_bytes() == first.packet_bytes
    assert (directory / "request.bin").read_bytes() == first.prepared_request.body_bytes


def test_claim_send_is_irreversible_and_survives_store_restart(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)

    assert store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:00Z",
    )
    claim_bytes = (_review_dir(tmp_path, review_id) / "send.claim").read_bytes()

    assert not store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:01Z",
    )
    restarted = evidence.OXEvidenceStore(tmp_path)
    assert not restarted.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:02Z",
    )
    assert (_review_dir(tmp_path, review_id) / "send.claim").read_bytes() == claim_bytes


def test_claim_send_rejects_request_identity_mismatch_without_consuming_authority(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)

    with pytest.raises(OXEvidenceError):
        store.claim_send(review_id, "0" * 64, "2026-09-17T17:00:00Z")

    assert not (_review_dir(tmp_path, review_id) / "send.claim").exists()


def test_response_and_review_text_are_write_once(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    store.persist_prepared(_prepared(review_id))

    store.persist_response(review_id, b'{"choices":[]}')
    store.persist_review_text(review_id, "No material issues found.")

    store.persist_response(review_id, b'{"choices":[]}')
    store.persist_review_text(review_id, "No material issues found.")

    with pytest.raises(OXEvidenceError):
        store.persist_response(review_id, b"different")
    with pytest.raises(OXEvidenceError):
        store.persist_review_text(review_id, "Different review.")


def test_get_projects_ready_then_outcome_unknown_after_claim(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)

    ready = store.get(review_id)
    assert ready.state is OXReviewState.READY
    assert ready.attempt_outcome is None
    assert ready.review_text is None

    store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:00Z",
    )

    uncertain = evidence.OXEvidenceStore(tmp_path).get(review_id)
    assert uncertain.state is OXReviewState.OUTCOME_UNKNOWN
    assert uncertain.provider_started_at == "2026-09-17T17:00:00Z"
    assert uncertain.review_text is None


def test_finalize_completed_requires_durable_response_and_review_text(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)
    store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:00Z",
    )

    terminal = {
        "state": OXReviewState.COMPLETED,
        "provider_started_at": "2026-09-17T17:00:00Z",
        "provider_finished_at": "2026-09-17T17:00:03Z",
        "attempt_outcome": "COMPLETED",
    }
    with pytest.raises(OXEvidenceError):
        store.finalize(review_id, terminal)

    body = b'{"choices":[{"message":{"role":"assistant","content":"Looks sound."}}]}'
    store.persist_response(review_id, body)
    with pytest.raises(OXEvidenceError):
        store.finalize(review_id, terminal)

    store.persist_review_text(review_id, "Looks sound.")
    store.finalize(review_id, terminal)

    projected = store.get(review_id)
    assert projected.state is OXReviewState.COMPLETED
    assert projected.attempt_outcome == "COMPLETED"
    assert projected.provider_finished_at == "2026-09-17T17:00:03Z"
    assert projected.response_bytes == len(body)
    assert projected.review_text == "Looks sound."


def test_finalize_failed_projects_safe_terminal_metadata(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)
    store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T17:00:00Z",
    )
    store.persist_response(review_id, b"provider rejection")

    store.finalize(
        review_id,
        {
            "state": "FAILED",
            "provider_started_at": "2026-09-17T17:00:00Z",
            "provider_finished_at": "2026-09-17T17:00:01Z",
            "attempt_outcome": "REJECTED",
        },
    )

    projected = store.get(review_id)
    assert projected.state is OXReviewState.FAILED
    assert projected.attempt_outcome == "REJECTED"
    assert projected.response_bytes == len(b"provider rejection")
    assert projected.review_text is None


def test_get_is_a_safe_projection_without_raw_bytes_or_paths(tmp_path) -> None:
    store = evidence.OXEvidenceStore(tmp_path)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)

    projected = asdict(store.get(review_id))

    assert set(projected) == {
        "review_id",
        "state",
        "repository",
        "mode",
        "snapshot_sha256",
        "request_sha256",
        "provider_started_at",
        "provider_finished_at",
        "attempt_outcome",
        "response_bytes",
        "review_text",
    }
    serialized = repr(projected)
    assert str(tmp_path) not in serialized
    assert prepared.packet_bytes.decode("utf-8") not in serialized
    assert prepared.prepared_request.body_bytes.decode("utf-8") not in serialized
