import pytest

from byte_mcp.errors import OXApprovalError, OXTransportError
from byte_mcp.ox.live_service import OXReviewService
from byte_mcp.ox.models import ProviderResult, ProviderUsage
from tests.ox.test_review_service import make_service, prepare, verification


class SequenceClient:
    def __init__(self, outcomes: list[ProviderResult | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def complete(self, messages, *, json_mode: bool, attempt_id: str) -> ProviderResult:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "json_mode": json_mode,
                "attempt_id": attempt_id,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def natural_result(attempt_label: str) -> ProviderResult:
    content = f"Natural OX response for {attempt_label}."
    raw = {
        "id": f"response-{attempt_label}",
        "model": "zai/glm-5.3-flash",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
    }
    return ProviderResult(
        content=content,
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


def test_explicit_initial_retry_requires_renewed_approval_and_allocates_a002(tmp_path) -> None:
    client = SequenceClient(
        [
            OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"),
            natural_result("retry"),
        ]
    )
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    assert first["attempt_id"] == f"{proposal['review_id']}-A001"
    assert first["attempt_outcome"] == "OUTCOME_UNKNOWN"

    with pytest.raises(OXApprovalError):
        service.retry_review(proposal["review_id"], renewed_approval=False)
    assert len(client.calls) == 1

    retried = service.retry_review(proposal["review_id"], renewed_approval=True)

    assert len(client.calls) == 2
    assert retried["attempt_id"] == f"{proposal['review_id']}-A002"
    assert retried["state"] == "REVIEWED"
    assert retried["attempt_outcome"] == "COMPLETED"
    assert retried["replayed"] is False
    attempts = store.get_review(proposal["review_id"])["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        f"{proposal['review_id']}-A001",
        f"{proposal['review_id']}-A002",
    ]
    identity = store.read_attempt_identity(
        proposal["review_id"], f"{proposal['review_id']}-A002"
    )
    assert identity["phase"] == "initial-retry"


def test_continuation_unknown_returns_structured_terminal_result(tmp_path) -> None:
    client = SequenceClient(
        [
            natural_result("initial"),
            OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"),
        ]
    )
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])

    result = service.continue_message(proposal["review_id"], "Check one more edge case.")

    assert len(client.calls) == 2
    assert result["review_id"] == proposal["review_id"]
    assert result["attempt_id"] == f"{proposal['review_id']}-A002"
    assert result["state"] == "OUTCOME_UNKNOWN"
    assert result["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert result["safe_error_type"] == "OXTransportError"
    assert result["response_available"] is False
    assert result["replayed"] is False
    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["safe_error_type"] == "OXTransportError"
    identity = store.read_attempt_identity(
        proposal["review_id"], f"{proposal['review_id']}-A002"
    )
    assert identity["phase"] == "continuation"


def test_blind_revalidation_unknown_returns_structured_terminal_result(tmp_path) -> None:
    client = SequenceClient(
        [
            natural_result("initial"),
            OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"),
        ]
    )
    service, store, _, base, target, _ = make_live_service(tmp_path, client)
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])
    prepared = service.prepare_revalidation(
        proposal["review_id"],
        target_commit=target,
        base_commit=base,
        verification=verification(),
    )

    result = service.transmit_blind_revalidation(prepared["revalidation_id"])

    assert len(client.calls) == 2
    assert result["review_id"] == proposal["review_id"]
    assert result["revalidation_id"] == prepared["revalidation_id"]
    assert result["attempt_id"] == f"{proposal['review_id']}-A002"
    assert result["phase"] == "blind"
    assert result["state"] == "OUTCOME_UNKNOWN"
    assert result["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert result["safe_error_type"] == "OXTransportError"
    assert result["response_available"] is False
    revalidation = store.get_revalidation(prepared["revalidation_id"])
    attempt = revalidation["attempts"][-1]
    assert attempt["safe_error_type"] == "OXTransportError"
