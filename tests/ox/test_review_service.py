import json
import threading
from pathlib import Path

import pytest

from byte_mcp.errors import (
    OXApprovalError,
    OXBundleError,
    OXEvidenceError,
    OXRepositoryError,
    OXScopeError,
    OXTransportError,
    OXUnavailableError,
)
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import AttemptOutcome, ProviderResult, ProviderUsage, ReviewState
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository
from tests.ox.q03h_initial_support import wait_for_lane_release, wait_for_state


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(self, action: str, *, outcome: str = "allowed", **fields: object) -> None:
        self.events.append((action, outcome, fields))


class FailIfCalledClient:
    def complete(self, *args, **kwargs):
        raise AssertionError("provider client must not be called")


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "json_mode": json_mode,
                "attempt_id": attempt_id,
            }
        )
        content = json.dumps(
            {
                "protocol_version": "ox-findings-v1",
                "findings": [
                    {
                        "category": "correctness",
                        "severity": "medium",
                        "confidence": 0.8,
                        "location": "src/alpha.py:1",
                        "claim": "The target behavior differs from the base.",
                        "evidence": "The committed diff changes value.",
                        "reproduction": "Inspect the committed diff.",
                        "expected_behavior": "The intended value remains explicit.",
                        "observed_or_predicted_behavior": "The value changed.",
                        "disproof_condition": "Show the change is intentional and covered.",
                        "recommended_investigation": "Check the relevant test expectation.",
                    }
                ],
            }
        )
        raw = {
            "id": f"response-{attempt_id}",
            "model": "zai/glm-5.3-flash",
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 4},
            },
        }
        return ProviderResult(
            content=content,
            usage=ProviderUsage(20, 10, 30, 4),
            response_id=raw["id"],
            model=raw["model"],
            raw_response=raw,
        )


class MalformedClient(RecordingClient):
    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "json_mode": json_mode,
                "attempt_id": attempt_id,
            }
        )
        raw = {
            "id": f"response-{attempt_id}",
            "model": "zai/glm-5.3-flash",
            "choices": [{"message": {"role": "assistant", "content": "not-json"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return ProviderResult(
            content="not-json",
            usage=ProviderUsage(1, 1, 2, 0),
            response_id=raw["id"],
            model=raw["model"],
            raw_response=raw,
        )


class BlockingClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)


class UnknownThenSuccessClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.attempts += 1
        if self.attempts == 1:
            self.calls.append(
                {"messages": list(messages), "json_mode": json_mode, "attempt_id": attempt_id}
            )
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        return super().complete(messages, json_mode=json_mode, attempt_id=attempt_id)


class FailingEvidenceStore(EvidenceStore):
    def persist_prepared_review(self, **kwargs):
        raise OXEvidenceError("synthetic evidence failure")


def write_registry(path: Path, repository_path: Path, *, extra_context: str | None = None) -> None:
    context = ["README.md"]
    if extra_context is not None:
        context.append(extra_context)
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
                                "context_files": context,
                            }
                        },
                    }
                },
            }
        ),
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


def make_service(tmp_path: Path, client, *, evidence=None, max_bundle_bytes: int = 100_000):
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings(
        "FAKE-TEST-KEY",
        registry_path,
        tmp_path / "evidence",
        max_bundle_bytes=max_bundle_bytes,
    )
    store = evidence or EvidenceStore(settings.evidence_root)
    service = OXReviewService(settings, store, client, FakeAudit())
    return service, store, repository_path, base, target, registry_path


def prepare(service: OXReviewService, base: str, target: str) -> dict[str, object]:
    return service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review the exact committed change.",
        verification=verification(),
    )


