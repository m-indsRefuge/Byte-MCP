"""Read-only proxy from Byte-MCP to the local BEL-02 MCP service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp.types import LATEST_PROTOCOL_VERSION

_ALLOWED_TOOLS = frozenset(
    {
        "bel02_status",
        "bel02_git_status",
        "bel02_git_diff",
    }
)
_BASE_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


class Bel02ProxyError(RuntimeError):
    """Normalized BEL-02 proxy failure."""


@dataclass(frozen=True, slots=True)
class Bel02ProxySettings:
    url: str = "http://127.0.0.1:8012/mcp"
    timeout_seconds: float = 10.0
    max_response_chars: int = 60_000

    @classmethod
    def load(cls, *, max_response_chars: int = 60_000) -> Bel02ProxySettings:
        url = os.getenv(
            "BYTE_MCP_BEL02_URL",
            "http://127.0.0.1:8012/mcp",
        ).strip()
        timeout_raw = os.getenv(
            "BYTE_MCP_BEL02_TIMEOUT_SECONDS",
            "10",
        ).strip()

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise Bel02ProxyError(
                "BYTE_MCP_BEL02_TIMEOUT_SECONDS must be numeric."
            ) from exc

        if not 1.0 <= timeout_seconds <= 30.0:
            raise Bel02ProxyError(
                "BYTE_MCP_BEL02_TIMEOUT_SECONDS must be between 1 and 30."
            )

        parsed = urlsplit(url)
        if parsed.scheme != "http":
            raise Bel02ProxyError("BEL-02 proxy must use loopback HTTP.")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise Bel02ProxyError("BEL-02 proxy must remain loopback-only.")
        if parsed.username is not None or parsed.password is not None:
            raise Bel02ProxyError("BEL-02 proxy URL must not contain credentials.")
        if parsed.path != "/mcp" or parsed.query or parsed.fragment:
            raise Bel02ProxyError(
                "BEL-02 proxy URL must point exactly to /mcp without query or fragment."
            )

        try:
            port = parsed.port
        except ValueError as exc:
            raise Bel02ProxyError("BEL-02 proxy URL contains an invalid port.") from exc

        if port is None or not 1024 <= port <= 65535:
            raise Bel02ProxyError(
                "BEL-02 proxy URL must specify a port between 1024 and 65535."
            )

        return cls(
            url=url,
            timeout_seconds=timeout_seconds,
            max_response_chars=max_response_chars,
        )


def _response_json(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").casefold()
    if "application/json" not in content_type and "+json" not in content_type:
        raise Bel02ProxyError(
            f"BEL-02 returned unsupported content type: {content_type or '<missing>'}."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise Bel02ProxyError("BEL-02 returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise Bel02ProxyError("BEL-02 returned a non-object JSON response.")
    return payload


def _extract_payload(response_payload: dict[str, Any]) -> dict[str, Any]:
    if "error" in response_payload:
        raise Bel02ProxyError("BEL-02 returned an MCP protocol error.")

    result = response_payload.get("result")
    if not isinstance(result, dict):
        raise Bel02ProxyError("BEL-02 response did not contain an MCP result.")

    if result.get("isError") is True or result.get("is_error") is True:
        raise Bel02ProxyError("BEL-02 returned an MCP tool error.")

    structured = result.get("structuredContent")
    if structured is None:
        structured = result.get("structured_content")

    if isinstance(structured, dict):
        return structured

    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    raise Bel02ProxyError("BEL-02 response did not contain a structured receipt.")


def _enforce_response_bound(
    payload: dict[str, Any],
    max_response_chars: int,
) -> dict[str, Any]:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(rendered) > max_response_chars:
        raise Bel02ProxyError(
            "BEL-02 receipt exceeded Byte-MCP's configured response bound."
        )
    return payload


class Bel02Proxy:
    """Fixed read-only BEL-02 tool proxy over bounded loopback MCP HTTP."""

    def __init__(
        self,
        settings: Bel02ProxySettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def _headers(
        self,
        *,
        session_id: str | None = None,
        protocol_version: str | None = None,
    ) -> dict[str, str]:
        headers = dict(_BASE_HEADERS)
        if session_id:
            headers["mcp-session-id"] = session_id
        if protocol_version:
            headers["mcp-protocol-version"] = protocol_version
        return headers

    async def _post(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
        *,
        session_id: str | None = None,
        protocol_version: str | None = None,
    ) -> httpx.Response:
        response = await client.post(
            self.settings.url,
            headers=self._headers(
                session_id=session_id,
                protocol_version=protocol_version,
            ),
            json=body,
        )
        response.raise_for_status()
        return response

    async def _call_mcp(
        self,
        client: httpx.AsyncClient,
        tool_name: str,
    ) -> dict[str, Any]:
        initialize_response = await self._post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "byte-mcp-bel02-proxy",
                        "version": "0.1.0",
                    },
                },
            },
        )
        initialize_payload = _response_json(initialize_response)
        if "error" in initialize_payload:
            raise Bel02ProxyError("BEL-02 MCP initialization failed.")

        initialize_result = initialize_payload.get("result")
        if not isinstance(initialize_result, dict):
            raise Bel02ProxyError("BEL-02 initialization returned no result.")

        protocol_version = initialize_result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise Bel02ProxyError(
                "BEL-02 initialization returned no protocol version."
            )

        session_id = initialize_response.headers.get("mcp-session-id")

        await self._post(
            client,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            session_id=session_id,
            protocol_version=protocol_version,
        )

        tool_response = await self._post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {},
                },
            },
            session_id=session_id,
            protocol_version=protocol_version,
        )
        return _extract_payload(_response_json(tool_response))

    async def call(self, tool_name: str) -> dict[str, Any]:
        if tool_name not in _ALLOWED_TOOLS:
            raise Bel02ProxyError(
                f"BEL-02 tool is not exposed through Byte-MCP: {tool_name}"
            )

        timeout = httpx.Timeout(
            connect=min(3.0, self.settings.timeout_seconds),
            read=self.settings.timeout_seconds,
            write=min(5.0, self.settings.timeout_seconds),
            pool=min(3.0, self.settings.timeout_seconds),
        )

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                payload = await self._call_mcp(client, tool_name)
        except Bel02ProxyError:
            raise
        except httpx.TimeoutException as exc:
            raise Bel02ProxyError("BEL-02 proxy request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise Bel02ProxyError(
                f"BEL-02 returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise Bel02ProxyError(
                f"BEL-02 transport failed: {type(exc).__name__}."
            ) from exc
        except Exception as exc:
            raise Bel02ProxyError(
                f"BEL-02 is unavailable: {type(exc).__name__}: {exc}"
            ) from exc

        return _enforce_response_bound(
            payload,
            self.settings.max_response_chars,
        )
