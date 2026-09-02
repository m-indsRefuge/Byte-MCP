"""Regression tests for long-running OX MCP provider operations."""

import asyncio
import inspect
import time

from byte_mcp import server


async def _invoke_review(**kwargs):
    """Support the pre-fix sync handler and repaired async handler."""
    result = server.ox_review(**kwargs)

    if inspect.isawaitable(result):
        return await result

    return result


def test_ox_review_provider_path_is_async() -> None:
    """Potentially long provider work must not run as a sync MCP v1 handler."""
    assert inspect.iscoroutinefunction(server.ox_review), (
        "ox_review must be async before provider work can be offloaded "
        "from the MCP v1 event-loop thread"
    )


def test_initial_review_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """A slow initial transmission must leave the event loop responsive."""

    class SlowService:
        def transmit_review(self, review_id: str):
            time.sleep(0.20)
            return {
                "review_id": review_id,
                "path": "initial",
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
            _invoke_review(
                review_id="OX-TEST-001",
                approve=True,
            )
        )

        await asyncio.sleep(0.02)

        event_loop_delay = loop.time() - started
        result = await task

        return event_loop_delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow initial OX provider work blocked the MCP event loop "
        f"for {delay:.3f}s"
    )

    assert result == {
        "review_id": "OX-TEST-001",
        "path": "initial",
    }


def test_retry_review_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """An explicitly approved retry must also execute outside the event loop."""

    class SlowService:
        def retry_review(
            self,
            review_id: str,
            *,
            renewed_approval: bool,
        ):
            assert renewed_approval is True

            time.sleep(0.20)

            return {
                "review_id": review_id,
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
            _invoke_review(
                review_id="OX-TEST-001",
                approve=True,
                retry=True,
            )
        )

        await asyncio.sleep(0.02)

        event_loop_delay = loop.time() - started
        result = await task

        return event_loop_delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow OX retry work blocked the MCP event loop "
        f"for {delay:.3f}s"
    )

    assert result == {
        "review_id": "OX-TEST-001",
        "path": "retry",
    }
