"""Regression boundary for OX revalidation provider safety."""

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from byte_mcp import server
from byte_mcp.errors import OXUnavailableError
from byte_mcp.ox.models import ReviewState
from tests.ox import q03h_revalidation_support as q03hr
from tests.ox.q03h_initial_support import verification


def test_ox_revalidate_provider_path_is_async() -> None:
    """Provider-capable revalidation must remain an async MCP handler."""
    assert inspect.iscoroutinefunction(server.ox_revalidate)


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


def test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode(tmp_path) -> None:
    client = q03hr.RevalidationNaturalClient()
    service, store, jobs, repository_path, base, target = q03hr.make_revalidation_service(
        tmp_path,
        client,
    )
    review_id = q03hr.establish_initial_review(service, store, jobs, base, target)
    revalidation_id = q03hr.prepare_revalidation(
        service,
        repository_path,
        review_id,
        target,
    )
    calls_before = len(client.calls)
    client.block_next = True
    client.entered.clear()
    client.release.clear()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.transmit_blind_revalidation, revalidation_id)
        assert client.entered.wait(timeout=5)
        try:
            receipt = future.result(timeout=0.25)
        except TimeoutError:
            client.release.set()
            future.result(timeout=5)
            raise

    assert receipt["revalidation_id"] == revalidation_id
    assert receipt["state"] == ReviewState.TRANSMITTING.value
    assert receipt["launch_accepted"] is True
    assert receipt["replayed"] is False
    assert receipt["provider_request_performed"] is False
    assert len(client.calls) == calls_before + 1
    assert client.calls[-1]["json_mode"] is False
    attempts = store.get_revalidation(revalidation_id)["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["runtime_session_id"] == jobs.runtime_session_id

    replay = service.transmit_blind_revalidation(revalidation_id)
    assert replay["attempt_id"] == receipt["attempt_id"]
    assert replay["launch_accepted"] is False
    assert replay["replayed"] is True
    assert len(client.calls) == calls_before + 1
    assert len(store.get_revalidation(revalidation_id)["attempts"]) == 1

    client.release.set()
    q03hr.wait_for_revalidation_state(
        store,
        revalidation_id,
        ReviewState.BLIND_REVALIDATED,
    )
    q03hr.wait_for_lane_release(jobs)


def test_shared_lane_rejects_cross_type_launches_before_claim(tmp_path) -> None:
    client = q03hr.RevalidationNaturalClient()
    service, store, jobs, repository_path, base, target = q03hr.make_revalidation_service(
        tmp_path,
        client,
    )
    review_id = q03hr.establish_initial_review(service, store, jobs, base, target)
    finding_id = q03hr.establish_byte_provenance(service, review_id)

    targeted_revalidation_id = q03hr.prepare_revalidation(
        service,
        repository_path,
        review_id,
        target,
    )
    targeted_blind = service.transmit_blind_revalidation(targeted_revalidation_id)
    if targeted_blind["state"] == ReviewState.TRANSMITTING.value:
        q03hr.wait_for_revalidation_state(
            store,
            targeted_revalidation_id,
            ReviewState.BLIND_REVALIDATED,
        )
    q03hr.wait_for_lane_release(jobs)

    targeted_revalidation = store.get_revalidation(targeted_revalidation_id)
    remediation_commit = targeted_revalidation["identity"]["target_commit"]
    blind_proposal = service.prepare_revalidation(
        review_id,
        target_commit=remediation_commit,
        base_commit=target,
        verification=verification(),
    )
    blind_revalidation_id = str(blind_proposal["revalidation_id"])

    held_review_id = q03hr.prepare_initial_review(service, base, target)
    client.block_next = True
    client.entered.clear()
    client.release.clear()
    held = service.transmit_review(held_review_id)
    assert held["state"] == ReviewState.TRANSMITTING.value
    assert client.entered.wait(timeout=5)

    calls_before = len(client.calls)
    review_attempts_before = list(store.get_review(review_id)["attempts"])
    blind_attempts_before = list(store.get_revalidation(blind_revalidation_id)["attempts"])
    targeted_attempts_before = list(
        store.get_revalidation(targeted_revalidation_id)["attempts"]
    )

    with pytest.raises(OXUnavailableError):
        service.continue_message(review_id, "This must not claim while initial is active.")
    with pytest.raises(OXUnavailableError):
        service.transmit_blind_revalidation(blind_revalidation_id)
    with pytest.raises(OXUnavailableError):
        service.run_targeted_revalidation(targeted_revalidation_id, [finding_id])

    assert len(client.calls) == calls_before
    assert store.get_review(review_id)["attempts"] == review_attempts_before
    assert store.get_revalidation(blind_revalidation_id)["attempts"] == blind_attempts_before
    assert (
        store.get_revalidation(targeted_revalidation_id)["attempts"]
        == targeted_attempts_before
    )

    client.release.set()
    q03hr.wait_for_review_state(store, held_review_id, ReviewState.REVIEWED)
    q03hr.wait_for_lane_release(jobs)


def test_targeted_revalidation_routes_directly_to_background_service(monkeypatch) -> None:
    class LaunchService:
        def __init__(self) -> None:
            self.calls = []

        def run_targeted_revalidation(self, revalidation_id: str, finding_ids: list[str]):
            self.calls.append((revalidation_id, finding_ids))
            return {
                "revalidation_id": revalidation_id,
                "attempt_id": "OX-000001-A003",
                "state": "TRANSMITTING",
                "launch_accepted": True,
            }

    service = LaunchService()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("background targeted revalidation must not use to_thread")

    monkeypatch.setattr(server, "_ox_service", lambda: service)
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_revalidate(
            review_id="OX-000001",
            revalidation_id="OX-000001-RV001",
            targeted=True,
            finding_ids=["OX-000001-F001"],
        )
    )

    assert service.calls == [("OX-000001-RV001", ["OX-000001-F001"])]
    assert result["state"] == "TRANSMITTING"
    assert result["launch_accepted"] is True


