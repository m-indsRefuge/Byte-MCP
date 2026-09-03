"""Deterministic fixtures for Q03H background revalidation acceptance tests."""

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
from tests.ox.helpers import commit_files, create_repository
from tests.ox.q03h_initial_support import FakeAudit, verification, write_registry


class RevalidationNaturalClient:
    """Natural fake whose next revalidation call can block or fail deterministically."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.block_next = False
        self.fail_next = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls.append(
            {
                "attempt_id": attempt_id,
                "json_mode": json_mode,
                "messages": [dict(message) for message in messages],
            }
        )
        if self.block_next:
            self.block_next = False
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise AssertionError("blocked revalidation fixture was not released")
        if self.fail_next:
            self.fail_next = False
            raise OXTransportError(attempt_outcome=AttemptOutcome.OUTCOME_UNKNOWN.value)
        return natural_result(attempt_id)


def natural_result(attempt_id: str) -> ProviderResult:
    content = f"Natural OX revalidation response for {attempt_id}."
    raw = {
        "id": f"response-{attempt_id}",
        "model": "zai/glm-5.3-flash",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
    }
    return ProviderResult(
        content=content,
        usage=ProviderUsage(4, 5, 9, 0),
        response_id=raw["id"],
        model=raw["model"],
        raw_response=raw,
    )


def derived_finding() -> dict[str, object]:
    return {
        "category": "correctness",
        "severity": "high",
        "confidence": 0.95,
        "location": "src/alpha.py:1",
        "claim": "The implementation violates the stated contract.",
        "evidence": "OX identified the committed line and Byte verified the source reference.",
        "reproduction": "Inspect the committed line against the supplied contract.",
        "expected_behavior": "The committed implementation should satisfy the contract.",
        "observed_or_predicted_behavior": "The committed implementation does not satisfy it.",
        "disproof_condition": "Show the cited implementation is contract-compliant.",
        "recommended_investigation": "Reproduce the behavior against the committed evidence.",
    }


def make_revalidation_service(
    tmp_path: Path,
    client: RevalidationNaturalClient,
    *,
    evidence: EvidenceStore | None = None,
    jobs: OXProviderJobManager | None = None,
) -> tuple[
    OXReviewService,
    EvidenceStore,
    OXProviderJobManager,
    Path,
    str,
    str,
]:
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings("FAKE-TEST-KEY", registry_path, tmp_path / "evidence")
    store = evidence or EvidenceStore(settings.evidence_root)
    manager = jobs or OXProviderJobManager()
    service = OXReviewService(settings, store, client, FakeAudit(), manager)
    return service, store, manager, repository_path, base, target


def prepare_initial_review(service: OXReviewService, base: str, target: str) -> str:
    proposal = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review the exact committed change.",
        verification=verification(),
    )
    return str(proposal["review_id"])


def establish_initial_review(
    service: OXReviewService,
    store: EvidenceStore,
    jobs: OXProviderJobManager,
    base: str,
    target: str,
) -> str:
    review_id = prepare_initial_review(service, base, target)
    launch = service.transmit_review(review_id)
    assert launch["state"] == ReviewState.TRANSMITTING.value
    wait_for_review_state(store, review_id, ReviewState.REVIEWED)
    wait_for_lane_release(jobs)
    return review_id


def prepare_revalidation(
    service: OXReviewService,
    repository_path: Path,
    review_id: str,
    target: str,
) -> str:
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    proposal = service.prepare_revalidation(
        review_id,
        target_commit=remediation,
        base_commit=target,
        verification=verification(),
    )
    return str(proposal["revalidation_id"])


def establish_byte_provenance(service: OXReviewService, review_id: str) -> str:
    service.record_findings(review_id, [derived_finding()])
    finding_id = f"{review_id}-F001"
    service.adjudicate(
        review_id,
        [
            {
                "finding_id": finding_id,
                "status": "CONFIRMED",
                "evidence": "Byte confirmed the committed evidence.",
                "reasoning_summary": "The selected finding requires remediation.",
            }
        ],
    )
    return finding_id


def wait_for_review_state(
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


def wait_for_revalidation_state(
    store: EvidenceStore,
    revalidation_id: str,
    state: ReviewState,
) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        revalidation = store.get_revalidation(revalidation_id)
        if revalidation["state"] == state.value:
            return revalidation
        threading.Event().wait(0.01)
    raise AssertionError(f"revalidation did not reach {state.value}")


def wait_for_lane_release(jobs: OXProviderJobManager) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if jobs.snapshot() is None:
            return
        threading.Event().wait(0.01)
    raise AssertionError("OX provider lane did not release")
