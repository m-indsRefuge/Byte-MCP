import asyncio
import inspect
from typing import Any

import pytest

from byte_mcp import server
from byte_mcp.errors import OXProtocolError, OXUnavailableError
from byte_mcp.ox.models import OXAvailability
from byte_mcp.ox.runtime import OXRuntime

_OX_TOOL_NAMES = {"ox_review", "ox_continue", "ox_revalidate", "ox_get_review"}


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {"operation": name}

    def prepare_review(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("prepare_review", **kwargs)

    def transmit_review(self, review_id: str) -> dict[str, Any]:
        return self._call("transmit_review", review_id)

    def retry_review(self, review_id: str, *, renewed_approval: bool) -> dict[str, Any]:
        return self._call("retry_review", review_id, renewed_approval=renewed_approval)

    def continue_message(self, review_id: str, message: str) -> dict[str, Any]:
        return self._call("continue_message", review_id, message)

    def record_findings(
        self, review_id: str, findings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self._call("record_findings", review_id, findings)

    def retry_continuation(
        self, review_id: str, attempt_id: str, *, renewed_approval: bool
    ) -> dict[str, Any]:
        return self._call(
            "retry_continuation",
            review_id,
            attempt_id,
            renewed_approval=renewed_approval,
        )

    def adjudicate(self, review_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        return self._call("adjudicate", review_id, events)

    def prepare_revalidation(self, review_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("prepare_revalidation", review_id, **kwargs)

    def transmit_blind_revalidation(self, revalidation_id: str) -> dict[str, Any]:
        return self._call("transmit_blind_revalidation", revalidation_id)

    def retry_revalidation(
        self, revalidation_id: str, *, renewed_approval: bool
    ) -> dict[str, Any]:
        return self._call(
            "retry_revalidation", revalidation_id, renewed_approval=renewed_approval
        )

    def run_targeted_revalidation(
        self, revalidation_id: str, finding_ids: list[str]
    ) -> dict[str, Any]:
        return self._call("run_targeted_revalidation", revalidation_id, finding_ids)

    def get_review(self, review_id: str, *, view: str) -> dict[str, Any]:
        return self._call("get_review", review_id, view=view)


class FakeRuntime:
    def __init__(self, service: FakeService) -> None:
        self.service = service

    def require_service(self) -> FakeService:
        return self.service


def tools() -> dict[str, Any]:
    return server.mcp._tool_manager._tools


def test_exactly_four_ox_tools_are_registered_with_locked_annotations() -> None:
    registered = tools()

    assert {name for name in registered if name.startswith("ox_")} == _OX_TOOL_NAMES
    for name in {"ox_review", "ox_continue", "ox_revalidate"}:
        annotations = registered[name].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is False
        assert annotations.openWorldHint is True
    annotations = registered["ox_get_review"].annotations
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def test_ox_tool_signatures_match_v1_contract() -> None:
    review = inspect.signature(server.ox_review)
    continuation = inspect.signature(server.ox_continue)
    revalidation = inspect.signature(server.ox_revalidate)
    retrieval = inspect.signature(server.ox_get_review)

    assert list(review.parameters) == [
        "repository",
        "subsystem",
        "target_commit",
        "base_commit",
        "objective",
        "verification",
        "review_id",
        "approve",
        "retry",
    ]
    assert list(continuation.parameters) == [
        "review_id",
        "mode",
        "message",
        "findings",
        "adjudications",
        "retry_attempt_id",
        "approve_retry",
    ]
    assert list(revalidation.parameters) == [
        "review_id",
        "revalidation_id",
        "target_commit",
        "base_commit",
        "verification",
        "approve",
        "retry",
        "targeted",
        "finding_ids",
    ]
    assert list(retrieval.parameters) == ["review_id", "view"]


def test_review_modes_are_strict_and_dispatch_without_scope_redefinition(monkeypatch) -> None:
    fake = FakeService()
    monkeypatch.setattr(server, "ox_runtime", lambda: FakeRuntime(fake))

    result = asyncio.run(server.ox_review(
        repository="fixture",
        subsystem="validation",
        target_commit="a" * 40,
        base_commit="b" * 40,
        objective="Review it.",
        verification=[{"id": "v1"}],
    ))
    assert result["operation"] == "prepare_review"
    result = asyncio.run(server.ox_review(review_id="OX-000001", approve=True))
    assert result["operation"] == "transmit_review"
    result = asyncio.run(server.ox_review(review_id="OX-000001", approve=True, retry=True))
    assert result["operation"] == "retry_review"

    with pytest.raises(OXProtocolError):
        asyncio.run(server.ox_review(
            review_id="OX-000001",
            approve=True,
            target_commit="c" * 40,
        ))
    with pytest.raises(OXProtocolError):
        asyncio.run(server.ox_review(review_id="OX-000001", retry=True))


def test_continue_revalidate_and_get_review_modes_are_mutually_exclusive(monkeypatch) -> None:
    fake = FakeService()
    monkeypatch.setattr(server, "ox_runtime", lambda: FakeRuntime(fake))

    assert (
        asyncio.run(server.ox_continue("OX-000001", message="hello"))["operation"]
        == "continue_message"
    )
    assert (
        asyncio.run(server.ox_continue(
            "OX-000001",
            mode="record_findings",
            findings=[{"claim": "derived"}],
        ))["operation"]
        == "record_findings"
    )
    assert (
        asyncio.run(server.ox_continue(
            "OX-000001",
            mode="adjudicate",
            adjudications=[{"finding_id": "OX-000001-F001"}],
        ))["operation"]
        == "adjudicate"
    )
    assert (
        asyncio.run(server.ox_continue(
            "OX-000001",
            mode="retry",
            retry_attempt_id="OX-000001-A002",
            approve_retry=True,
        ))["operation"]
        == "retry_continuation"
    )
    with pytest.raises(OXProtocolError):
        asyncio.run(server.ox_continue(
            "OX-000001",
            mode="retry",
            message="replacement is forbidden",
            retry_attempt_id="OX-000001-A002",
            approve_retry=True,
        ))
    with pytest.raises(OXProtocolError):
        asyncio.run(server.ox_continue(
            "OX-000001",
            mode="record_findings",
            message="must be local-only",
            findings=[{"claim": "derived"}],
        ))

    assert (
        asyncio.run(server.ox_revalidate(
            "OX-000001",
            target_commit="c" * 40,
            base_commit="b" * 40,
            verification=[{"id": "v2"}],
        ))["operation"]
        == "prepare_revalidation"
    )
    assert (
        asyncio.run(server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
        ))["operation"]
        == "transmit_blind_revalidation"
    )
    assert (
        asyncio.run(server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
            retry=True,
        ))["operation"]
        == "retry_revalidation"
    )
    assert (
        asyncio.run(server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            targeted=True,
            finding_ids=["OX-000001-F001"],
        ))["operation"]
        == "run_targeted_revalidation"
    )
    with pytest.raises(OXProtocolError):
        asyncio.run(server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
            targeted=True,
            finding_ids=["OX-000001-F001"],
        ))

    for view in ("findings", "attempts", "revalidation"):
        result = server.ox_get_review("OX-000001", view)
        assert result["operation"] == "get_review"
        assert fake.calls[-1][2]["view"] == view
    with pytest.raises(OXProtocolError):
        server.ox_get_review("OX-000001", "source")


