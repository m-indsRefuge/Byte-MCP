import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from byte_mcp.errors import OXTransportError
from byte_mcp.ox import client as client_module
from byte_mcp.ox.client import OXClient


class _DaemonThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class _TrickleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    request_started_at = None

    def log_message(self, format, *args):
        return

    def do_POST(self):
        type(self).request_started_at = time.monotonic()
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)

        payload = json.dumps(
            {
                "id": "response-OX-000001-A001",
                "model": "zai/glm-5.3-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "{}",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

        chunks = 12
        chunk_size = max(1, len(payload) // chunks)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()

        try:
            offset = 0
            while offset < len(payload):
                end = min(len(payload), offset + chunk_size)
                self.wfile.write(payload[offset:end])
                self.wfile.flush()
                offset = end
                if offset < len(payload):
                    time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.close_connection = True


def _settings():
    return SimpleNamespace(
        api_key="test-key",
        max_output_tokens=128,
    )


def test_total_provider_deadline_defaults_to_900_seconds() -> None:
    assert client_module._TOTAL_DEADLINE_SECONDS == 900.0


def test_trickle_response_cannot_extend_request_beyond_absolute_deadline(
    monkeypatch,
) -> None:
    server = _DaemonThreadingHTTPServer(("127.0.0.1", 0), _TrickleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    monkeypatch.setattr(
        client_module,
        "_GATEWAY_URL",
        f"http://{host}:{port}/v1/chat/completions",
    )
    monkeypatch.setattr(
        client_module,
        "_TIMEOUT",
        httpx.Timeout(connect=0.2, read=0.05, write=0.2, pool=0.2),
    )
    monkeypatch.setattr(
        client_module,
        "_TOTAL_DEADLINE_SECONDS",
        0.12,
        raising=False,
    )

    client = OXClient(_settings())

    _TrickleHandler.request_started_at = None
    try:
        with pytest.raises(OXTransportError) as exc_info:
            client.complete(
                [{"role": "user", "content": "bounded canary"}],
                json_mode=False,
                attempt_id="OX-000001-A001",
            )
        raised_at = time.monotonic()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert exc_info.value.attempt_outcome == "OUTCOME_UNKNOWN"
    assert _TrickleHandler.request_started_at is not None
    request_elapsed = raised_at - _TrickleHandler.request_started_at
    assert request_elapsed < 0.25, (
        "provider request exceeded its absolute wall-clock deadline; "
        f"request_elapsed={request_elapsed:.3f}s"
    )
