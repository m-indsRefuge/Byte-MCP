"""Regression boundary for OX revalidation provider safety."""

import asyncio
import inspect
import time

from byte_mcp import server


def test_ox_revalidate_provider_path_is_async() -> None:
    """Provider-capable revalidation must not remain a sync MCP handler."""
    assert inspect.iscoroutinefunction(server.ox_revalidate), (
        "ox_revalidate must be async before provider-capable "
        "revalidation work can be offloaded from the MCP v1 "
        "event-loop thread"
    )



async def _invoke_revalidate(**kwargs):
    result = server.ox_revalidate(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def test_prepare_revalidation_remains_local_and_inline(monkeypatch) -> None:
    """Local preparation must not be sent through a worker thread."""

    class LocalService:
        def prepare_revalidation(
            self,
            review_id: str,
            *,
            target_commit: str,
            base_commit: str,
            verification,
        ):
            return {
                "review_id": review_id,
                "target_commit": target_commit,
                "base_commit": base_commit,
                "verification": verification,
                "path": "prepare",
            }

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("prepare_revalidation must remain direct/local")

    monkeypatch.setattr(server, "_ox_service", lambda: LocalService())
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_revalidate(
            review_id="OX-TEST-001",
            target_commit="a" * 40,
            base_commit="b" * 40,
            verification=[{"id": "v1"}],
        )
    )

    assert result["path"] == "prepare"


def test_targeted_revalidation_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """Targeted provider work must execute outside the MCP event loop."""

    class SlowService:
        def run_targeted_revalidation(
            self,
            revalidation_id: str,
            finding_ids: list[str],
        ):
            time.sleep(0.20)
            return {
                "revalidation_id": revalidation_id,
                "finding_ids": finding_ids,
                "path": "targeted",
            }

    monkeypatch.setattr(server, "_ox_service", lambda: SlowService())

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()
        task = asyncio.create_task(
            _invoke_revalidate(
                review_id="OX-TEST-001",
                revalidation_id="OX-TEST-001-RV001",
                targeted=True,
                finding_ids=["OX-TEST-001-F001"],
            )
        )
        await asyncio.sleep(0.02)
        delay = loop.time() - started
        result = await task
        return delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow targeted OX revalidation blocked the MCP event loop "
        f"for {delay:.3f}s"
    )
    assert result["path"] == "targeted"


def test_retry_revalidation_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """An explicitly approved revalidation retry must be offloaded."""

    class SlowService:
        def retry_revalidation(
            self,
            revalidation_id: str,
            *,
            renewed_approval: bool,
        ):
            assert renewed_approval is True
            time.sleep(0.20)
            return {
                "revalidation_id": revalidation_id,
                "path": "retry",
            }

    monkeypatch.setattr(server, "_ox_service", lambda: SlowService())

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()
        task = asyncio.create_task(
            _invoke_revalidate(
                review_id="OX-TEST-001",
                revalidation_id="OX-TEST-001-RV001",
                approve=True,
                retry=True,
            )
        )
        await asyncio.sleep(0.02)
        delay = loop.time() - started
        result = await task
        return delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow OX revalidation retry blocked the MCP event loop "
        f"for {delay:.3f}s"
    )
    assert result["path"] == "retry"


def test_blind_revalidation_slow_provider_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """Approved blind revalidation transmission must be offloaded."""

    class SlowService:
        def transmit_blind_revalidation(self, revalidation_id: str):
            time.sleep(0.20)
            return {
                "revalidation_id": revalidation_id,
                "path": "blind",
            }

    monkeypatch.setattr(server, "_ox_service", lambda: SlowService())

    async def scenario():
        loop = asyncio.get_running_loop()
        started = loop.time()
        task = asyncio.create_task(
            _invoke_revalidate(
                review_id="OX-TEST-001",
                revalidation_id="OX-TEST-001-RV001",
                approve=True,
            )
        )
        await asyncio.sleep(0.02)
        delay = loop.time() - started
        result = await task
        return delay, result

    delay, result = asyncio.run(scenario())

    assert delay < 0.10, (
        "slow blind OX revalidation blocked the MCP event loop "
        f"for {delay:.3f}s"
    )
    assert result["path"] == "blind"