def review_dir(store: EvidenceStore, review_id: str) -> Path:
    return store._root / "reviews" / review_id


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_prepare_persists_digest_bound_proposal_and_never_calls_provider(tmp_path) -> None:
    service, store, _, base, target, _ = make_service(tmp_path, FailIfCalledClient())

    proposal = prepare(service, base, target)

    assert proposal["review_id"] == "OX-000001"
    assert proposal["repository"] == "fixture"
    assert proposal["subsystem"] == "validation"
    assert proposal["target_commit"] == target
    assert proposal["base_commit"] == base
    assert proposal["objective"] == "Review the exact committed change."
    assert proposal["artifact_count"] >= 4
    assert proposal["total_bytes"] > 0
    assert len(proposal["manifest_sha256"]) == 64
    assert proposal["model"] == "zai/glm-5.3-flash"
    assert proposal["provider"] == "zai"
    assert proposal["transmitted"] is False
    assert store.get_review("OX-000001")["state"] == ReviewState.PREPARED.value


@pytest.mark.parametrize(
    ("change", "error_type"),
    [
        ({"repository": "missing"}, OXRepositoryError),
        ({"subsystem": "missing"}, OXScopeError),
        ({"target_commit": "HEAD"}, OXRepositoryError),
        ({"verification": []}, OXBundleError),
    ],
)
def test_prepare_invalid_input_fails_before_provider(tmp_path, change, error_type) -> None:
    service, _, _, base, target, _ = make_service(tmp_path, FailIfCalledClient())
    arguments = {
        "repository": "fixture",
        "subsystem": "validation",
        "target_commit": target,
        "base_commit": base,
        "objective": "Review it.",
        "verification": verification(),
    }
    arguments.update(change)

    with pytest.raises(error_type):
        service.prepare_review(**arguments)


def test_prepare_oversize_and_evidence_failure_never_call_provider(tmp_path) -> None:
    service, _, _, base, target, _ = make_service(
        tmp_path / "oversize", FailIfCalledClient(), max_bundle_bytes=16_384
    )
    with pytest.raises(OXBundleError):
        service.prepare_review(
            repository="fixture",
            subsystem="validation",
            target_commit=target,
            base_commit=base,
            objective="x" * 20_000,
            verification=verification(),
        )

    root = tmp_path / "evidence-failure"
    root.mkdir()
    repository_path, base2, target2 = create_repository(root)
    registry_path = root / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, root / "evidence")
    failing_store = FailingEvidenceStore(settings.evidence_root)
    failing = OXReviewService(settings, failing_store, FailIfCalledClient(), FakeAudit())
    with pytest.raises(OXEvidenceError):
        failing.prepare_review(
            repository="fixture",
            subsystem="validation",
            target_commit=target2,
            base_commit=base2,
            objective="Review it.",
            verification=verification(),
        )


def test_transmit_persists_response_findings_and_usage(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    launch = service.transmit_review(proposal["review_id"])
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, "OX-000001", ReviewState.REVIEWED)

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is True
    assert client.calls[0]["attempt_id"] == "OX-000001-A001"
    findings = service.get_review("OX-000001", view="findings")
    assert findings["findings"][0]["finding_id"] == "OX-000001-F001"
    review = store.get_review("OX-000001")
    assert review["attempts"][-1]["outcome"] == "COMPLETED"
    directory = review_dir(store, "OX-000001")
    thread = read_jsonl(directory / "threads" / "initial.jsonl")
    assert [message["role"] for message in thread] == ["system", "user", "assistant"]
    response = json.loads(
        (directory / "responses" / "OX-000001-A001.json").read_text(encoding="utf-8")
    )
    assert response["id"] == "response-OX-000001-A001"
    assert response["usage"] == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
        "prompt_tokens_details": {"cached_tokens": 4},
    }
    attempt = json.loads(
        (directory / "attempts" / "OX-000001-A001.json").read_text(encoding="utf-8")
    )
    assert attempt["manifest_sha256"] == proposal["manifest_sha256"]
    assert len(attempt["history_sha256"]) == 64
    assert attempt["runtime_session_id"] == service._jobs.runtime_session_id


def test_malformed_findings_fail_only_after_raw_response_is_durable(tmp_path) -> None:
    client = MalformedClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    launch = service.transmit_review(proposal["review_id"])
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, "OX-000001", ReviewState.REVIEWED)

    directory = review_dir(store, "OX-000001")
    assert (directory / "responses" / "OX-000001-A001.json").is_file()
    assert (directory / "findings" / "FINDINGS_INVALID-OX-000001-A001.json").is_file()
    assert store.get_review("OX-000001")["state"] == ReviewState.REVIEWED.value


