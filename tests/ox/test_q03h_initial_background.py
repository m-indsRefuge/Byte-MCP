"""Q03H Task 4 acceptance contracts for background initial OX ownership."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from byte_mcp import server
from byte_mcp.errors import OXApprovalError, OXTransportError, OXUnavailableError
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.jobs import OXProviderJobManager
from byte_mcp.ox.models import AttemptOutcome, ProviderResult, ProviderUsage, ReviewState
from byte_mcp.ox.natural_service import OXReviewService
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository
from tests.ox.test_review_service import FakeAudit, verification, write_registry


class BlockingNaturalClient:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[dict[str, object]] = []

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls.append(
            {
                "attempt_id": attempt_id,
                "json_mode": json_mode,
                "messages": [dict(message) for message in messages],
            }
        )
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("blocked provider fixture was not released")
        return _natural_result(attempt_id, "Natural OX engineering review.")


class OrderedNaturalClient:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[dict[str, object]] = []
        self.completed = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.order.append("client.complete")
        self.calls.append(
            {
                "attempt_id": attempt_id,
                "json_mode": json_mode,
                "messages": [dict(message) for message in messages],
            }
        )
        result = _natural_result(attempt_id, "Natural OX engineering review.")
        self.completed.set()
        return result


class UnknownThenSuccessClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.first_finished = threading.Event()
        self.second_finished = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        assert json_mode is False
        self.calls.append(attempt_id)
        if len(self.calls) == 1:
            self.first_finished.set()
            raise OXTransportError(attempt_outcome=AttemptOutcome.OUTCOME_UNKNOWN.value)
        self.second_finished.set()
        return _natural_result(attempt_id, "Retry completed naturally.")


class RecordingEvidenceStore(EvidenceStore):
    def __init__(self, root: Path, order: list[str]) -> None:
        super().__init__(root)
        self.order = order

    def record_provider_request_started(self, *args, **kwargs) -> None:
        self.order.append("provider-start")
        super().record_provider_request_started(*args, **kwargs)

    def persist_provider_response(self, *args, **kwargs) -> None:
        self.order.append("raw-response")
        super().persist_provider_response(*args, **kwargs)

    def append_thread_message(self, review_id, thread_name, message) -> None:
        if message.get("role") == "assistant":
            self.order.append("assistant-thread")
        super().append_thread_message(review_id, thread_name, message)

    def record_attempt_outcome(self, review_id, attempt_id, outcome) -> None:
        value = outcome.value if isinstance(outcome, AttemptOutcome) else outcome
        self.order.append(f"outcome:{value}")
        super().record_attempt_outcome(review_id, attempt_id, outcome)


class OrderedAudit(FakeAudit):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self.order = order

    def record(self, action: str, *, outcome: str = "allowed", **fields: object) -> None:
        if fields.get("phase") in {"transmit", "initial", "initial-retry"}:
            self.order.append("audit")
        super().record(action, outcome=outcome, **fields)


def _natural_result(attempt_id: str, content: str) -> ProviderResult:
    raw = {
        "id": f"response-{attempt_id}",
        "model": "zai/glm-5.3-flash",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }
    return ProviderResult(
        content=content,
        usage=ProviderUsage(3, 4, 7, 0),
        response_id=raw["id"],
        model=raw["model"],
        raw_response=raw,
    )


def _make_service(
    tmp_path: Path,
    client,
    *,
    evidence: EvidenceStore | None = None,
    audit=None,
) -> tuple[OXReviewService, EvidenceStore, OXProviderJobManager, str, str]:
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, tmp_path / "evidence")
    store = evidence or EvidenceStore(settings.evidence_root)
    jobs = OXProviderJobManager()
    service = OXReviewService(settings, store, client, audit or FakeAudit(), jobs)
    return service, store, jobs, base, target


def _prepare(service: OXReviewService, base: str, target: str) -> dict[str, object]:
    return service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review the exact committed change.",
        verification=verification(),
    )


def _wait_for_state(store: EvidenceStore, review_id: str, state: ReviewState) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        review = store.get_review(review_id)
        if review["state"] == state.value:
            return review
        threading.Event().wait(0.01)
    raise AssertionError(f"review did not reach {state.value}")


def _wait_for_lane_release(jobs: OXProviderJobManager) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if jobs.snapshot() is None:
            return
        threading.Event().wait(0.01)
    raise AssertionError("OX provider lane did not release")


def test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider(tmp_path) -> None:
    client = BlockingNaturalClient()
    service, store, jobs, base, target = _make_service(tmp_path, client)
    proposal = _prepare(service, base, target)

    receipt = service.transmit_review(str(proposal["review_id"]))

    assert client.entered.wait(timeout=5)
    assert receipt["review_id"] == proposal["review_id"]
    assert receipt["attempt_id"] == "OX-000001-A001"
    assert receipt["state"] == ReviewState.TRANSMITTING.value
    assert receipt["launch_accepted"] is True
    assert receipt["replayed"] is False
    assert receipt["provider_request_performed"] is False
    assert store.get_review(str(proposal["review_id"]))["state"] == ReviewState.TRANSMITTING.value
    assert jobs.snapshot() is not None

    client.release.set()
    _wait_for_state(store, str(proposal["review_id"]), ReviewState.REVIEWED)
    _wait_for_lane_release(jobs)
    assert len(client.calls) == 1


def test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker(
    tmp_path,
    monkeypatch,
) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target = _make_service(tmp_path, client)
    proposal = _prepare(service, base, target)
    review_id = str(proposal["review_id"])
    monkeypatch.setattr(server, "_ox_service", lambda: service)

    async def scenario() -> dict[str, object]:
        first = asyncio.create_task(server.ox_review(review_id=review_id, approve=True))
        receipt = await asyncio.wait_for(first, timeout=1)
        assert client.entered.wait(timeout=5)

        cancelled = asyncio.create_task(server.ox_review(review_id=review_id, approve=True))
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        replayed = await asyncio.wait_for(
            server.ox_review(review_id=review_id, approve=True),
            timeout=1,
        )
        return {"receipt": receipt, "replayed": replayed}

    results = asyncio.run(scenario())

    assert results["receipt"]["launch_accepted"] is True
    assert results["replayed"]["launch_accepted"] is False
    assert results["replayed"]["replayed"] is True
    assert len(store.get_review(review_id)["attempts"]) == 1
    assert len(client.calls) == 1

    client.release.set()
    _wait_for_state(store, review_id, ReviewState.REVIEWED)
    assert len(client.calls) == 1


def test_q03h_ac04_same_active_operation_replays_without_duplicate_work(tmp_path) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target = _make_service(tmp_path, client)
    proposal = _prepare(service, base, target)
    review_id = str(proposal["review_id"])

    first = service.transmit_review(review_id)
    assert client.entered.wait(timeout=5)
    before_attempts = list(store.get_review(review_id)["attempts"])
    before_calls = len(client.calls)

    replay = service.transmit_review(review_id)

    assert first["launch_accepted"] is True
    assert replay["launch_accepted"] is False
    assert replay["replayed"] is True
    assert replay["attempt_id"] == first["attempt_id"]
    assert store.get_review(review_id)["attempts"] == before_attempts
    assert len(client.calls) == before_calls == 1

    client.release.set()
    _wait_for_state(store, review_id, ReviewState.REVIEWED)


def test_q03h_ac07_submission_failure_after_claim_persists_not_sent(
    tmp_path,
    monkeypatch,
) -> None:
    client = BlockingNaturalClient()
    service, store, jobs, base, target = _make_service(tmp_path, client)
    proposal = _prepare(service, base, target)
    review_id = str(proposal["review_id"])

    def fail_start(_thread) -> None:
        raise RuntimeError("sentinel thread-start failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    with pytest.raises(OXUnavailableError):
        service.transmit_review(review_id)

    review = store.get_review(review_id)
    assert review["state"] == ReviewState.FAILED.value
    assert len(review["attempts"]) == 1
    assert review["attempts"][0]["outcome"] == AttemptOutcome.NOT_SENT.value
    assert "provider_started_at" not in review["attempts"][0]
    assert client.calls == []
    assert jobs.snapshot() is None

    monkeypatch.undo()
    other_tmp = tmp_path / "lane-reuse"
    other_tmp.mkdir()
    other_client = BlockingNaturalClient()
    other_service, _, _, other_base, other_target = _make_service(other_tmp, other_client)
    other = _prepare(other_service, other_base, other_target)
    receipt = other_service.transmit_review(str(other["review_id"]))
    assert receipt["launch_accepted"] is True
    other_client.release.set()


def test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence(tmp_path) -> None:
    order: list[str] = []
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, tmp_path / "evidence")
    store = RecordingEvidenceStore(settings.evidence_root, order)
    jobs = OXProviderJobManager()
    client = OrderedNaturalClient(order)
    service = OXReviewService(settings, store, client, OrderedAudit(order), jobs)
    proposal = _prepare(service, base, target)
    review_id = str(proposal["review_id"])

    receipt = service.transmit_review(review_id)
    assert receipt["launch_accepted"] is True
    assert client.completed.wait(timeout=5)
    _wait_for_state(store, review_id, ReviewState.REVIEWED)
    _wait_for_lane_release(jobs)

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert client.calls[0]["attempt_id"] == receipt["attempt_id"]
    assert order.index("provider-start") < order.index("client.complete")
    assert order.index("client.complete") < order.index("raw-response")
    assert order.index("raw-response") < order.index("assistant-thread")
    assert order.index("assistant-thread") < order.index("outcome:COMPLETED")
    assert order.index("outcome:COMPLETED") < order.index("audit")
    attempt = store.get_review(review_id)["attempts"][-1]
    assert attempt["runtime_session_id"] == jobs.runtime_session_id
    assert "provider_started_at" in attempt


def test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once(tmp_path) -> None:
    client = UnknownThenSuccessClient()
    service, store, jobs, base, target = _make_service(tmp_path, client)
    proposal = _prepare(service, base, target)
    review_id = str(proposal["review_id"])

    first = service.transmit_review(review_id)
    assert first["attempt_id"] == "OX-000001-A001"
    assert client.first_finished.wait(timeout=5)
    _wait_for_state(store, review_id, ReviewState.OUTCOME_UNKNOWN)
    _wait_for_lane_release(jobs)

    with pytest.raises(OXApprovalError):
        service.retry_review(review_id, renewed_approval=False)
    assert client.calls == ["OX-000001-A001"]
    assert len(store.get_review(review_id)["attempts"]) == 1

    retry = service.retry_review(review_id, renewed_approval=True)
    assert retry["attempt_id"] == "OX-000001-A002"
    assert retry["launch_accepted"] is True
    assert client.second_finished.wait(timeout=5)
    _wait_for_state(store, review_id, ReviewState.REVIEWED)
    _wait_for_lane_release(jobs)

    assert client.calls == ["OX-000001-A001", "OX-000001-A002"]
    attempts = store.get_review(review_id)["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]
    assert all(attempt["runtime_session_id"] == jobs.runtime_session_id for attempt in attempts)
