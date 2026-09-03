import json
from pathlib import Path

import httpx

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


def make_client(handler):
    settings = OXSettings(SECRET, Path("repositories.json"), Path("evidence"))
    return OXClient(settings, transport=httpx.MockTransport(handler))


def test_q03i_provider_request_is_attributed_by_component_review_and_attempt() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCESS_BODY)

    make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["ai-reporting-tags"] == (
        "component:byte-mcp-ox,review:OX-000001,attempt:OX-000001-A001"
    )
    assert SECRET not in request.headers["ai-reporting-tags"]
    assert "Review this bounded packet." not in request.headers["ai-reporting-tags"]
    assert json.loads(request.content)["stream"] is False
