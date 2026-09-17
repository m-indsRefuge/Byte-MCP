from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

import byte_mcp.ox.service as ox_service
from byte_mcp.ox.evidence import OXEvidenceStore
from byte_mcp.ox.models import (
    OXArtifact,
    OXPreparedReview,
    OXReviewMode,
    OXReviewScope,
    OXReviewState,
    OXSnapshot,
)
from byte_mcp.ox.packet import build_review_packet, prepare_ox_request
from byte_mcp.ox.scope import OXScopeResolver
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OX_SNAPSHOT_POLICY_VERSION, OXSettings

_API_KEY = "test-only-task10-key"
_STARTED = "2026-09-17T19:00:00+00:00"
_FINISHED = "2026-09-17T19:00:03+00:00"
_REVIEW_TEXT = "Task 10 review is durable."


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _prepared(review_id: str) -> OXPreparedReview:
    content = b"VALUE = 1\n"
    artifact = OXArtifact(
        logical_path="src/app.py",
        content=content,
        byte_length=len(content),
        content_sha256=_sha256(content),
        classification="text/utf-8",
        git_state=None,
    )
    scope = OXReviewScope(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        paths=("src",),
        objective="Qualify crash and replay boundaries.",
    )
    snapshot = OXSnapshot(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        requested_paths=("src",),
        policy_version=OX_SNAPSHOT_POLICY_VERSION,
        artifacts=(artifact,),
        exclusions=(),
        total_content_bytes=artifact.byte_length,
        snapshot_sha256=_sha256(b"task-10-snapshot"),
    )
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


def _review_directory(evidence_root: Path, review_id: str) -> Path:
    return evidence_root / "reviews" / review_id


def _persist_prepared(evidence_root: Path) -> tuple[OXEvidenceStore, str, OXPreparedReview]:
    store = OXEvidenceStore(evidence_root)
    review_id = store.allocate_review_id()
    prepared = _prepared(review_id)
    store.persist_prepared(prepared)
    return store, review_id, prepared


def _claim(store: OXEvidenceStore, prepared: OXPreparedReview) -> None:
    assert store.claim_send(
        prepared.review_id,
        prepared.prepared_request.request_sha256,
        _STARTED,
    )


def _complete_review(evidence_root: Path) -> tuple[str, bytes]:
    store, review_id, prepared = _persist_prepared(evidence_root)
    _claim(store, prepared)
    response = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": _REVIEW_TEXT,
                    }
                }
            ]
        }
    ).encode("utf-8")
    store.persist_response(review_id, response)
    store.persist_review_text(review_id, _REVIEW_TEXT)
    store.finalize(
        review_id,
        {
            "state": OXReviewState.COMPLETED,
            "provider_started_at": _STARTED,
            "provider_finished_at": _FINISHED,
            "attempt_outcome": "COMPLETED",
        },
    )
    return review_id, response