def test_disabled_ox_review_fails_at_runtime_boundary(monkeypatch) -> None:
    runtime = OXRuntime(OXAvailability.DISABLED)
    monkeypatch.setattr(server, "ox_runtime", lambda: runtime)

    with pytest.raises(OXUnavailableError):
        asyncio.run(server.ox_review(
            repository="fixture",
            subsystem="validation",
            target_commit="a" * 40,
            base_commit="b" * 40,
            objective="Review it.",
            verification=[{"id": "v1"}],
        ))


def test_q03h_ac18_attempt_view_projects_transport_metadata(tmp_path, monkeypatch) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from byte_mcp.errors import OXTransportFailureKind
    from byte_mcp.ox.evidence import EvidenceStore
    from byte_mcp.ox.models import AttemptOutcome
    from byte_mcp.ox.service import OXReviewService
    from byte_mcp.ox.settings import OXSettings

    manifest_sha256 = "a" * 64
    runtime_session_id = "b" * 32

    class ProjectionEvidenceStore(EvidenceStore):
        def get_review(self, review_id: str) -> dict[str, object]:
            review = super().get_review(review_id)
            for attempt in review["attempts"]:
                attempt["internal_only"] = "must-not-escape"
            return review

    class FailIfCalledClient:
        def complete(self, *args, **kwargs):
            raise AssertionError("retrieval must not call the provider")

    class Audit:
        def record(self, *args, **kwargs) -> None:
            return None

    store = ProjectionEvidenceStore(tmp_path / "evidence")
    review_id = store.persist_prepared_review(
        identity={
            "repository": "fixture",
            "subsystem": "validation",
            "objective": "review",
        },
        manifest={"manifest_sha256": manifest_sha256},
        bundle={"packet": "prepared"},
    )
    events_path = store._root / "reviews" / review_id / "events.jsonl"
    legacy_attempt_id = f"{review_id}-A001"
    legacy_events = [
        {
            "attempt_id": legacy_attempt_id,
            "event_type": "TRANSMISSION_INTENT",
            "manifest_sha256": manifest_sha256,
            "recorded_at": "2026-09-01T00:00:00+00:00",
        },
        {
            "attempt_id": legacy_attempt_id,
            "event_type": "ATTEMPT_OUTCOME",
            "outcome": AttemptOutcome.NOT_SENT.value,
        },
    ]
    with events_path.open("ab") as handle:
        for event in legacy_events:
            handle.write(
                json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
                + b"\n"
            )

    owned = store.claim_retry_transmission(
        review_id,
        manifest_sha256,
        renewed_approval=True,
        runtime_session_id=runtime_session_id,
    )
    store.record_provider_request_started(
        review_id,
        owned["attempt_id"],
        runtime_session_id=runtime_session_id,
        phase="initial",
    )
    started_at = store.get_review(review_id)["attempts"][-1]["provider_started_at"]
    assert isinstance(started_at, str)
    finished_at = (datetime.fromisoformat(started_at) + timedelta(milliseconds=25)).isoformat()
    store.record_attempt_outcome(
        review_id,
        owned["attempt_id"],
        AttemptOutcome.OUTCOME_UNKNOWN,
    )
    store.record_provider_transport_metadata(
        review_id,
        owned["attempt_id"],
        runtime_session_id=runtime_session_id,
        provider_finished_at=finished_at,
        elapsed_ms=25,
        transport_failure_kind=OXTransportFailureKind.READ_ERROR,
    )

    settings = OXSettings(
        "FAKE-TEST-KEY",
        tmp_path / "repositories.json",
        store._root,
    )
    service = OXReviewService(settings, store, FailIfCalledClient(), Audit())
    monkeypatch.setattr(server, "ox_runtime", lambda: FakeRuntime(service))

    result = server.ox_get_review(review_id, "attempts")

    assert result == {
        "review_id": review_id,
        "attempts": [
            {
                "attempt_id": legacy_attempt_id,
                "manifest_sha256": manifest_sha256,
                "outcome": AttemptOutcome.NOT_SENT.value,
            },
            {
                "attempt_id": owned["attempt_id"],
                "manifest_sha256": manifest_sha256,
                "runtime_session_id": runtime_session_id,
                "outcome": AttemptOutcome.OUTCOME_UNKNOWN.value,
                "provider_started_at": started_at,
                "provider_finished_at": finished_at,
                "elapsed_ms": 25,
                "transport_failure_kind": OXTransportFailureKind.READ_ERROR.value,
            },
        ],
    }
