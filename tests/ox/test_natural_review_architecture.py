from byte_mcp.ox.models import ReviewState
from byte_mcp.ox.protocol import build_initial_messages
from tests.ox.test_review_service import RecordingClient, make_service, prepare


def test_initial_prompt_requests_natural_engineering_review() -> None:
    messages = build_initial_messages({"artifact": "value"}, objective="Review it.")

    system = messages[0]["content"]
    assert "independent" in system.lower()
    assert "falsifiable" in system.lower()
    assert "natural" in system.lower() or "markdown" in system.lower()
    assert "ox-findings-v1" not in system
    assert "Return only JSON" not in system


def test_initial_review_uses_natural_provider_response_without_findings_parse(tmp_path) -> None:
    client = RecordingClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is False
    assert result["state"] == ReviewState.REVIEWED.value
    assert result["response"]
    assert "findings" not in result
    assert store.get_review(proposal["review_id"])["attempts"][-1]["outcome"] == "COMPLETED"
