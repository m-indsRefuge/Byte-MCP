"""Regression tests for long-running OX MCP provider operations."""

import asyncio
import inspect

import pytest

from byte_mcp import server
from byte_mcp.ox.models import ReviewState
from tests.ox.q03h_initial_support import (
    BlockingNaturalClient,
    make_natural_service,
    prepare,
    wait_for_state,
)


async def _invoke_review(**kwargs):
    result = server.ox_review(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def test_ox_review_provider_path_is_async() -> None:
    """The public MCP handler remains async while provider lifetime is runtime-owned."""
    assert inspect.iscoroutinefunction(server.ox_review)


def test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider(
    tmp_path,
    monkeypatch,
) -> None:
    client = BlockingNaturalClient()
    service, store, jobs, base, target = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    monkeypatch.setattr(server, "_ox_service", lambda: service)

    async def scenario() -> dict[str, object]:
        return await asyncio.wait_for(
            _invoke_review(review_id=review_id, approve=True),
            timeout=1,
        )

    receipt = asyncio.run(scenario())

    assert client.entered.wait(timeout=5)
    assert receipt["review_id"] == review_id
    assert receipt["attempt_id"] == "OX-000001-A001"
    assert receipt["state"] == ReviewState.TRANSMITTING.value
    assert receipt["launch_accepted"] is True
    assert receipt["replayed"] is False
    assert receipt["provider_request_performed"] is False
    assert store.get_review(review_id)["state"] == ReviewState.TRANSMITTING.value
    assert jobs.snapshot() is not None
    assert len(client.calls) == 1

    client.release.set()
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    assert len(client.calls) == 1


def test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker(
    tmp_path,
    monkeypatch,
) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target = make_natural_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_id = str(proposal["review_id"])
    monkeypatch.setattr(server, "_ox_service", lambda: service)

    async def scenario() -> tuple[dict[str, object], dict[str, object]]:
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
        return receipt, replayed

    receipt, replayed = asyncio.run(scenario())

    assert receipt["launch_accepted"] is True
    assert replayed["launch_accepted"] is False
    assert replayed["replayed"] is True
    assert replayed["attempt_id"] == receipt["attempt_id"]
    assert len(store.get_review(review_id)["attempts"]) == 1
    assert len(client.calls) == 1

    client.release.set()
    wait_for_state(store, review_id, ReviewState.REVIEWED)
    assert len(client.calls) == 1
