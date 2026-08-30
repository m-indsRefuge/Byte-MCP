import threading
from concurrent.futures import ThreadPoolExecutor

from byte_mcp.errors import OXTransportError
from byte_mcp.ox.live_service import OXReviewService
from byte_mcp.ox.models import ProviderResult, ProviderUsage
from tests.ox.test_review_service import RecordingClient, make_service, prepare


class UnknownClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str):
        self.calls += 1
        raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")


class BlockingNaturalClient:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        raw = {
            "id": f"response-{attempt_id}",
            "model": "zai/glm-5.3-flash",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "No material defect identified in the supplied evidence.",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        }
        return ProviderResult(
            content=raw["choices"][0]["message"]["content"],
            usage=ProviderUsage(20, 10, 30, 0),
            response_id=raw["id"],
            model=raw["model"],
            raw_response=raw,
        )


def make_live_service(tmp_path, client):
    base_service, store, repository_path, base, target, registry_path = make_service(
        tmp_path, client
    )
    service = OXReviewService(
        base_service._settings,
        store,
        client,
        base_service._audit,
    )
    return service, store, repository_path, base, target, registry_path


def test_sequential_duplicate_after_unknown_replays_a001_without_provider_call(tmp_path) -> None:
    client = UnknownClient()
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    second = service.transmit_review(proposal["review_id"])

    assert client.calls == 1
    assert first["attempt_id"] == f"{proposal['review_id']}-A001"
    assert first["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert first["replayed"] is False
    assert second == {
        **first,
        "replayed": True,
    }
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        f"{proposal['review_id']}-A001"
    ]


def test_duplicate_after_completed_review_returns_status_without_provider_call(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    second = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert first["state"] == "REVIEWED"
    assert first["attempt_outcome"] == "COMPLETED"
    assert second["review_id"] == proposal["review_id"]
    assert second["attempt_id"] == f"{proposal['review_id']}-A001"
    assert second["state"] == "REVIEWED"
    assert second["attempt_outcome"] == "COMPLETED"
    assert second["safe_error_type"] is None
    assert second["response_available"] is True
    assert second["replayed"] is True
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert len(attempts) == 1


def test_concurrent_duplicate_observes_transmitting_a001_without_second_send(tmp_path) -> None:
    client = BlockingNaturalClient()
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service.transmit_review, proposal["review_id"])
        assert client.entered.wait(timeout=5)

        duplicate = service.transmit_review(proposal["review_id"])

        assert duplicate["review_id"] == proposal["review_id"]
        assert duplicate["attempt_id"] == f"{proposal['review_id']}-A001"
        assert duplicate["state"] == "TRANSMITTING"
        assert duplicate["attempt_outcome"] is None
        assert duplicate["safe_error_type"] is None
        assert duplicate["response_available"] is False
        assert duplicate["replayed"] is True
        assert client.calls == 1

        client.release.set()
        first = first_future.result(timeout=5)

    assert first["state"] == "REVIEWED"
    assert client.calls == 1
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        f"{proposal['review_id']}-A001"
    ]
