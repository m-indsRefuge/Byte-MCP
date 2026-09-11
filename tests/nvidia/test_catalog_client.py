import json

import httpx
import pytest

from byte_mcp.nvidia.catalog import NvidiaCatalogClient
from byte_mcp.nvidia.errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from byte_mcp.nvidia.settings import NvidiaHostedSettings

KEY = "NVIDIA-SENTINEL-SECRET"


def settings(api_key=KEY):
    return NvidiaHostedSettings(api_key=api_key, catalog_timeout_seconds=10)


def test_discover_makes_exactly_one_get_to_models_with_internal_bearer_header():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "nvidia/example-model"}]})

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    snapshot = client.discover()
    assert snapshot.model_ids == ("nvidia/example-model",)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://integrate.api.nvidia.com/v1/models"
    assert requests[0].headers["Authorization"] == f"Bearer {KEY}"


def test_missing_key_fails_before_transport():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    client = NvidiaCatalogClient(settings(None), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.CONFIGURATION
    assert calls == 0


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (302, NvidiaCatalogFailureKind.REQUEST),
        (400, NvidiaCatalogFailureKind.REQUEST),
        (401, NvidiaCatalogFailureKind.AUTHENTICATION),
        (403, NvidiaCatalogFailureKind.PERMISSION),
        (404, NvidiaCatalogFailureKind.UNAVAILABLE),
        (429, NvidiaCatalogFailureKind.RATE_LIMIT),
        (500, NvidiaCatalogFailureKind.UNAVAILABLE),
        (503, NvidiaCatalogFailureKind.UNAVAILABLE),
    ],
)
def test_http_rejections_are_bounded_and_never_retried(status, kind):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            json={"error": {"message": "provider text must not propagate", "secret": KEY}},
        )

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is kind
    assert str(excinfo.value) == kind.value
    assert KEY not in str(excinfo.value)
    assert calls == 1


def test_malformed_json_is_protocol_failure_without_retry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"not-json")

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL
    assert calls == 1


def test_catalog_response_body_is_capped_at_one_megabyte():
    oversized = b"{" + (b"x" * 1_000_001) + b"}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized)

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL


def test_transport_exception_is_safe_and_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("SENTINEL-TRANSPORT-TEXT", request=request)

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.TRANSPORT
    assert "SENTINEL-TRANSPORT-TEXT" not in str(excinfo.value)
    assert calls == 1


def test_unknown_response_headers_are_not_returned():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-sentinel-secret": "SERVER-HEADER-SECRET"},
            content=json.dumps({"data": [{"id": "nvidia/example-model"}]}).encode(),
        )

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    snapshot = client.discover()
    assert "SERVER-HEADER-SECRET" not in repr(snapshot)


@pytest.mark.parametrize("failure", ["transport", "json"])
def test_catalog_error_does_not_retain_sensitive_exception_context(failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ReadError(KEY, request=request)
        return httpx.Response(200, content=(KEY + " invalid json").encode())

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as caught:
        client.discover()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_redirect_location_is_never_followed():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(307, headers={"Location": "https://example.invalid/steal"})

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as caught:
        client.discover()
    assert caught.value.kind is NvidiaCatalogFailureKind.REQUEST
    assert len(calls) == 1
