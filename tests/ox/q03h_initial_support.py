"""Shared deterministic fixtures for Q03H Task 4 acceptance tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from byte_mcp.errors import OXTransportError
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.jobs import OXProviderJobManager
from byte_mcp.ox.models import AttemptOutcome, ProviderResult, ProviderUsage, ReviewState
from byte_mcp.ox.natural_service import OXReviewService
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(self, action: str, *, outcome: str = "allowed", **fields: object) -> None:
        self.events.append((action, outcome, fields))


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
        return natural_result(attempt_id, "Natural OX engineering review.")


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
        result = natural_result(attempt_id, "Natural OX engineering review.")
        self.completed.set()
        return result


class UnknownThenSuccessNaturalClient:
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
        return natural_result(attempt_id, "Retry completed naturally.")


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


def natural_result(attempt_id: str, content: str) -> ProviderResult:
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


def write_registry(path: Path, repository_path: Path) -> None:
    path.write_text(
        '{"version":1,"repositories":{"fixture":{"path":'
        + repr(str(repository_path.resolve())).replace("'", '"')
        + ',"subsystems":{"validation":{"version":1,"source_roots":["src"],'
        '"test_roots":["tests"],"boundary_files":["src/alpha.py"],'
        '"context_files":["README.md"]}}}}}',
        encoding="utf-8",
    )


def verification() -> list[dict[str, object]]:
    return [
        {
            "id": "verification-1",
            "kind": "pytest",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "170 passed\n",
            "stderr": "",
            "recorded_at": "2026-08-29T18:00:00Z",
            "provenance": "Byte_Coding CI",
        }
    ]


def make_natural_service(
    tmp_path: Path,
    client,
    *,
    evidence: EvidenceStore | None = None,
    audit=None,
    jobs: OXProviderJobManager | None = None,
) -> tuple[OXReviewService, EvidenceStore, OXProviderJobManager, str, str]:
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, tmp_path / "evidence")
    store = evidence or EvidenceStore(settings.evidence_root)
    manager = jobs or OXProviderJobManager()
    service = OXReviewService(settings, store, client, audit or FakeAudit(), manager)
    return service, store, manager, base, target


def prepare(service: OXReviewService, base: str, target: str) -> dict[str, object]:
    return service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review the exact committed change.",
        verification=verification(),
    )


def wait_for_state(
    store: EvidenceStore,
    review_id: str,
    state: ReviewState,
) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        review = store.get_review(review_id)
        if review["state"] == state.value:
            return review
        threading.Event().wait(0.01)
    raise AssertionError(f"review did not reach {state.value}")


def wait_for_lane_release(jobs: OXProviderJobManager) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if jobs.snapshot() is None:
            return
        threading.Event().wait(0.01)
    raise AssertionError("OX provider lane did not release")
