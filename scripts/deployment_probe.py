"""Provider-free, exact MCP tool discovery for deployment qualification."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

LIVE_URL = "http://127.0.0.1:8000/mcp"


def tool_names(tools: Any) -> list[str]:
    """Reject incomplete or malformed discovery instead of normalizing it away."""
    if not isinstance(tools, list) or not tools:
        raise ValueError("Discovery must contain a nonempty tool list.")
    names: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or any(character.isspace() or ord(character) < 32 for character in name)
        ):
            raise ValueError("Discovery contains an invalid tool name.")
        names.append(name)
    if len(set(names)) != len(names):
        raise ValueError("Discovery contains duplicate tool names.")
    return sorted(names)


@contextmanager
def no_connections():
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Network connections are forbidden during offline discovery.")

    with (
        patch.object(socket.socket, "connect", denied),
        patch.object(socket.socket, "connect_ex", denied),
        patch.object(socket.socket, "sendto", denied),
        patch.object(socket, "create_connection", denied),
        patch.object(asyncio.BaseEventLoop, "create_connection", denied),
        patch.object(asyncio.BaseEventLoop, "create_datagram_endpoint", denied),
    ):
        yield


async def offline_tools(repo: Path) -> list[str]:
    # The event loop already exists before blocking sockets (Windows uses a wakeup socket).
    with no_connections(), patch.object(sys, "dont_write_bytecode", True):
        server = import_module("byte_mcp.server")
        origin = getattr(server, "__file__", None)
        expected = repo / "src" / "byte_mcp" / "server.py"
        if origin is None or Path(origin).resolve(strict=True) != expected.resolve(strict=True):
            raise ValueError("Imported MCP server does not originate from the expected repository.")
        return tool_names(await server.mcp.list_tools())


async def live_tools(url: str = LIVE_URL) -> list[str]:
    # Ignore proxy environment and reject redirects so discovery stays on the fixed loopback URL.
    async with (
        httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15.0) as client,
        streamable_http_client(url, http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        if getattr(result, "nextCursor", None) is not None:
            raise ValueError("Paginated discovery is not accepted as a complete tool surface.")
        return tool_names(result.tools)


async def probe(repo: Path, *, live: bool = False, live_url: str = LIVE_URL) -> dict[str, Any]:
    resolved = repo.resolve(strict=True)
    if not resolved.is_dir() or not (resolved / "src" / "byte_mcp" / "server.py").is_file():
        raise ValueError("Expected repository does not contain the MCP server.")
    async with asyncio.timeout(30):
        names = await offline_tools(resolved)
        if live:
            names = await live_tools(live_url)
    return {"repo_path": str(resolved), "tools": names, "tool_count": len(names)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--live-url", default=LIVE_URL)
    args = parser.parse_args()
    result = asyncio.run(probe(args.repo, live=args.live, live_url=args.live_url))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
