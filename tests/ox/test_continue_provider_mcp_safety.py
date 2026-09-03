"""Regression tests for OX continuation provider safety."""

import asyncio
import inspect

from byte_mcp import server


async def _invoke_continue(**kwargs):
    """Support the pre-fix sync handler and repaired async handler."""
    result = server.ox_continue(**kwargs)

    if inspect.isawaitable(result):
        return await result

    return result


def test_ox_continue_provider_path_is_async() -> None:
    """Provider-capable continuation must remain an async MCP handler."""
    assert inspect.iscoroutinefunction(server.ox_continue)


def test_continue_message_routes_directly_to_background_service(
    monkeypatch,
) -> None:
    """The service owns provider lifetime; the MCP task must not own a thread hop."""

    class LaunchService:
        def __init__(self) -> None:
            self.calls = []

        def continue_message(self, review_id: str, message: str):
            self.calls.append((review_id, message))
            return {
                "review_id": review_id,
                "attempt_id": "OX-000001-A002",
                "state": "TRANSMITTING",
                "launch_accepted": True,
            }

    service = LaunchService()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("background continuation must not use asyncio.to_thread")

    monkeypatch.setattr(server, "_ox_service", lambda: service)
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_continue(
            review_id="OX-000001",
            message="continue",
        )
    )

    assert service.calls == [("OX-000001", "continue")]
    assert result["attempt_id"] == "OX-000001-A002"
    assert result["state"] == "TRANSMITTING"
    assert result["launch_accepted"] is True


def test_retry_continuation_routes_directly_with_renewed_approval(
    monkeypatch,
) -> None:
    """Explicit continuation retry is launched directly by the background-owning service."""

    class LaunchService:
        def __init__(self) -> None:
            self.calls = []

        def retry_continuation(
            self,
            review_id: str,
            retry_attempt_id: str,
            *,
            renewed_approval: bool,
        ):
            self.calls.append((review_id, retry_attempt_id, renewed_approval))
            return {
                "review_id": review_id,
                "attempt_id": "OX-000001-A003",
                "state": "TRANSMITTING",
                "launch_accepted": True,
            }

    service = LaunchService()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("background continuation retry must not use asyncio.to_thread")

    monkeypatch.setattr(server, "_ox_service", lambda: service)
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_continue(
            review_id="OX-000001",
            mode="retry",
            retry_attempt_id="OX-000001-A002",
            approve_retry=True,
        )
    )

    assert service.calls == [("OX-000001", "OX-000001-A002", True)]
    assert result["attempt_id"] == "OX-000001-A003"
    assert result["state"] == "TRANSMITTING"
    assert result["launch_accepted"] is True


def test_record_findings_remains_local_and_inline(
    monkeypatch,
) -> None:
    """Local finding persistence must not be routed through a worker thread."""

    class LocalService:
        def record_findings(
            self,
            review_id: str,
            findings,
        ):
            return {
                "review_id": review_id,
                "findings": findings,
                "path": "record_findings",
            }

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError(
            "record_findings must remain local and must not use to_thread"
        )

    monkeypatch.setattr(
        server,
        "_ox_service",
        lambda: LocalService(),
    )
    monkeypatch.setattr(
        asyncio,
        "to_thread",
        forbidden_to_thread,
    )

    result = asyncio.run(
        _invoke_continue(
            review_id="OX-TEST-001",
            mode="record_findings",
            findings=[{"claim": "derived"}],
        )
    )

    assert result["path"] == "record_findings"


def test_adjudicate_remains_local_and_inline(
    monkeypatch,
) -> None:
    """Local adjudication must not be routed through a worker thread."""

    class LocalService:
        def adjudicate(
            self,
            review_id: str,
            adjudications,
        ):
            return {
                "review_id": review_id,
                "adjudications": adjudications,
                "path": "adjudicate",
            }

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError(
            "adjudicate must remain local and must not use to_thread"
        )

    monkeypatch.setattr(
        server,
        "_ox_service",
        lambda: LocalService(),
    )
    monkeypatch.setattr(
        asyncio,
        "to_thread",
        forbidden_to_thread,
    )

    result = asyncio.run(
        _invoke_continue(
            review_id="OX-TEST-001",
            mode="adjudicate",
            adjudications=[
                {"finding_id": "OX-TEST-001-F001"},
            ],
        )
    )

    assert result["path"] == "adjudicate"