def _projects_root(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    repository = projects / "example"
    repository.mkdir(parents=True)
    (repository / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    return projects


def _service(
    projects_root: Path,
    evidence_root: Path,
    store: OXEvidenceStore | None = None,
) -> OXReviewService:
    evidence_store = store or OXEvidenceStore(evidence_root)
    return OXReviewService(
        scope_resolver=OXScopeResolver(projects_root),
        evidence_store=evidence_store,
        settings_loader=lambda: OXSettings(api_key=_API_KEY, evidence_root=evidence_root),
    )


def test_concurrent_claim_has_exactly_one_winner_and_one_immutable_claim(tmp_path: Path) -> None:
    store, review_id, prepared = _persist_prepared(tmp_path / "evidence")
    barrier = threading.Barrier(2)

    def claim_once(claimed_at: str) -> bool:
        barrier.wait(timeout=5)
        return store.claim_send(
            review_id,
            prepared.prepared_request.request_sha256,
            claimed_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim_once, "2026-09-17T19:00:00+00:00"),
            executor.submit(claim_once, "2026-09-17T19:00:01+00:00"),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert sorted(results) == [False, True]
    claim_path = _review_directory(tmp_path / "evidence", review_id) / "send.claim"
    claim_bytes = claim_path.read_bytes()
    assert claim_bytes
    assert not store.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T19:00:02+00:00",
    )
    assert claim_path.read_bytes() == claim_bytes


class _SharedReviewStore(OXEvidenceStore):
    def __init__(self, evidence_root: Path, barrier: threading.Barrier) -> None:
        super().__init__(evidence_root)
        self._shared_review_id = super().allocate_review_id()
        self._barrier = barrier
        self._claim_settled = threading.Event()

    def allocate_review_id(self) -> str:
        return self._shared_review_id

    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool:
        self._barrier.wait(timeout=5)
        claimed = super().claim_send(review_id, request_sha256, claimed_at)
        if claimed:
            self._claim_settled.set()
        else:
            assert self._claim_settled.wait(timeout=5)
        return claimed


def test_duplicate_service_execution_performs_at_most_one_transport(tmp_path: Path) -> None:
    projects_root = _projects_root(tmp_path)
    evidence_root = tmp_path / "evidence"
    store = _SharedReviewStore(evidence_root, threading.Barrier(2))
    service = _service(projects_root, evidence_root, store)
    transport_calls = 0
    transport_lock = threading.Lock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        with transport_lock:
            transport_calls += 1
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": _REVIEW_TEXT,
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    def run_review() -> dict[str, object]:
        return asyncio.run(
            service.review(
                repository="example",
                mode="FULL_REPOSITORY",
                paths=None,
                objective="Qualify duplicate send authority.",
                transport=transport,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_review), executor.submit(run_review)]
        results = [future.result(timeout=15) for future in futures]

    assert transport_calls == 1
    assert {str(result["review_id"]) for result in results} == {store._shared_review_id}
    assert {str(result["state"]) for result in results} <= {
        "COMPLETED",
        "OUTCOME_UNKNOWN",
    }
    restarted = OXEvidenceStore(evidence_root).get(store._shared_review_id)
    assert restarted.state is OXReviewState.COMPLETED


@pytest.mark.parametrize(
    ("stage", "expected_state"),
    [
        ("prepared", OXReviewState.READY),
        ("claimed_before_transport", OXReviewState.OUTCOME_UNKNOWN),
        ("http_completed_before_response", OXReviewState.OUTCOME_UNKNOWN),
        ("response_persisted", OXReviewState.OUTCOME_UNKNOWN),
        ("review_text_persisted", OXReviewState.OUTCOME_UNKNOWN),
        ("terminal_completed", OXReviewState.COMPLETED),
    ],
)
def test_restart_projection_never_reconstructs_send_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected_state: OXReviewState,
) -> None:
    evidence_root = tmp_path / stage / "evidence"
    projects_root = _projects_root(tmp_path / stage)
    store, review_id, prepared = _persist_prepared(evidence_root)
    response = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": _REVIEW_TEXT,
                    }
                }
            ]
        }
    ).encode("utf-8")

    if stage != "prepared":
        _claim(store, prepared)
    if stage in {"response_persisted", "review_text_persisted", "terminal_completed"}:
        store.persist_response(review_id, response)
    if stage in {"review_text_persisted", "terminal_completed"}:
        store.persist_review_text(review_id, _REVIEW_TEXT)
    if stage == "terminal_completed":
        store.finalize(
            review_id,
            {
                "state": "COMPLETED",
                "provider_started_at": _STARTED,
                "provider_finished_at": _FINISHED,
                "attempt_outcome": "COMPLETED",
            },
        )

    async def forbidden_transport(*args, **kwargs):
        raise AssertionError("restart retrieval must not perform provider networking")

    monkeypatch.setattr(ox_service, "execute_ox_transport", forbidden_transport)
    restarted_store = OXEvidenceStore(evidence_root)
    restarted_service = _service(projects_root, evidence_root, restarted_store)
    result = restarted_service.get_review(review_id)

    assert result["state"] == expected_state.value
    if stage == "prepared":
        assert not (
            _review_directory(evidence_root, review_id) / "send.claim"
        ).exists()
    else:
        claim_path = _review_directory(evidence_root, review_id) / "send.claim"
        claim_bytes = claim_path.read_bytes()
        assert not restarted_store.claim_send(
            review_id,
            prepared.prepared_request.request_sha256,
            "2026-09-17T19:00:05+00:00",
        )
        assert claim_path.read_bytes() == claim_bytes


def test_torn_send_claim_projects_outcome_unknown_and_never_restores_authority(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    store, review_id, prepared = _persist_prepared(evidence_root)
    claim_path = _review_directory(evidence_root, review_id) / "send.claim"
    claim_path.write_bytes(b"")

    restarted = OXEvidenceStore(evidence_root)
    projected = restarted.get(review_id)

    assert projected.state is OXReviewState.OUTCOME_UNKNOWN
    assert projected.review_text is None
    assert not restarted.claim_send(
        review_id,
        prepared.prepared_request.request_sha256,
        "2026-09-17T19:00:05+00:00",
    )
    assert claim_path.read_bytes() == b""


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_response",
        "changed_response",
        "missing_review_text",
        "changed_review_text",
        "response_hash",
        "response_count",
        "review_hash",
        "review_count",
    ],
)
def test_corrupt_completion_evidence_cannot_project_completed(
    tmp_path: Path,
    corruption: str,
) -> None:
    evidence_root = tmp_path / corruption / "evidence"
    review_id, response = _complete_review(evidence_root)
    directory = _review_directory(evidence_root, review_id)

    if corruption == "missing_response":
        (directory / "response.bin").unlink()
    elif corruption == "changed_response":
        (directory / "response.bin").write_bytes(response + b"corrupt")
    elif corruption == "missing_review_text":
        (directory / "review.txt").unlink()
    elif corruption == "changed_review_text":
        (directory / "review.txt").write_text("Different review.", encoding="utf-8")
    else:
        metadata_path = directory / "review.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if corruption == "response_hash":
            metadata["response_sha256"] = "0" * 64
        elif corruption == "response_count":
            metadata["response_bytes"] = int(metadata["response_bytes"]) + 1
        elif corruption == "review_hash":
            metadata["review_text_sha256"] = "0" * 64
        elif corruption == "review_count":
            metadata["review_text_bytes"] = int(metadata["review_text_bytes"]) + 1
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    projected = OXEvidenceStore(evidence_root).get(review_id)

    assert projected.state is OXReviewState.OUTCOME_UNKNOWN
    assert projected.review_text is None
