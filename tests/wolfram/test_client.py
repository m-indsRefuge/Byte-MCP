import httpx
import pytest

from byte_mcp.errors import (
    WolframAuthenticationError,
    WolframProviderError,
    WolframRateLimitError,
    WolframRequestError,
    WolframTimeoutError,
    WolframTransportError,
    WolframUninterpretableError,
)
from byte_mcp.wolfram.client import WolframLLMClient


def test_client_uses_fixed_endpoint_bearer_auth_and_input_only(wolfram_settings) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            text=(
                'Query:\n"2+2"\n\nResult:\n4\n\n'
                'Wolfram|Alpha website result for "2+2":\n'
                'https://www.wolframalpha.com/input?i=2%2B2'
            ),
        )

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    result = client.query("2+2", 6800)

    request = seen["request"]
    assert str(request.url).startswith("https://www.wolframalpha.com/api/v1/llm-api?")
    assert request.url.params["input"] == "2+2"
    assert request.url.params["maxchars"] == "6800"
    assert "appid" not in request.url.params
    assert request.headers["Authorization"] == "Bearer TEST-WOLFRAM-APPID"
    assert result.result_url == "https://www.wolframalpha.com/input?i=2%2B2"
    assert "TEST-WOLFRAM-APPID" not in repr(client)


def test_client_never_retries_provider_failure(wolfram_settings) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="temporary failure")

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframProviderError):
        client.query("2+2", 6800)
    assert calls == 1


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, WolframRequestError),
        (403, WolframAuthenticationError),
        (429, WolframRateLimitError),
        (501, WolframUninterpretableError),
        (503, WolframProviderError),
    ],
)
def test_client_maps_http_failures(wolfram_settings, status, error_type) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="safe provider detail")

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(error_type) as caught:
        client.query("2+2", 6800)
    assert "TEST-WOLFRAM-APPID" not in str(caught.value)


def test_client_maps_connect_and_read_timeout(wolfram_settings) -> None:
    def connect_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    with pytest.raises(WolframTransportError):
        WolframLLMClient(
            wolfram_settings,
            transport=httpx.MockTransport(connect_handler),
        ).query("2+2", 6800)

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(WolframTimeoutError):
        WolframLLMClient(
            wolfram_settings,
            transport=httpx.MockTransport(timeout_handler),
        ).query("2+2", 6800)


def test_success_without_result_link_does_not_invent_one(wolfram_settings) -> None:
    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="Result:\n4")),
    )
    result = client.query("2+2", 6800)
    assert result.result == "Result:\n4"
    assert result.result_url is None
