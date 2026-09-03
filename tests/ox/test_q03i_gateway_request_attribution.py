from pathlib import Path

from byte_mcp.ox.client import OXClient
from byte_mcp.ox.settings import OXSettings

SECRET = "SENTINEL-SECRET"
ATTEMPT_ID = "OX-000001-A001"
MESSAGES = [
    {"role": "system", "content": "You are an independent validator."},
    {"role": "user", "content": "Review this bounded packet."},
]
SUCCESS_BODY = {
    "id": "chatcmpl-q03i",
    "model": "zai/glm-5.3-flash",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "The packet is reviewable."},
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    },
}


class SuccessfulResponse:
    status_code = 200

    def json(self):
        return SUCCESS_BODY


def make_client() -> OXClient:
    settings = OXSettings(SECRET, Path("repositories.json"), Path("evidence"))
    return OXClient(settings)


def test_q03i_provider_request_is_attributed_by_component_review_and_attempt(monkeypatch) -> None:
    captured_headers = None

    async def capture_post(*, transport, headers, body):
        nonlocal captured_headers
        captured_headers = dict(headers)
        return SuccessfulResponse()

    monkeypatch.setattr("byte_mcp.ox.client._post_with_total_deadline", capture_post)

    make_client().complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert captured_headers is not None
    reporting_tags = captured_headers["ai-reporting-tags"]
    assert reporting_tags == (
        "component:byte-mcp-ox,review:OX-000001,attempt:OX-000001-A001"
    )
    assert SECRET not in reporting_tags
    assert "Review this bounded packet." not in reporting_tags