def test_changed_scope_invalidates_approval_before_provider(tmp_path) -> None:
    client = RecordingClient()
    service, _, repository_path, base, target, registry_path = make_service(tmp_path, client)
    proposal = prepare(service, base, target)
    write_registry(registry_path, repository_path, extra_context="missing-new-context.md")

    with pytest.raises((OXScopeError, OXBundleError, OXRepositoryError, OXApprovalError)):
        service.transmit_review(proposal["review_id"])

    assert client.calls == []


def test_concurrent_transmit_claim_allows_exactly_one_provider_call(tmp_path) -> None:
    client = BlockingClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    assert client.entered.wait(timeout=5)
    replay = service.transmit_review(proposal["review_id"])

    assert first["attempt_id"] == replay["attempt_id"]
    assert replay["replayed"] is True
    assert len(store.get_review("OX-000001")["attempts"]) == 1
    client.release.set()
    wait_for_state(store, "OX-000001", ReviewState.REVIEWED)
    assert len(client.calls) == 1


def test_unknown_attempt_requires_renewed_approval_before_exact_retry(tmp_path) -> None:
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    launch = service.transmit_review(proposal["review_id"])
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, "OX-000001", ReviewState.OUTCOME_UNKNOWN)

    with pytest.raises(OXApprovalError):
        service.retry_review("OX-000001", renewed_approval=False)
    assert len(client.calls) == 1

    retry = service.retry_review("OX-000001", renewed_approval=True)
    assert retry["state"] == ReviewState.TRANSMITTING.value
    wait_for_state(store, "OX-000001", ReviewState.REVIEWED)

    assert [call["attempt_id"] for call in client.calls] == ["OX-000001-A001", "OX-000001-A002"]
    attempts = store.get_review("OX-000001")["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]


def test_q03h_ac07_submission_failure_after_claim_persists_not_sent(
    tmp_path,
    monkeypatch,
) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)
    jobs = service._jobs
    original_start = threading.Thread.start

    def fail_start(_thread) -> None:
        raise RuntimeError("sentinel thread-start failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(OXUnavailableError):
        service.transmit_review(proposal["review_id"])

    failed = store.get_review(proposal["review_id"])
    assert failed["state"] == ReviewState.FAILED.value
    assert len(failed["attempts"]) == 1
    assert failed["attempts"][0]["outcome"] == AttemptOutcome.NOT_SENT.value
    assert "provider_started_at" not in failed["attempts"][0]
    assert client.calls == []
    assert jobs.snapshot() is None

    monkeypatch.setattr(threading.Thread, "start", original_start)
    second = prepare(service, base, target)
    receipt = service.transmit_review(second["review_id"])

    assert service._jobs is jobs
    assert receipt["launch_accepted"] is True
    wait_for_state(store, second["review_id"], ReviewState.REVIEWED)
    wait_for_lane_release(jobs)
    assert len(client.calls) == 1


def test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once(tmp_path) -> None:
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = proposal["review_id"]

    first = service.transmit_review(review_id)
    assert first["attempt_id"] == "OX-000001-A001"
    wait_for_state(store, review_id, ReviewState.OUTCOME_UNKNOWN)
    wait_for_lane_release(service._jobs)

    with pytest.raises(OXApprovalError):
        service.retry_review(review_id, renewed_approval=False)
    assert len(client.calls) == 1
    assert len(store.get_review(review_id)["attempts"]) == 1

    retry = service.retry_review(review_id, renewed_approval=True)
    assert retry["attempt_id"] == "OX-000001-A002"
    assert retry["launch_accepted"] is True
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(service._jobs)

    assert [call["attempt_id"] for call in client.calls] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]
    attempts = store.get_review(review_id)["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]
    assert all(
        attempt["runtime_session_id"] == service._jobs.runtime_session_id
        for attempt in attempts
    )
