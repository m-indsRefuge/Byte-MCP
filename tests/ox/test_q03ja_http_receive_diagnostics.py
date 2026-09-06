import json
import socketserver
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from byte_mcp.errors import OXProtocolError, OXTransportError, OXTransportFailureKind
from byte_mcp.ox import client as client_module
from byte_mcp.ox.client import OXClient

MESSAGES = [{"role": "user", "content": "q03ja diagnostic"}]
ATTEMPT_ID = "OX-000001-A001"


class _RawHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, response: bytes, *, hold_open_seconds: float = 0.0) -> None:
        self.response = response
        self.hold_open_seconds = hold_open_seconds
        self.request_count = 0
        super().__init__(("127.0.0.1", 0), _RawHTTPHandler)


class _RawHTTPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _RawHTTPServer)
        server.request_count += 1
        received = bytearray()
        while b"\r\n\r\n" not in received:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            received.extend(chunk)
        head, body = bytes(received).split(b"\r\n\r\n", 1)
        content_length = 0
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1].strip())
                break
        remaining = max(0, content_length - len(body))
        while remaining > 0:
            chunk = self.request.recv(min(4096, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        if server.response:
            self.request.sendall(server.response)
        if server.hold_open_seconds:
            time.sleep(server.hold_open_seconds)


def _settings():
    return SimpleNamespace(api_key="test-key", max_output_tokens=128)


def _start_server(server: _RawHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _client_for_server(
    monkeypatch,
    server: _RawHTTPServer,
    *,
    read_timeout: float = 0.2,
) -> OXClient:
    host, port = server.server_address
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(
        client_module,
        "_GATEWAY_URL",
        f"http://{host}:{port}/v1/chat/completions",
    )
    monkeypatch.setattr(
        client_module,
        "_TIMEOUT",
        httpx.Timeout(connect=0.2, read=read_timeout, write=0.2, pool=0.2),
    )
    return OXClient(_settings())


def _shutdown(server: _RawHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=1)


NO_HEADERS = b""
HEADERS_NO_BODY = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: 5\r\n\r\n"
)
PARTIAL_FIXED_BODY = HEADERS_NO_BODY + b"abc"
PARTIAL_CHUNKED_BODY = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Transfer-Encoding: chunked\r\n\r\n"
    b"3\r\nabc\r\n"
    b"5\r\nde"
)


@pytest.mark.parametrize(
    ("response", "headers_received", "body_started", "byte_count"),
    [
        (NO_HEADERS, False, False, 0),
        (HEADERS_NO_BODY, True, False, 0),
        (PARTIAL_FIXED_BODY, True, True, 3),
        (PARTIAL_CHUNKED_BODY, True, True, 3),
    ],
)
def test_q03ja_remote_protocol_failure_reports_receive_progress(
    monkeypatch,
    response: bytes,
    headers_received: bool,
    body_started: bool,
    byte_count: int,
) -> None:
    server = _RawHTTPServer(response)
    thread = _start_server(server)
    client = _client_for_server(monkeypatch, server)
    try:
        with pytest.raises(OXTransportError) as raised:
            client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
    finally:
        _shutdown(server, thread)

    error = raised.value
    assert server.request_count == 1
    assert error.attempt_outcome == "OUTCOME_UNKNOWN"
    assert error.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
    observation = error.transport_observation
    assert observation.response_headers_received is headers_received
    assert observation.http_status_code == (200 if headers_received else None)
    assert observation.response_body_started is body_started
    assert observation.decoded_body_bytes_received == byte_count


def test_q03ja_headers_then_read_timeout_reports_zero_body_bytes(monkeypatch) -> None:
    server = _RawHTTPServer(HEADERS_NO_BODY, hold_open_seconds=0.2)
    thread = _start_server(server)
    client = _client_for_server(monkeypatch, server, read_timeout=0.05)
    try:
        with pytest.raises(OXTransportError) as raised:
            client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
    finally:
        _shutdown(server, thread)

    error = raised.value
    assert server.request_count == 1
    assert error.attempt_outcome == "OUTCOME_UNKNOWN"
    assert error.transport_failure_kind is OXTransportFailureKind.READ_TIMEOUT
    observation = error.transport_observation
    assert observation.response_headers_received is True
    assert observation.http_status_code == 200
    assert observation.response_body_started is False
    assert observation.decoded_body_bytes_received == 0


def _success_payload() -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-q03ja",
            "model": "zai/glm-5.3-flash",
            "choices": [
                {"message": {"role": "assistant", "content": "diagnostic success"}}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        },
        separators=(",", ":"),
    ).encode()


def _response_with_body(payload: bytes, status: int = 200) -> bytes:
    return (
        f"HTTP/1.1 {status} OK\r\n".encode()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(payload)}\r\n\r\n".encode()
        + payload
    )


def test_q03ja_complete_response_carries_completed_transport_observation(monkeypatch) -> None:
    payload = _success_payload()
    server = _RawHTTPServer(_response_with_body(payload))
    thread = _start_server(server)
    client = _client_for_server(monkeypatch, server)
    try:
        result = client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
    finally:
        _shutdown(server, thread)

    observation = result.transport_observation
    assert server.request_count == 1
    assert observation is not None
    assert observation.response_headers_received is True
    assert observation.http_status_code == 200
    assert observation.response_body_started is True
    assert observation.decoded_body_bytes_received == len(payload)
    assert observation.transport_failure_kind is None
    assert observation.response_headers_elapsed_ms is not None
    assert observation.first_body_elapsed_ms is not None
    assert observation.last_body_elapsed_ms is not None
    assert 0 <= observation.response_headers_elapsed_ms <= observation.first_body_elapsed_ms
    assert observation.first_body_elapsed_ms <= observation.last_body_elapsed_ms <= observation.elapsed_ms


def test_q03ja_complete_malformed_json_is_protocol_failure_with_complete_transport(monkeypatch) -> None:
    payload = b'{"broken":'
    server = _RawHTTPServer(_response_with_body(payload))
    thread = _start_server(server)
    client = _client_for_server(monkeypatch, server)
    try:
        with pytest.raises(OXProtocolError) as raised:
            client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
    finally:
        _shutdown(server, thread)

    error = raised.value
    assert server.request_count == 1
    assert error.attempt_outcome == "COMPLETED"
    observation = error.transport_observation
    assert observation.response_headers_received is True
    assert observation.response_body_started is True
    assert observation.decoded_body_bytes_received == len(payload)
    assert observation.transport_failure_kind is None


def test_q03ja_proxy_diagnostic_records_presence_only(monkeypatch) -> None:
    sentinel = "Q03JA-PROXY-SENTINEL"
    monkeypatch.setenv("HTTP_PROXY", f"http://{sentinel}.invalid")
    monkeypatch.setenv("HTTPS_PROXY", f"http://{sentinel}.invalid")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_success_payload())

    client = OXClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    observation = result.transport_observation
    assert observation is not None
    assert observation.proxy_environment_present is True
    assert sentinel not in repr(result)
    assert sentinel not in repr(observation)
