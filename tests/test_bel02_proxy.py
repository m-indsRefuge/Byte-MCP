"""Tests for the read-only BEL-02 Byte-MCP proxy."""

from __future__ import annotations

import json

import httpx
import pytest

from byte_mcp.bel02_proxy import (
    Bel02Proxy,
    Bel02ProxyError,
    Bel02ProxySettings,
    _enforce_response_bound,
)


def test_default_bel02_proxy_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTE_MCP_BEL02_URL", raising=False)
    monkeypatch.delenv("BYTE_MCP_BEL02_TIMEOUT_SECONDS", raising=False)

    settings = Bel02ProxySettings.load(max_response_chars=1234)

    assert settings.url == "http://127.0.0.1:8012/mcp"
    assert settings.timeout_seconds == 10.0
    assert settings.max_response_chars == 1234


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8012/mcp",
        "http://example.com:8012/mcp",
        "http://127.0.0.1:8012/not-mcp",
        "http://user:pass@127.0.0.1:8012/mcp",
        "http://127.0.0.1:80/mcp",
        "http://127.0.0.1:8012/mcp?x=1",
    ],
)
def test_bel02_proxy_rejects_unsafe_urls(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("BYTE_MCP_BEL02_URL", url)

    with pytest.raises(Bel02ProxyError):
        Bel02ProxySettings.load()


@pytest.mark.anyio
async def test_bel02_proxy_has_no_generic_forwarding() -> None:
    proxy = Bel02Proxy(Bel02ProxySettings())

    with pytest.raises(Bel02ProxyError, match="not exposed"):
        await proxy.call("bel02_run")


def test_bel02_proxy_enforces_response_bound() -> None:
    with pytest.raises(Bel02ProxyError, match="response bound"):
        _enforce_response_bound({"stdout": "x" * 100}, 20)


@pytest.mark.anyio
async def test_stateless_raw_mcp_sequence_returns_structured_receipt() -> None:
    observed: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed.append(
            {
                "body": body,
                "session": request.headers.get("mcp-session-id"),
                "protocol": request.headers.get("mcp-protocol-version"),
            }
        )

        method = body["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "BEL-02", "version": "0.1.0"},
                    },
                },
            )

        if method == "notifications/initialized":
            return httpx.Response(202)

        if method == "tools/call":
            assert body["params"] == {
                "name": "bel02_git_diff",
                "arguments": {},
            }
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "structuredContent": {
                            "ok": True,
                            "exit_code": 0,
                            "stdout": "expected diff",
                        }
                    },
                },
            )

        raise AssertionError(f"unexpected MCP method: {method}")

    proxy = Bel02Proxy(
        Bel02ProxySettings(),
        transport=httpx.MockTransport(handler),
    )

    result = await proxy.call("bel02_git_diff")

    assert result == {
        "ok": True,
        "exit_code": 0,
        "stdout": "expected diff",
    }
    assert [entry["body"]["method"] for entry in observed] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert observed[0]["session"] is None
    assert observed[0]["protocol"] is None
    assert observed[1]["protocol"] == "2025-11-25"
    assert observed[2]["protocol"] == "2025-11-25"


@pytest.mark.anyio
async def test_stateful_mcp_session_headers_are_forwarded() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)

        if body["method"] == "initialize":
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "mcp-session-id": "test-session",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "BEL-02", "version": "0.1.0"},
                    },
                },
            )

        assert request.headers["mcp-session-id"] == "test-session"
        assert request.headers["mcp-protocol-version"] == "2025-11-25"

        if body["method"] == "notifications/initialized":
            return httpx.Response(202)

        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"structuredContent": {"mode": "D0_CANARY_ONLY"}},
            },
        )

    proxy = Bel02Proxy(
        Bel02ProxySettings(),
        transport=httpx.MockTransport(handler),
    )

    result = await proxy.call("bel02_status")

    assert result == {"mode": "D0_CANARY_ONLY"}
    assert calls == 3


@pytest.mark.anyio
async def test_bel02_proxy_normalizes_transport_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    proxy = Bel02Proxy(
        Bel02ProxySettings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Bel02ProxyError, match="timed out"):
        await proxy.call("bel02_status")


@pytest.mark.anyio
async def test_bel02_proxy_rejects_mcp_protocol_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)

        if body["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "BEL-02", "version": "0.1.0"},
                    },
                },
            )

        if body["method"] == "notifications/initialized":
            return httpx.Response(202)

        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32603, "message": "synthetic failure"},
            },
        )

    proxy = Bel02Proxy(
        Bel02ProxySettings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Bel02ProxyError, match="protocol error"):
        await proxy.call("bel02_git_status")
