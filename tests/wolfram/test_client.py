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
    seen = {}

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
    assert request.method == "GET"
    assert str(request.url).startswith("https://www.wolframalpha.com/api/v1/llm-api?")
    assert request.url.params["input"] == "2+2"
    assert request.url.params["maxchars"] == "6800"
    assert "appid" not in request.url.params
    assert set(request.url.params) == {"input", "maxchars"}
    assert request.headers["Authorization"] == "Bearer TEST-WOLFRAM-APPID"
    assert result.result_url is not None
    assert result.result_url.startswith("https://www.wolframalpha.com/input?")


def test_provider_failure_is_not_retried(wolfram_settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="unavailable")

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
        (500, WolframProviderError),
        (503, WolframProviderError),
    ],
)
def test_http_error_mapping(wolfram_settings, status: int, error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="safe-provider-message")

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(error_type):
        client.query("2+2", 6800)


def test_501_excerpt_is_bounded_and_redacts_appid(wolfram_settings) -> None:
    body = "TEST-WOLFRAM-APPID " + ("x" * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(501, text=body)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframUninterpretableError) as caught:
        client.query("nonsense", 6800)
    message = str(caught.value)
    assert "TEST-WOLFRAM-APPID" not in message
    assert len(message) < 650


def test_connect_error_maps_to_transport(wolfram_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframTransportError):
        client.query("2+2", 6800)


def test_connect_timeout_maps_to_transport(wolfram_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout", request=request)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframTransportError):
        client.query("2+2", 6800)


def test_read_timeout_maps_to_timeout(wolfram_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout", request=request)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframTimeoutError):
        client.query("2+2", 6800)


def test_other_transport_error_maps_to_transport(wolfram_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read error", request=request)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(WolframTransportError):
        client.query("2+2", 6800)


def test_success_without_result_url_returns_none(wolfram_settings) -> None:
    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="Result:\n4")),
    )
    result = client.query("2+2", 9)
    assert result.text == "Result:\n4"
    assert result.result_url is None
    assert result.response_chars == len("Result:\n4")
    assert result.response_at_limit is True


def test_empty_success_body_is_protocol_error(wolfram_settings) -> None:
    from byte_mcp.errors import WolframProtocolError

    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="   ")),
    )
    with pytest.raises(WolframProtocolError):
        client.query("2+2", 6800)
