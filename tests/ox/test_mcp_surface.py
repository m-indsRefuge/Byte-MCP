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

    result = server.ox_review(
        repository="fixture",
        subsystem="validation",
        target_commit="a" * 40,
        base_commit="b" * 40,
        objective="Review it.",
        verification=[{"id": "v1"}],
    )
    assert result["operation"] == "prepare_review"
    result = server.ox_review(review_id="OX-000001", approve=True)
    assert result["operation"] == "transmit_review"
    result = server.ox_review(review_id="OX-000001", approve=True, retry=True)
    assert result["operation"] == "retry_review"

    with pytest.raises(OXProtocolError):
        server.ox_review(
            review_id="OX-000001",
            approve=True,
            target_commit="c" * 40,
        )
    with pytest.raises(OXProtocolError):
        server.ox_review(review_id="OX-000001", retry=True)


def test_continue_revalidate_and_get_review_modes_are_mutually_exclusive(monkeypatch) -> None:
    fake = FakeService()
    monkeypatch.setattr(server, "ox_runtime", lambda: FakeRuntime(fake))

    assert server.ox_continue("OX-000001", message="hello")["operation"] == "continue_message"
    assert (
        server.ox_continue(
            "OX-000001",
            mode="record_findings",
            findings=[{"claim": "derived"}],
        )["operation"]
        == "record_findings"
    )
    assert (
        server.ox_continue(
            "OX-000001",
            mode="adjudicate",
            adjudications=[{"finding_id": "OX-000001-F001"}],
        )["operation"]
        == "adjudicate"
    )
    assert (
        server.ox_continue(
            "OX-000001",
            mode="retry",
            retry_attempt_id="OX-000001-A002",
            approve_retry=True,
        )["operation"]
        == "retry_continuation"
    )
    with pytest.raises(OXProtocolError):
        server.ox_continue(
            "OX-000001",
            mode="retry",
            message="replacement is forbidden",
            retry_attempt_id="OX-000001-A002",
            approve_retry=True,
        )
    with pytest.raises(OXProtocolError):
        server.ox_continue(
            "OX-000001",
            mode="record_findings",
            message="must be local-only",
            findings=[{"claim": "derived"}],
        )

    assert (
        server.ox_revalidate(
            "OX-000001",
            target_commit="c" * 40,
            base_commit="b" * 40,
            verification=[{"id": "v2"}],
        )["operation"]
        == "prepare_revalidation"
    )
    assert (
        server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
        )["operation"]
        == "transmit_blind_revalidation"
    )
    assert (
        server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
            retry=True,
        )["operation"]
        == "retry_revalidation"
    )
    assert (
        server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            targeted=True,
            finding_ids=["OX-000001-F001"],
        )["operation"]
        == "run_targeted_revalidation"
    )
    with pytest.raises(OXProtocolError):
        server.ox_revalidate(
            "OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
            targeted=True,
            finding_ids=["OX-000001-F001"],
        )

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
        server.ox_review(
            repository="fixture",
            subsystem="validation",
            target_commit="a" * 40,
            base_commit="b" * 40,
            objective="Review it.",
            verification=[{"id": "v1"}],
        )