def test_retry_revalidation_routes_directly_with_renewed_approval(monkeypatch) -> None:
    class LaunchService:
        def __init__(self) -> None:
            self.calls = []

        def retry_revalidation(
            self,
            revalidation_id: str,
            *,
            renewed_approval: bool,
        ):
            self.calls.append((revalidation_id, renewed_approval))
            return {
                "revalidation_id": revalidation_id,
                "attempt_id": "OX-000001-A003",
                "state": "TRANSMITTING",
                "launch_accepted": True,
            }

    service = LaunchService()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("background revalidation retry must not use to_thread")

    monkeypatch.setattr(server, "_ox_service", lambda: service)
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_revalidate(
            review_id="OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
            retry=True,
        )
    )

    assert service.calls == [("OX-000001-RV001", True)]
    assert result["state"] == "TRANSMITTING"
    assert result["launch_accepted"] is True


def test_blind_revalidation_routes_directly_to_background_service(monkeypatch) -> None:
    class LaunchService:
        def __init__(self) -> None:
            self.calls = []

        def transmit_blind_revalidation(self, revalidation_id: str):
            self.calls.append(revalidation_id)
            return {
                "revalidation_id": revalidation_id,
                "attempt_id": "OX-000001-A002",
                "state": "TRANSMITTING",
                "launch_accepted": True,
            }

    service = LaunchService()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("background blind revalidation must not use to_thread")

    monkeypatch.setattr(server, "_ox_service", lambda: service)
    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)

    result = asyncio.run(
        _invoke_revalidate(
            review_id="OX-000001",
            revalidation_id="OX-000001-RV001",
            approve=True,
        )
    )

    assert service.calls == ["OX-000001-RV001"]
    assert result["state"] == "TRANSMITTING"
    assert result["launch_accepted"] is True
