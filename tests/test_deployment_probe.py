import asyncio
import importlib.util
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deployment_probe", REPO / "scripts/deployment_probe.py"
)
assert SPEC is not None and SPEC.loader is not None
probe_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_module)


def test_offline_real_server_discovery_keeps_providers_lazy(monkeypatch):
    from byte_mcp import server

    def forbidden(*args, **kwargs):
        raise AssertionError("A provider or file service was initialized.")

    monkeypatch.setattr(server, "service", forbidden)
    monkeypatch.setattr(server, "wolfram_runtime", forbidden)
    monkeypatch.setattr(server, "nvidia_review_runtime", forbidden)
    monkeypatch.setattr(server, "ox_runtime", forbidden)
    result = asyncio.run(probe_module.probe(REPO))
    assert result == {
        "repo_path": str(REPO),
        "tools": [
            "fetch",
            "list_directory",
            "list_roots",
            "nvidia_get_review",
            "nvidia_query",
            "nvidia_review",
            "ox_get_review",
            "ox_review",
            "search",
            "wolfram_query",
        ],
        "tool_count": 10,
    }


@pytest.mark.parametrize("names", [[], [""], [" x"], ["a b"], ["a\x00"], [None], ["x", "x"]])
def test_rejects_malformed_or_duplicate_tool_sets(names):
    with pytest.raises(ValueError):
        probe_module.tool_names([SimpleNamespace(name=name) for name in names])


@pytest.mark.parametrize("live", [False, True])
def test_rejects_wrong_server_origin_before_any_live_connection(monkeypatch, live):
    monkeypatch.setattr(
        probe_module, "import_module", lambda _: SimpleNamespace(__file__=__file__)
    )
    async def forbidden_live():
        raise AssertionError("Wrong import origin must stop before live discovery.")

    monkeypatch.setattr(probe_module, "live_tools", forbidden_live)
    with pytest.raises(ValueError, match="originate"):
        asyncio.run(probe_module.probe(REPO, live=live))


def test_offline_import_attempt_to_connect_is_denied(monkeypatch):
    def unsafe_import(name):
        socket.create_connection(("127.0.0.1", 8000))

    monkeypatch.setattr(probe_module, "import_module", unsafe_import)
    with pytest.raises(RuntimeError, match="forbidden"):
        asyncio.run(probe_module.probe(REPO))


def test_offline_async_connection_is_denied():
    async def attempt():
        with probe_module.no_connections():
            await asyncio.open_connection("127.0.0.1", 8000)

    with pytest.raises(RuntimeError, match="forbidden"):
        asyncio.run(attempt())


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_offline_blocks_connections_and_restores_socket(method):
    original = getattr(socket.socket, method)
    with (
        socket.socket() as connection,
        probe_module.no_connections(),
        pytest.raises(RuntimeError, match="forbidden"),
    ):
        getattr(connection, method)(("127.0.0.1", 8000))
    assert getattr(socket.socket, method) is original


@pytest.mark.parametrize("cursor", [None, "more", ""])
def test_live_only_initializes_and_lists_tools(monkeypatch, cursor):
    events = []

    @asynccontextmanager
    async def transport(url, *, http_client):
        assert url == "http://127.0.0.1:8000/mcp"
        assert http_client.follow_redirects is False
        assert http_client.trust_env is False
        events.append("transport")
        yield "read", "write", None

    class Session:
        def __init__(self, read, write):
            assert (read, write) == ("read", "write")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            events.append("initialize")

        async def list_tools(self):
            events.append("list_tools")
            return SimpleNamespace(tools=[SimpleNamespace(name="fetch")], nextCursor=cursor)

    monkeypatch.setattr(probe_module, "streamable_http_client", transport)
    monkeypatch.setattr(probe_module, "ClientSession", Session)
    if cursor is not None:
        with pytest.raises(ValueError, match="Paginated"):
            asyncio.run(probe_module.probe(REPO, live=True))
    else:
        assert asyncio.run(probe_module.probe(REPO, live=True))["tools"] == ["fetch"]
    assert events == ["transport", "initialize", "list_tools"]
