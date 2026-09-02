"""Regression tests for OX continuation provider safety."""

import asyncio
import inspect
import time

from byte_mcp import server


async def _invoke_continue(**kwargs):
    """Support the pre-fix sync handler and repaired async handler."""
    result = server.ox_continue(**kwargs)

    if inspect.isawaitable(result):
        return await result

    return result


def test_ox_continue_provider_path_is_async() -> None:
    """Provider-capable continuation must not remain a sync MCP handler."""
    assert inspect.iscoroutinefunction(server.ox_continue), (
        "ox_continue must be async before provider-capable continuation "
        "work can be offloaded from the MCP v1 event-loop thread"
    )


def test_continue_message_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """A slow continuation message must not block the MCP event loop."""

    class SlowService:
        def continue_message(
            self,
            review_id: str,
            message: str,
        ):
            time.sleep(0.20)

            return {
                "review_id": review_id,
                "message": message,
                "path": "message",
            }

    monkeypatch.setattr(
        server,
        "_ox_service",
        lambda: SlowService(),
    )

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()

        task = asyncio.create_task(
            _invoke_continue(
                review_id="OX-TEST-001",
                message="continue",
            )
        )

        await asyncio.sleep(0.02)

        event_loop_delay = loop.time() - started
        result = await task

        return event_loop_delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow OX continuation message blocked the MCP event loop "
        f"for {delay:.3f}s"
    )

    assert result == {
        "review_id": "OX-TEST-001",
        "message": "continue",
        "path": "message",
    }


def test_retry_continuation_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """An explicitly approved continuation retry must also be offloaded."""

    class SlowService:
        def retry_continuation(
            self,
            review_id: str,
            retry_attempt_id: str,
            *,
            renewed_approval: bool,
        ):
            assert renewed_approval is True

            time.sleep(0.20)

            return {
                "review_id": review_id,
                "attempt_id": retry_attempt_id,
                "path": "retry",
            }

    monkeypatch.setattr(
        server,
        "_ox_service",
        lambda: SlowService(),
    )

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()

        task = asyncio.create_task(
            _invoke_continue(
                review_id="OX-TEST-001",
                mode="retry",
                retry_attempt_id="OX-TEST-001-A002",
                approve_retry=True,
            )
        )

        await asyncio.sleep(0.02)

        event_loop_delay = loop.time() - started
        result = await task

        return event_loop_delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow OX continuation retry blocked the MCP event loop "
        f"for {delay:.3f}s"
    )

    assert result == {
        "review_id": "OX-TEST-001",
        "attempt_id": "OX-TEST-001-A002",
        "path": "retry",
    }


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
        server.asyncio,
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
        server.asyncio,
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
