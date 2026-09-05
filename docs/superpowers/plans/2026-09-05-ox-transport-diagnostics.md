# Q03J-A OX Transport Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, durable HTTP receive-phase diagnostics to the existing non-streaming OX provider path without changing provider semantics, authority, retry behavior, or request count.

**Architecture:** Keep the Vercel AI Gateway request at `stream=false`, but consume the HTTP response incrementally with HTTPX so Byte-MCP can observe response-header arrival and decoded body progress. Snapshot those observations into one immutable `ProviderTransportObservation`, carry it on successful `ProviderResult` values and bounded provider errors, and append it through the existing `PROVIDER_TRANSPORT_METADATA` evidence event after the authoritative attempt outcome. Preserve legacy evidence readers and the existing public MCP projection.

**Tech Stack:** Python 3.12, HTTPX `>=0.28.1,<1`, asyncio, pytest, Ruff, append-only JSONL evidence, existing Q03H background provider lane, Q03I Vercel reporting tags.

**Spec:** `docs/superpowers/specs/2026-09-05-ox-transport-diagnostics-design.md`

## Global Constraints

- Qualified predecessor is `da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843` (Q03I).
- Execute in an isolated worktree on branch `fix/ox-runtime-q03ja-transport-diagnostics`, created from the committed design/plan branch `design/ox-runtime-q03ja-transport-diagnostics`, not from `main`.
- Provider endpoint remains `https://ai-gateway.vercel.sh/v1/chat/completions`.
- Model remains `zai/glm-5.3-flash`; provider allowlist remains Z.AI only.
- JSON request field remains exactly `"stream": false`.
- Reasoning effort and maximum-output-token configuration remain unchanged.
- Q03I `ai-reporting-tags` remain unchanged and no `ai-reporting-user` header is introduced.
- Exactly one outbound POST is allowed per OX attempt; no reconnect, resume, fallback, automatic retry, or automatic A002.
- HTTPX connect/read/write/pool timeouts remain unchanged: 10 s / 900 s / 30 s / 10 s.
- The 900-second absolute receive deadline remains one wall-clock bound over send, header wait, and complete body receive and is never renewed by body activity.
- `RemoteProtocolError` remains `OUTCOME_UNKNOWN / REMOTE_PROTOCOL_ERROR`.
- Partial body content never authorizes `COMPLETED` and never authorizes retry.
- Q03H shared provider-lane ownership, runtime-session ownership, two-phase approval, and historical recovery semantics remain unchanged.
- Successful provider-response evidence must still precede successful terminalization.
- Historical OX evidence must not be migrated, normalized, or rewritten.
- Q03J-A persists metadata only; it does not persist partial response content.
- Do not widen the public `ox_get_review` projection with Q03J-A header/body/proxy fields.
- Do not modify `jobs.py`, supervisor/launcher behavior, provider selection/settings, MCP routing schemas, or retry/approval policy. If implementation proves one of those changes is necessary, STOP and return for design review.
- No OX, Wolfram, Vercel AI Gateway, Z.AI, or other external provider request is authorized during implementation or qualification. All new HTTP tests must use `httpx.MockTransport` or loopback `127.0.0.1`.
- No runtime promotion and no merge to `main` without separate authorization.

---

## File Structure

### Production files

- Modify `src/byte_mcp/ox/models.py`
  - Define immutable `ProviderTransportObservation`.
  - Add optional `transport_observation` to `ProviderResult` as the internal success carrier.
- Modify `src/byte_mcp/errors.py`
  - Allow bounded provider-call errors to carry an optional observation without retaining arbitrary exception state.
  - Preserve the existing legacy fields on `OXTransportError`.
- Modify `src/byte_mcp/ox/client.py`
  - Add a private mutable receive tracker that snapshots to `ProviderTransportObservation`.
  - Replace buffered `AsyncClient.post()` response consumption with one HTTPX response-stream context while the provider JSON body remains `stream=false`.
  - Parse the accumulated complete body bytes through the existing status, JSON, redaction, and provider-envelope semantics.
  - Attach the observation to success and complete-response errors; attach a partial observation to transport errors.
- Modify `src/byte_mcp/ox/evidence.py`
  - Extend existing `PROVIDER_TRANSPORT_METADATA` persistence and reconstruction with the new bounded fields.
  - Keep the existing legacy call shape readable and writable for internal compatibility.
  - Validate field types and cross-field consistency.
- Modify `src/byte_mcp/ox/service.py`
  - Record observations for base initial, continuation, revalidation, HTTP/protocol error, and transport-error paths.
  - Preserve outcome-first failure ordering and response-before-success ordering.
- Modify `src/byte_mcp/ox/natural_service.py`
  - Record successful natural initial/revalidation observations after terminal outcome and before audit.
  - Propagate a result observation into service-generated protocol errors.

### Test files

- Create `tests/ox/test_q03ja_transport_diagnostics.py`
  - Raw loopback HTTP parser-boundary tests, complete-response diagnostics, proxy-presence privacy, one-request semantics.
- Create `tests/ox/test_q03ja_transport_evidence.py`
  - Evidence validation/reconstruction, legacy compatibility, service ordering, revalidation symmetry, public-projection non-expansion.
- Modify `tests/ox/test_client.py`
  - Expand the approved bounded transport-error state to allow the observation while retaining legacy safety assertions.
- Modify `tests/ox/test_provider_total_deadline.py`
  - Assert Q03J-A observation fields on the existing continuous-trickle absolute-deadline test.

Do not create a new production transport subsystem or a second provider client.

---

### Task 1: Define the immutable observation contract and bounded error carriers

**Files:**
- Modify: `src/byte_mcp/ox/models.py:1-45`
- Modify: `src/byte_mcp/errors.py:107-175`
- Create: `tests/ox/test_q03ja_transport_diagnostics.py`
- Modify: `tests/ox/test_client.py:1-95`

**Interfaces:**
- Produces: `ProviderTransportObservation` with exactly the approved fields from the spec.
- Produces: `ProviderResult.transport_observation: ProviderTransportObservation | None`.
- Produces: provider errors accepting `transport_observation` as an optional keyword, with `OXTransportError` retaining `transport_failure_kind`, `provider_started_at`, `provider_finished_at`, and `elapsed_ms`.
- Consumes: existing `OXTransportFailureKind` enum from `byte_mcp.errors`.

- [ ] **Step 1: Write the RED contract tests**

Create `tests/ox/test_q03ja_transport_diagnostics.py` with this initial content:

```python
from dataclasses import FrozenInstanceError

import pytest

from byte_mcp.errors import OXProtocolError, OXTransportError, OXTransportFailureKind
from byte_mcp.ox.models import ProviderResult, ProviderTransportObservation


def observation(
    *,
    kind: OXTransportFailureKind | None = None,
) -> ProviderTransportObservation:
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at="2026-09-05T08:00:01+00:00",
        response_headers_elapsed_ms=1000,
        http_status_code=200,
        response_body_started=True,
        first_body_at="2026-09-05T08:00:02+00:00",
        first_body_elapsed_ms=2000,
        last_body_at="2026-09-05T08:00:03+00:00",
        last_body_elapsed_ms=3000,
        decoded_body_bytes_received=128,
        provider_finished_at="2026-09-05T08:00:04+00:00",
        elapsed_ms=4000,
        transport_failure_kind=kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def test_q03ja_observation_is_immutable_and_provider_result_can_carry_it() -> None:
    value = observation()
    result = ProviderResult("ok", transport_observation=value)

    assert result.transport_observation is value
    with pytest.raises(FrozenInstanceError):
        value.elapsed_ms = 5  # type: ignore[misc]


def test_q03ja_protocol_and_transport_errors_can_carry_bounded_observation() -> None:
    value = observation(kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR)
    protocol = OXProtocolError(
        attempt_outcome="COMPLETED",
        transport_observation=value,
    )
    transport = OXTransportError(
        attempt_outcome="OUTCOME_UNKNOWN",
        transport_failure_kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        provider_started_at="2026-09-05T08:00:00+00:00",
        provider_finished_at=value.provider_finished_at,
        elapsed_ms=value.elapsed_ms,
        transport_observation=value,
    )

    assert protocol.transport_observation is value
    assert transport.transport_observation is value
    assert transport.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
    assert transport.args == ()
```

- [ ] **Step 2: Run the contract tests to verify RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py -q
```

Expected: collection/import failure because `ProviderTransportObservation` and the new error keyword do not exist.

- [ ] **Step 3: Add `ProviderTransportObservation` and the optional result field**

In `src/byte_mcp/ox/models.py`, import `OXTransportFailureKind` and add this frozen dataclass before `ProviderResult`:

```python
@dataclass(frozen=True, slots=True)
class ProviderTransportObservation:
    response_headers_received: bool
    response_headers_at: str | None
    response_headers_elapsed_ms: int | None
    http_status_code: int | None
    response_body_started: bool
    first_body_at: str | None
    first_body_elapsed_ms: int | None
    last_body_at: str | None
    last_body_elapsed_ms: int | None
    decoded_body_bytes_received: int
    provider_finished_at: str
    elapsed_ms: int
    transport_failure_kind: OXTransportFailureKind | None
    trust_env_enabled: bool
    proxy_environment_present: bool
```

Append this field to `ProviderResult`:

```python
transport_observation: ProviderTransportObservation | None = None
```

Appending preserves every existing positional call because all existing fields keep their current order.

- [ ] **Step 4: Extend provider-call errors without a runtime import cycle**

At the top of `src/byte_mcp/errors.py`, enable postponed annotations and use a type-checking-only import:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from byte_mcp.ox.models import ProviderTransportObservation
```

Change `_ProviderCallError.__init__` to:

```python
def __init__(
    self,
    *,
    attempt_outcome: str = "OUTCOME_UNKNOWN",
    transport_observation: ProviderTransportObservation | None = None,
):
    if attempt_outcome not in self._APPROVED_OUTCOMES:
        raise ValueError("attempt_outcome must use an approved outcome")
    self.attempt_outcome = attempt_outcome
    if transport_observation is not None:
        self.transport_observation = transport_observation
    super().__init__()
```

Extend `OXTransportError.__init__` with:

```python
transport_observation: ProviderTransportObservation | None = None,
```

and replace its existing `super()` call with:

```python
super().__init__(
    attempt_outcome=attempt_outcome,
    transport_observation=transport_observation,
)
```

Do not retain the originating HTTPX exception or its message.

- [ ] **Step 5: Update the existing bounded error-state assertion**

In `tests/ox/test_client.py`, add `"transport_observation"` to `_APPROVED_TRANSPORT_ERROR_FIELDS` and replace the exact-key equality assertion with:

```python
assert {
    "attempt_outcome",
    "transport_failure_kind",
    "provider_started_at",
    "provider_finished_at",
    "elapsed_ms",
} <= set(error.__dict__)
assert set(error.__dict__) <= _APPROVED_TRANSPORT_ERROR_FIELDS
```

Keep `_assert_state_does_not_retain_transport_failure` unchanged so the observation is recursively checked for secrets and retained exception objects.

- [ ] **Step 6: Run Task 1 GREEN**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_client.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/byte_mcp/ox/models.py src/byte_mcp/errors.py tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_client.py
git commit -m "refactor: model OX transport observations"
```

---

### Task 2: Observe real non-streaming HTTP receive phases with one request

**Files:**
- Modify: `src/byte_mcp/ox/client.py:1-235`
- Modify: `tests/ox/test_q03ja_transport_diagnostics.py`
- Modify: `tests/ox/test_provider_total_deadline.py:1-135`

**Interfaces:**
- Consumes: `ProviderTransportObservation` from Task 1.
- Produces: `_TransportTracker.snapshot(kind) -> ProviderTransportObservation`.
- Produces: `_post_with_total_deadline` returning `tuple[int, bytes]` while mutating only the private tracker supplied by `OXClient.complete`.
- Produces: every real client success and every complete-response provider error carrying a completed observation; every transport failure carrying a partial observation.

- [ ] **Step 1: Add a disposable raw loopback HTTP server to the focused test file**

Add these imports and helpers to `tests/ox/test_q03ja_transport_diagnostics.py`:

```python
import json
import socketserver
import threading
import time
from types import SimpleNamespace

import httpx

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


def _client_for_server(monkeypatch, server: _RawHTTPServer, *, read_timeout: float = 0.2):
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
```

The server must never bind outside `127.0.0.1`.

- [ ] **Step 2: Add RED tests for actual HTTP parser boundaries**

Add these exact raw responses:

```python
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
```

Write one test per case. Every test starts the server, constructs the client with `_client_for_server`, invokes:

```python
client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
```

inside `pytest.raises(OXTransportError)`, and always shuts down/closes/joins the server in `finally`.

For all four cases assert:

```python
error = raised.value
obs = error.transport_observation
assert server.request_count == 1
assert error.attempt_outcome == "OUTCOME_UNKNOWN"
assert error.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
```

Then assert:

```python
# NO_HEADERS
assert obs.response_headers_received is False
assert obs.http_status_code is None
assert obs.response_body_started is False
assert obs.decoded_body_bytes_received == 0

# HEADERS_NO_BODY
assert obs.response_headers_received is True
assert obs.http_status_code == 200
assert obs.response_body_started is False
assert obs.decoded_body_bytes_received == 0

# PARTIAL_FIXED_BODY
assert obs.response_headers_received is True
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received == 3

# PARTIAL_CHUNKED_BODY
assert obs.response_headers_received is True
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received == 3
```

- [ ] **Step 3: Add RED tests for read timeout, valid success, malformed JSON, and proxy privacy**

For read timeout, send `HEADERS_NO_BODY`, set `hold_open_seconds=0.2`, use `read_timeout=0.05`, and assert:

```python
assert raised.value.transport_failure_kind is OXTransportFailureKind.READ_TIMEOUT
obs = raised.value.transport_observation
assert obs.response_headers_received is True
assert obs.http_status_code == 200
assert obs.response_body_started is False
assert obs.decoded_body_bytes_received == 0
assert server.request_count == 1
```

For success, serialize:

```python
payload = json.dumps(
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
response = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    + f"Content-Length: {len(payload)}\r\n\r\n".encode()
    + payload
)
```

Call:

```python
result = client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
```

and assert:

```python
obs = result.transport_observation
assert server.request_count == 1
assert obs is not None
assert obs.response_headers_received is True
assert obs.http_status_code == 200
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received == len(payload)
assert obs.transport_failure_kind is None
assert obs.response_headers_elapsed_ms is not None
assert obs.first_body_elapsed_ms is not None
assert obs.last_body_elapsed_ms is not None
assert 0 <= obs.response_headers_elapsed_ms <= obs.first_body_elapsed_ms
assert obs.first_body_elapsed_ms <= obs.last_body_elapsed_ms <= obs.elapsed_ms
```

For malformed JSON, use `payload = b'{"broken":'` with the correct `Content-Length`; assert `OXProtocolError` has `attempt_outcome == "COMPLETED"`, carries an observation with exact decoded byte count, and has `transport_failure_kind is None`.

For proxy privacy, set `HTTP_PROXY` and `HTTPS_PROXY` to `http://Q03JA-PROXY-SENTINEL.invalid`, use `httpx.MockTransport` returning the valid success body, and assert `result.transport_observation.proxy_environment_present is True` while `Q03JA-PROXY-SENTINEL` is absent from `repr(result)` and `repr(result.transport_observation)`.

- [ ] **Step 4: Run the parser-boundary tests to verify RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py -q
```

Expected: failures because the current buffered client cannot expose the approved receive-phase metadata.

- [ ] **Step 5: Implement the private tracker in `client.py`**

Add:

```python
import os
from dataclasses import dataclass

from .models import ProviderResult, ProviderTransportObservation, ProviderUsage

_TRUST_ENV = True
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _proxy_environment_present() -> bool:
    return any(bool(os.environ.get(name)) for name in _PROXY_ENV_KEYS)


@dataclass(slots=True)
class _TransportTracker:
    started_monotonic_ns: int
    response_headers_at: str | None = None
    response_headers_elapsed_ms: int | None = None
    http_status_code: int | None = None
    first_body_at: str | None = None
    first_body_elapsed_ms: int | None = None
    last_body_at: str | None = None
    last_body_elapsed_ms: int | None = None
    decoded_body_bytes_received: int = 0

    def _elapsed_ms(self) -> int:
        return max(0, (monotonic_ns() - self.started_monotonic_ns) // 1_000_000)

    def mark_headers(self, status_code: int) -> None:
        self.response_headers_at = datetime.now(UTC).isoformat()
        self.response_headers_elapsed_ms = self._elapsed_ms()
        self.http_status_code = status_code

    def mark_body(self, byte_count: int) -> None:
        now = datetime.now(UTC).isoformat()
        elapsed_ms = self._elapsed_ms()
        if self.decoded_body_bytes_received == 0:
            self.first_body_at = now
            self.first_body_elapsed_ms = elapsed_ms
        self.decoded_body_bytes_received += byte_count
        self.last_body_at = now
        self.last_body_elapsed_ms = elapsed_ms

    def snapshot(
        self,
        transport_failure_kind: OXTransportFailureKind | None,
    ) -> ProviderTransportObservation:
        return ProviderTransportObservation(
            response_headers_received=self.response_headers_at is not None,
            response_headers_at=self.response_headers_at,
            response_headers_elapsed_ms=self.response_headers_elapsed_ms,
            http_status_code=self.http_status_code,
            response_body_started=self.decoded_body_bytes_received > 0,
            first_body_at=self.first_body_at,
            first_body_elapsed_ms=self.first_body_elapsed_ms,
            last_body_at=self.last_body_at,
            last_body_elapsed_ms=self.last_body_elapsed_ms,
            decoded_body_bytes_received=self.decoded_body_bytes_received,
            provider_finished_at=datetime.now(UTC).isoformat(),
            elapsed_ms=self._elapsed_ms(),
            transport_failure_kind=transport_failure_kind,
            trust_env_enabled=_TRUST_ENV,
            proxy_environment_present=_proxy_environment_present(),
        )
```

Do not add a response body, header mapping, URL, exception, proxy value, or environment value to `_TransportTracker`.

- [ ] **Step 6: Replace buffered response consumption with one locally streamed HTTP response**

Replace `_post_with_total_deadline` with:

```python
async def _post_with_total_deadline(
    *,
    transport: httpx.AsyncBaseTransport | None,
    headers: Mapping[str, str],
    body: Mapping[str, object],
    tracker: _TransportTracker,
) -> tuple[int, bytes]:
    async with httpx.AsyncClient(
        transport=transport,
        timeout=_TIMEOUT,
        follow_redirects=False,
        trust_env=_TRUST_ENV,
    ) as client:
        async with asyncio.timeout(_TOTAL_DEADLINE_SECONDS):
            chunks = bytearray()
            async with client.stream(
                "POST",
                _GATEWAY_URL,
                headers=headers,
                json=body,
            ) as response:
                tracker.mark_headers(response.status_code)
                async for chunk in response.aiter_bytes():
                    if chunk:
                        tracker.mark_body(len(chunk))
                        chunks.extend(chunk)
                return response.status_code, bytes(chunks)
```

This changes only HTTPX local response buffering. The provider request body remains `"stream": False`.

- [ ] **Step 7: Snapshot observations on every terminal client path**

In `OXClient.complete`, retain the existing validation and request-body construction. Immediately before the provider call:

```python
provider_started_at = datetime.now(UTC).isoformat()
started_monotonic_ns = monotonic_ns()
tracker = _TransportTracker(started_monotonic_ns)
```

Invoke exactly one provider coroutine:

```python
status_code, response_body = asyncio.run(
    _post_with_total_deadline(
        transport=self._transport,
        headers=headers,
        body=body,
        tracker=tracker,
    )
)
```

For every current transport-exception mapping, keep the same outcome and `OXTransportFailureKind`. After mapping, build the error with:

```python
observation = tracker.snapshot(transport_failure_kind)
request_error = OXTransportError(
    attempt_outcome=transport_outcome,
    transport_failure_kind=transport_failure_kind,
    provider_started_at=provider_started_at,
    provider_finished_at=observation.provider_finished_at,
    elapsed_ms=observation.elapsed_ms,
    transport_observation=observation,
)
```

Do not retain the caught HTTPX exception.

After a complete HTTP receive, create exactly one success-side snapshot:

```python
observation = tracker.snapshot(None)
```

Use that same observation for HTTP-status errors, protocol errors, and the final `ProviderResult`.

- [ ] **Step 8: Parse the accumulated complete body and preserve existing status semantics**

Replace `_safe_error_code(response: httpx.Response)` with:

```python
def _safe_error_code(response_body: bytes) -> str | None:
    try:
        payload = json.loads(response_body)
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None
```

Replace `_raise_http_error` with:

```python
@staticmethod
def _raise_http_error(
    status: int,
    response_body: bytes,
    observation: ProviderTransportObservation,
) -> None:
    if status == 401:
        raise OXAuthenticationError(
            attempt_outcome="REJECTED",
            transport_observation=observation,
        )
    if status == 403:
        raise OXPermissionError(
            attempt_outcome="REJECTED",
            transport_observation=observation,
        )
    if status == 429:
        error_type = (
            OXQuotaError
            if _safe_error_code(response_body) in _QUOTA_ERROR_CODES
            else OXRateLimitError
        )
        raise error_type(
            attempt_outcome="REJECTED",
            transport_observation=observation,
        )
    if 400 <= status < 500:
        error_type = (
            OXContextLimitError
            if _safe_error_code(response_body) in _CONTEXT_ERROR_CODES
            else OXRequestError
        )
        raise error_type(
            attempt_outcome="REJECTED",
            transport_observation=observation,
        )
    if status >= 500:
        raise OXProviderUnavailableError(
            attempt_outcome="REJECTED",
            transport_observation=observation,
        )
    raise OXRequestError(
        attempt_outcome="REJECTED",
        transport_observation=observation,
    )
```

Call it only when `status_code >= 400`:

```python
self._raise_http_error(status_code, response_body, observation)
```

For a 2xx response, parse:

```python
try:
    raw_response = json.loads(response_body)
except Exception:
    raise OXProtocolError(
        attempt_outcome="COMPLETED",
        transport_observation=observation,
    ) from None
if not isinstance(raw_response, dict):
    raise OXProtocolError(
        attempt_outcome="COMPLETED",
        transport_observation=observation,
    )
```

Preserve secret redaction. Parse the redacted mapping with `_parse_response(safe_response)`. If `_parse_response` raises `OXProtocolError`, raise a new `OXProtocolError` with the same `attempt_outcome` and `transport_observation=observation`, suppressing cause/context. For any unexpected parsing exception, raise `OXProtocolError(attempt_outcome="COMPLETED", transport_observation=observation)` with no cause.

Return the final result as:

```python
return ProviderResult(
    result.content,
    result.usage,
    response_id=result.response_id,
    model=result.model,
    raw_response=result.raw_response,
    transport_observation=observation,
)
```

- [ ] **Step 9: Extend the absolute-deadline regression**

In `tests/ox/test_provider_total_deadline.py`, import `OXTransportFailureKind` and, after the existing `pytest.raises` block, add:

```python
error = exc_info.value
assert error.transport_failure_kind is OXTransportFailureKind.ABSOLUTE_DEADLINE
obs = error.transport_observation
assert obs.response_headers_received is True
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received > 0
assert obs.last_body_elapsed_ms is not None
assert obs.elapsed_ms >= obs.last_body_elapsed_ms
```

Do not change the production 900-second default.

- [ ] **Step 10: Run Task 2 GREEN**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_client.py tests/ox/test_client_timeout.py tests/ox/test_provider_total_deadline.py tests/ox/test_q03i_gateway_request_attribution.py -q
```

Expected: PASS. Confirm the existing Q03I attribution test still sees exactly one request and `body["stream"] is False`.

- [ ] **Step 11: Commit Task 2**

```bash
git add src/byte_mcp/ox/client.py tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_provider_total_deadline.py
git commit -m "feat: observe OX HTTP receive phases"
```

---

### Task 3: Persist and reconstruct bounded diagnostics without breaking legacy evidence

**Files:**
- Modify: `src/byte_mcp/ox/evidence.py:1-35, 560-690, 1300-1585, 1750-1975`
- Create: `tests/ox/test_q03ja_transport_evidence.py`
- Read/regression: `tests/ox/test_evidence.py:650-900`

**Interfaces:**
- Consumes: `ProviderTransportObservation` from Task 1.
- Produces: `EvidenceStore.record_provider_transport_metadata` and `EvidenceStore.record_revalidation_provider_transport_metadata` accepting an optional `observation` while retaining the legacy timing keyword path.
- Produces: reconstructed attempts containing the new fields only when a Q03J-A event actually recorded them.

- [ ] **Step 1: Write RED evidence tests for full Q03J-A metadata and legacy compatibility**

Create `tests/ox/test_q03ja_transport_evidence.py`. Import `replace`, `UTC`, `datetime`, `pytest`, `OXEvidenceError`, `OXTransportFailureKind`, `EvidenceStore`, `AttemptOutcome`, and `ProviderTransportObservation`. Define:

```python
MANIFEST_SHA256 = "a" * 64
RUNTIME_SESSION_ID = "a" * 32


def _prepare(store: EvidenceStore) -> str:
    return store.persist_prepared_review(
        identity={"repository": "fixture", "subsystem": "validation", "objective": "review"},
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )


def _observation() -> ProviderTransportObservation:
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at="2026-09-05T08:00:01+00:00",
        response_headers_elapsed_ms=1000,
        http_status_code=200,
        response_body_started=True,
        first_body_at="2026-09-05T08:00:02+00:00",
        first_body_elapsed_ms=2000,
        last_body_at="2026-09-05T08:00:03+00:00",
        last_body_elapsed_ms=3000,
        decoded_body_bytes_received=128,
        provider_finished_at="2026-09-05T08:00:04+00:00",
        elapsed_ms=4000,
        transport_failure_kind=None,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )
```

For the new-format review test, use:

```python
store = EvidenceStore(tmp_path)
review_id = _prepare(store)
attempt = store.claim_initial_transmission(
    review_id,
    MANIFEST_SHA256,
    runtime_session_id=RUNTIME_SESSION_ID,
)
store.record_provider_request_started(
    review_id,
    attempt["attempt_id"],
    runtime_session_id=RUNTIME_SESSION_ID,
    phase="initial",
)
store.record_attempt_outcome(review_id, attempt["attempt_id"], AttemptOutcome.COMPLETED)
store.record_provider_transport_metadata(
    review_id,
    attempt["attempt_id"],
    runtime_session_id=RUNTIME_SESSION_ID,
    observation=_observation(),
)
reconstructed = store.get_review(review_id)["attempts"][-1]
assert reconstructed["response_headers_received"] is True
assert reconstructed["http_status_code"] == 200
assert reconstructed["response_body_started"] is True
assert reconstructed["decoded_body_bytes_received"] == 128
assert reconstructed["trust_env_enabled"] is True
assert reconstructed["proxy_environment_present"] is False
```

Add a second test using the existing legacy call:

```python
store.record_provider_transport_metadata(
    review_id,
    attempt_id,
    runtime_session_id=RUNTIME_SESSION_ID,
    provider_finished_at=datetime.now(UTC).isoformat(),
    elapsed_ms=17,
    transport_failure_kind=OXTransportFailureKind.READ_ERROR,
)
```

and assert every Q03J-A-only field is absent from the reconstructed attempt.

- [ ] **Step 2: Write RED consistency-validation tests**

Use `replace(_observation(), field=value)` to create these exact invalid values and assert `OXEvidenceError` when persisting each:

```python
replace(_observation(), response_headers_received=False, http_status_code=200)
replace(_observation(), response_body_started=False, decoded_body_bytes_received=1)
replace(_observation(), response_body_started=True, decoded_body_bytes_received=0)
replace(_observation(), first_body_elapsed_ms=500, response_headers_elapsed_ms=1000)
replace(_observation(), last_body_elapsed_ms=5000, elapsed_ms=4000)
replace(_observation(), trust_env_enabled=1)  # type: ignore[arg-type]
replace(_observation(), proxy_environment_present="yes")  # type: ignore[arg-type]
replace(_observation(), http_status_code=999)
```

Also append a hand-written `PROVIDER_TRANSPORT_METADATA` JSONL record containing only `response_headers_received` from the Q03J-A field set and assert `get_review()` rejects it as malformed.

- [ ] **Step 3: Write RED revalidation-symmetry and duplicate tests**

Prepare a revalidation with the same helper pattern used by `tests/ox/test_evidence.py`: allocate the revalidation ID, persist the prepared revalidation, claim phase `blind`, record provider start, record `COMPLETED`, and call:

```python
store.record_revalidation_provider_transport_metadata(
    revalidation_id,
    attempt["attempt_id"],
    runtime_session_id=RUNTIME_SESSION_ID,
    observation=_observation(),
)
```

Assert the reconstructed revalidation attempt contains the same Q03J-A fields. Call the metadata method a second time and assert duplicate/already-recorded rejection.

- [ ] **Step 4: Run Task 3 tests to verify RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py tests/ox/test_evidence.py -q
```

Expected: the new tests fail because evidence persistence and reconstruction do not accept Q03J-A observations yet; legacy tests stay green.

- [ ] **Step 5: Add the observation import and exact event field set**

In `evidence.py`, import `ProviderTransportObservation` and define:

```python
_Q03JA_TRANSPORT_FIELDS = frozenset(
    {
        "response_headers_received",
        "response_headers_at",
        "response_headers_elapsed_ms",
        "http_status_code",
        "response_body_started",
        "first_body_at",
        "first_body_elapsed_ms",
        "last_body_at",
        "last_body_elapsed_ms",
        "decoded_body_bytes_received",
        "trust_env_enabled",
        "proxy_environment_present",
    }
)
```

`provider_finished_at`, `elapsed_ms`, and `transport_failure_kind` remain the legacy event fields.

- [ ] **Step 6: Add strict observation validation and serialization**

Implement this complete helper inside `EvidenceStore`:

```python
@classmethod
def _validated_transport_observation(
    cls,
    observation: ProviderTransportObservation,
) -> dict[str, object]:
    if not isinstance(observation, ProviderTransportObservation):
        raise OXEvidenceError("provider transport observation is invalid")
    if type(observation.response_headers_received) is not bool:
        raise OXEvidenceError("provider transport observation is invalid")
    if type(observation.response_body_started) is not bool:
        raise OXEvidenceError("provider transport observation is invalid")
    if type(observation.trust_env_enabled) is not bool:
        raise OXEvidenceError("provider transport observation is invalid")
    if type(observation.proxy_environment_present) is not bool:
        raise OXEvidenceError("provider transport observation is invalid")
    if not _is_elapsed_ms(observation.elapsed_ms):
        raise OXEvidenceError("provider transport observation is invalid")
    if not _is_elapsed_ms(observation.decoded_body_bytes_received):
        raise OXEvidenceError("provider transport observation is invalid")

    finished_at = cls._safe_provider_timestamp(observation.provider_finished_at)
    if finished_at is None:
        raise OXEvidenceError("provider transport observation is invalid")

    header_at = (
        cls._safe_provider_timestamp(observation.response_headers_at)
        if observation.response_headers_at is not None
        else None
    )
    status = observation.http_status_code
    status_valid = (
        isinstance(status, int)
        and not isinstance(status, bool)
        and 100 <= status <= 599
    )
    if observation.response_headers_received:
        if (
            header_at is None
            or not _is_elapsed_ms(observation.response_headers_elapsed_ms)
            or not status_valid
        ):
            raise OXEvidenceError("provider transport observation is invalid")
    elif (
        observation.response_headers_at is not None
        or observation.response_headers_elapsed_ms is not None
        or observation.http_status_code is not None
    ):
        raise OXEvidenceError("provider transport observation is invalid")

    first_at = (
        cls._safe_provider_timestamp(observation.first_body_at)
        if observation.first_body_at is not None
        else None
    )
    last_at = (
        cls._safe_provider_timestamp(observation.last_body_at)
        if observation.last_body_at is not None
        else None
    )
    if observation.response_body_started:
        if (
            not observation.response_headers_received
            or observation.decoded_body_bytes_received <= 0
            or first_at is None
            or last_at is None
            or not _is_elapsed_ms(observation.first_body_elapsed_ms)
            or not _is_elapsed_ms(observation.last_body_elapsed_ms)
        ):
            raise OXEvidenceError("provider transport observation is invalid")
    elif (
        observation.decoded_body_bytes_received != 0
        or observation.first_body_at is not None
        or observation.first_body_elapsed_ms is not None
        or observation.last_body_at is not None
        or observation.last_body_elapsed_ms is not None
    ):
        raise OXEvidenceError("provider transport observation is invalid")

    if observation.response_headers_received:
        assert observation.response_headers_elapsed_ms is not None
        if observation.response_headers_elapsed_ms > observation.elapsed_ms:
            raise OXEvidenceError("provider transport observation is invalid")
        assert header_at is not None
        if header_at > finished_at:
            raise OXEvidenceError("provider transport observation is invalid")

    if observation.response_body_started:
        assert observation.response_headers_elapsed_ms is not None
        assert observation.first_body_elapsed_ms is not None
        assert observation.last_body_elapsed_ms is not None
        if not (
            observation.response_headers_elapsed_ms
            <= observation.first_body_elapsed_ms
            <= observation.last_body_elapsed_ms
            <= observation.elapsed_ms
        ):
            raise OXEvidenceError("provider transport observation is invalid")
        assert header_at is not None and first_at is not None and last_at is not None
        if not header_at <= first_at <= last_at <= finished_at:
            raise OXEvidenceError("provider transport observation is invalid")

    failure_kind = cls._require_transport_failure_kind(
        observation.transport_failure_kind
    )
    return {
        "provider_finished_at": observation.provider_finished_at,
        "elapsed_ms": observation.elapsed_ms,
        "transport_failure_kind": failure_kind,
        "response_headers_received": observation.response_headers_received,
        "response_headers_at": observation.response_headers_at,
        "response_headers_elapsed_ms": observation.response_headers_elapsed_ms,
        "http_status_code": observation.http_status_code,
        "response_body_started": observation.response_body_started,
        "first_body_at": observation.first_body_at,
        "first_body_elapsed_ms": observation.first_body_elapsed_ms,
        "last_body_at": observation.last_body_at,
        "last_body_elapsed_ms": observation.last_body_elapsed_ms,
        "decoded_body_bytes_received": observation.decoded_body_bytes_received,
        "trust_env_enabled": observation.trust_env_enabled,
        "proxy_environment_present": observation.proxy_environment_present,
    }
```

Use the existing `_is_elapsed_ms` helper for the decoded byte count because it already means non-negative integer excluding bool; do not infer that the value is a time from the helper name.

- [ ] **Step 7: Keep the evidence write API backward compatible internally**

Change `record_provider_transport_metadata` to this signature:

```python
def record_provider_transport_metadata(
    self,
    review_id: str,
    attempt_id: str,
    *,
    runtime_session_id: str,
    provider_finished_at: str | None = None,
    elapsed_ms: int | None = None,
    transport_failure_kind: str | OXTransportFailureKind | None = None,
    observation: ProviderTransportObservation | None = None,
) -> None:
```

If `observation` is supplied, reject non-null `provider_finished_at`, `elapsed_ms`, or `transport_failure_kind`, call `_validated_transport_observation`, and build the event by adding `attempt_id`, `event_type`, and `runtime_session_id` to that returned mapping.

If `observation` is absent, require non-null `provider_finished_at` and `elapsed_ms`, keep the current timestamp/failure-kind validation, and emit exactly the existing legacy event shape.

Preserve the existing terminal-outcome requirement, current-attempt requirement, runtime-owner requirement, duplicate rejection, and finish-not-before-provider-start validation.

Apply the same signature and branch logic to `record_revalidation_provider_transport_metadata`; its event must continue to include the current attempt's `phase`.

- [ ] **Step 8: Extend reconstruction without changing historical interpretation**

In `_apply_transport_metadata_event`, keep current legacy validation first. Then add:

```python
present_q03ja_fields = _Q03JA_TRANSPORT_FIELDS.intersection(event)
if present_q03ja_fields and present_q03ja_fields != _Q03JA_TRANSPORT_FIELDS:
    raise OXEvidenceError("review events are malformed")
```

When every Q03J-A field is present, convert `transport_failure_kind` back to `OXTransportFailureKind` when it is a string, construct a `ProviderTransportObservation` from the event fields, and pass it to `_validated_transport_observation`. After validation, copy each name in `_Q03JA_TRANSPORT_FIELDS` from the event to the matching attempt.

When no Q03J-A field is present, do not add any new key to the matching attempt. Continue assigning the existing `provider_finished_at`, `elapsed_ms`, and `transport_failure_kind` exactly as today.

- [ ] **Step 9: Run Task 3 GREEN**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py tests/ox/test_evidence.py -q
```

Expected: PASS, including the existing Q03H legacy-evidence test.

- [ ] **Step 10: Commit Task 3**

```bash
git add src/byte_mcp/ox/evidence.py tests/ox/test_q03ja_transport_evidence.py
git commit -m "feat: persist bounded OX transport diagnostics"
```

---

### Task 4: Carry diagnostics through every service terminalization path

**Files:**
- Modify: `src/byte_mcp/ox/service.py:1025-1395`
- Modify: `src/byte_mcp/ox/natural_service.py:205-350`
- Modify: `tests/ox/test_q03ja_transport_evidence.py`
- Read/regression: `tests/ox/q03h_initial_support.py`
- Read/regression: `tests/ox/q03h_revalidation_support.py`

**Interfaces:**
- Consumes: `ProviderResult.transport_observation` and optional error `transport_observation`.
- Produces: review/revalidation transport metadata persisted only after authoritative terminal outcome.
- Produces: successful ordering `raw response -> existing assistant/result work -> COMPLETED outcome -> transport metadata -> audit`.
- Preserves: legacy `OXTransportError` fallback when a test/fake supplies only the old timing fields.

- [ ] **Step 1: Add observed fake client and ordered evidence fixtures**

In `tests/ox/test_q03ja_transport_evidence.py`, import the existing `make_natural_service`, `prepare`, and `wait_for_state` helpers from `tests.ox.q03h_initial_support`. Add a client that returns a valid `ProviderResult` with `_observation()` and records `client.complete` in an order list.

Add this evidence subclass:

```python
class OrderedEvidenceStore(EvidenceStore):
    def __init__(self, root, order):
        super().__init__(root)
        self.order = order

    def record_provider_request_started(self, *args, **kwargs):
        self.order.append("provider-start")
        return super().record_provider_request_started(*args, **kwargs)

    def persist_provider_response(self, *args, **kwargs):
        self.order.append("raw-response")
        return super().persist_provider_response(*args, **kwargs)

    def append_thread_message(self, review_id, thread_name, message):
        if message.get("role") == "assistant":
            self.order.append("assistant-thread")
        return super().append_thread_message(review_id, thread_name, message)

    def record_attempt_outcome(self, review_id, attempt_id, outcome):
        value = outcome.value if isinstance(outcome, AttemptOutcome) else outcome
        self.order.append(f"outcome:{value}")
        return super().record_attempt_outcome(review_id, attempt_id, outcome)

    def record_provider_transport_metadata(self, *args, **kwargs):
        self.order.append("transport-metadata")
        return super().record_provider_transport_metadata(*args, **kwargs)
```

Add an ordered audit fixture that appends `audit` before delegating to its in-memory event list.

- [ ] **Step 2: Write RED success-ordering tests for natural initial and continuation**

For natural initial, prepare/transmit the review and wait for `ReviewState.REVIEWED`. Restrict the order list to the provider-execution segment and assert:

```python
assert order == [
    "provider-start",
    "client.complete",
    "raw-response",
    "assistant-thread",
    "outcome:COMPLETED",
    "transport-metadata",
    "audit",
]
```

Retrieve internal evidence with `store.get_review(review_id)` and assert the latest attempt contains `response_headers_received`, `decoded_body_bytes_received`, `trust_env_enabled`, and `proxy_environment_present`.

Establish a reviewed initial attempt, clear the order list, call `service.continue_message(review_id, "Continue the bounded review.")`, wait for `REVIEWED`, and assert the continuation attempt records `transport-metadata` after `outcome:COMPLETED` and before `audit`.

- [ ] **Step 3: Write RED provider-error ordering tests**

Create one fake client that raises:

```python
OXProtocolError(
    attempt_outcome="COMPLETED",
    transport_observation=_observation(),
)
```

and another that raises:

```python
OXProviderUnavailableError(
    attempt_outcome="REJECTED",
    transport_observation=_observation(),
)
```

For each, run one initial provider path, wait for its existing terminal state, and assert the order list places the authoritative outcome before `transport-metadata` and `transport-metadata` before `audit`. Assert the reconstructed attempt keeps the existing outcome and also contains the Q03J-A observation fields.

- [ ] **Step 4: Write RED revalidation symmetry and public-projection tests**

Use the preparation/provenance helpers in `tests.ox.q03h_revalidation_support` to execute one observed blind revalidation. Assert the internal revalidation attempt contains the Q03J-A fields.

For a completed initial review, call:

```python
public_attempt = service.get_review(review_id, view="attempts")["attempts"][-1]
```

and assert every field below is absent:

```python
for field in (
    "response_headers_received",
    "response_headers_at",
    "response_headers_elapsed_ms",
    "http_status_code",
    "response_body_started",
    "first_body_at",
    "first_body_elapsed_ms",
    "last_body_at",
    "last_body_elapsed_ms",
    "decoded_body_bytes_received",
    "trust_env_enabled",
    "proxy_environment_present",
):
    assert field not in public_attempt
```

- [ ] **Step 5: Run Task 4 tests to verify RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py -q
```

Expected: failures because current success paths do not persist transport metadata and generic protocol/HTTP errors do not persist completed transport observations.

- [ ] **Step 6: Add shared observation-recording helpers in `service.py`**

Import `ProviderTransportObservation` and add:

```python
def _record_review_transport_observation(
    self,
    review_id: str,
    attempt_id: str,
    observation: ProviderTransportObservation | None,
) -> None:
    if observation is None:
        return
    self._evidence.record_provider_transport_metadata(
        review_id,
        attempt_id,
        runtime_session_id=self._jobs.runtime_session_id,
        observation=observation,
    )


def _record_revalidation_transport_observation(
    self,
    revalidation_id: str,
    attempt_id: str,
    observation: ProviderTransportObservation | None,
) -> None:
    if observation is None:
        return
    self._evidence.record_revalidation_provider_transport_metadata(
        revalidation_id,
        attempt_id,
        runtime_session_id=self._jobs.runtime_session_id,
        observation=observation,
    )
```

These helpers stay internal and do not change MCP schemas.

- [ ] **Step 7: Generalize provider-error finalization while preserving legacy fallback**

In `_record_provider_error`, keep this ordering:

```python
outcome = error.attempt_outcome
self._evidence.record_attempt_outcome(review_id, attempt_id, outcome)
observation = getattr(error, "transport_observation", None)
if isinstance(observation, ProviderTransportObservation):
    self._record_review_transport_observation(review_id, attempt_id, observation)
elif isinstance(error, OXTransportError):
    kind = error.transport_failure_kind
    finished_at = error.provider_finished_at
    elapsed_ms = error.elapsed_ms
    if kind is not None and finished_at is not None and elapsed_ms is not None:
        self._evidence.record_provider_transport_metadata(
            review_id,
            attempt_id,
            runtime_session_id=self._jobs.runtime_session_id,
            provider_finished_at=finished_at,
            elapsed_ms=elapsed_ms,
            transport_failure_kind=kind.value,
        )
```

Leave the existing `_audit_attempt` call immediately after this block.

Apply the same pattern in `_record_revalidation_provider_error`, using `record_revalidation_attempt_outcome`, `_record_revalidation_transport_observation`, and the existing legacy revalidation metadata call before the existing audit.

- [ ] **Step 8: Persist successful observations after outcome and before audit across base service paths**

In `_run_claimed_initial_attempt`, after each successful `record_attempt_outcome` call and before its existing audit call, add:

```python
self._record_review_transport_observation(
    descriptor.review_id,
    descriptor.attempt_id,
    result.transport_observation,
)
```

Do this in both the invalid-findings-completed branch and the normal findings-completed branch.

In `_run_claimed_continuation_attempt`, after the successful `record_attempt_outcome` and before audit, add the same review helper call.

In `_run_claimed_revalidation_attempt`, after each successful `record_revalidation_attempt_outcome` and before its audit, add:

```python
self._record_revalidation_transport_observation(
    revalidation_id,
    descriptor.attempt_id,
    result.transport_observation,
)
```

Do this in both the protocol-failure-completed branch and normal completed branch.

- [ ] **Step 9: Preserve observation on service-generated protocol errors**

Where `service.py` or `natural_service.py` creates `OXProtocolError` after receiving a `ProviderResult`, add this keyword:

```python
transport_observation=(
    result.transport_observation if isinstance(result, ProviderResult) else None
)
```

Do not change the existing `attempt_outcome` selected by that branch.

- [ ] **Step 10: Persist successful observations in natural initial and revalidation paths**

In `natural_service.py::_run_claimed_initial_attempt`, immediately after the successful `record_attempt_outcome(..., AttemptOutcome.COMPLETED)` statement and before the existing audit, add:

```python
self._record_review_transport_observation(
    descriptor.review_id,
    descriptor.attempt_id,
    result.transport_observation,
)
```

In `natural_service.py::_run_claimed_revalidation_attempt`, immediately after successful `record_revalidation_attempt_outcome(..., AttemptOutcome.COMPLETED)` and before the existing audit, add:

```python
self._record_revalidation_transport_observation(
    revalidation_id,
    descriptor.attempt_id,
    result.transport_observation,
)
```

Do not move the existing raw provider-response persistence or assistant-thread append.

- [ ] **Step 11: Run Task 4 GREEN plus Q03H ownership regressions**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py tests/ox/test_background_job_manager.py tests/ox/test_continue_provider_mcp_safety.py tests/ox/test_revalidate_provider_mcp_safety.py -q
```

Expected: PASS.

- [ ] **Step 12: Commit Task 4**

```bash
git add src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py tests/ox/test_q03ja_transport_evidence.py
git commit -m "feat: record OX transport observations through lifecycle"
```

---

### Task 5: Lock privacy, attribution, one-request, and backward-compatibility invariants

**Files:**
- Modify: `tests/ox/test_q03ja_transport_diagnostics.py`
- Modify: `tests/ox/test_q03ja_transport_evidence.py`
- Read/regression: `tests/ox/test_q03i_gateway_request_attribution.py`
- Read/regression: `tests/ox/test_provider_total_deadline.py`
- Read/regression: Q03H provider-lane/safety tests under `tests/ox/`

**Interfaces:**
- No new production API.
- Produces: frozen acceptance tests for the Q03J-A safety boundary.

- [ ] **Step 1: Add a diagnostic-schema privacy test**

Use the sentinel `Q03JA-SECRET-SENTINEL` as the configured API key, proxy environment value, transport exception message, and malformed body content in separate test cases. Recursively inspect `error.__dict__`, `error.transport_observation`, and the persisted `PROVIDER_TRANSPORT_METADATA` event. Assert the sentinel is absent. For proxy detection, assert only the boolean `proxy_environment_present is True` is retained.

Do not sanitize the sentinel inside the test before making the assertion.

- [ ] **Step 2: Lock one-request behavior for each raw transport case**

Parameterize the loopback cases and assert `server.request_count == 1` for all seven outcomes:

```text
pre-header EOF
headers then EOF
partial fixed-length body
partial chunked body
headers then read timeout
complete success
malformed complete JSON
```

Each parameterized case must invoke `OXClient.complete` exactly once.

- [ ] **Step 3: Lock request body and Q03I attribution**

Keep the existing `tests/ox/test_q03i_gateway_request_attribution.py` unchanged and add one focused assertion using `httpx.MockTransport` that captures the single request and checks:

```python
body = json.loads(request.content)
assert body["stream"] is False
assert body["model"] == "zai/glm-5.3-flash"
assert body["providerOptions"] == {"gateway": {"only": ["zai"]}}
assert request.headers["ai-reporting-tags"] == (
    "component:byte-mcp-ox,review:OX-000001,attempt:OX-000001-A001"
)
assert "ai-reporting-user" not in request.headers
```

- [ ] **Step 4: Add a historical-event byte-preservation test**

Create a review with a historical-format `PROVIDER_TRANSPORT_METADATA` event using only `provider_finished_at`, `elapsed_ms`, `transport_failure_kind`, and `runtime_session_id`. Capture `events.jsonl` bytes before `get_review()`, read the review, and assert:

```python
assert events_path.read_bytes() == before
```

Assert no Q03J-A-only field is synthesized into the reconstructed attempt.

- [ ] **Step 5: Run the focused acceptance suite GREEN**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_q03ja_transport_evidence.py tests/ox/test_client.py tests/ox/test_client_timeout.py tests/ox/test_provider_total_deadline.py tests/ox/test_q03i_gateway_request_attribution.py tests/ox/test_background_job_manager.py tests/ox/test_continue_provider_mcp_safety.py tests/ox/test_revalidate_provider_mcp_safety.py tests/ox/test_evidence.py -q
```

Expected: PASS with no network access beyond loopback.

- [ ] **Step 6: Commit Task 5**

```bash
git add tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_q03ja_transport_evidence.py
git commit -m "test: lock Q03J-A transport safety invariants"
```

---

### Task 6: Full qualification, scope audit, and zero-provider closure

**Files:**
- No production changes expected.
- Inspect: all Q03J-A changed files and existing CI/launcher scripts.

**Interfaces:**
- Produces: qualified Q03J-A implementation candidate only; no runtime promotion.

- [ ] **Step 1: Verify branch ancestry and changed-file scope**

Run:

```bash
git status --short
git merge-base HEAD da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843
git diff --name-status da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843...HEAD
git diff --check da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843...HEAD
```

Expected:
- merge base is exactly `da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843`;
- only approved Q03J-A production/test/docs files changed;
- no `jobs.py`, supervisor/launcher, provider settings, MCP schema, or retry-policy production change;
- `git diff --check` exits 0.

- [ ] **Step 2: Snapshot historical OX evidence read-only when the root exists**

On Windows PowerShell:

```powershell
$root = Join-Path $env:LOCALAPPDATA 'Byte-MCP\ox'
$before = Join-Path $env:TEMP 'q03ja-ox-evidence-before.json'
if (Test-Path $root) {
  Get-ChildItem $root -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
      [pscustomobject]@{
        Path = $_.FullName
        Length = $_.Length
        SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
      }
    } | ConvertTo-Json -Depth 3 | Set-Content $before -Encoding utf8
}
```

This step is read-only.

- [ ] **Step 3: Run dependency, compile, and lint gates exactly as CI does**

Run:

```bash
python -m pip check
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m ruff check .
```

Expected: all commands exit 0.

- [ ] **Step 4: Run the full test suite**

Run:

```bash
python -m pytest
```

Expected: full repository PASS on the supported local environment.

- [ ] **Step 5: Run Windows launcher qualification without changing launcher code**

On Windows PowerShell:

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: PASS. CI will separately cover its normal Windows launcher job and Pester 6 job.

- [ ] **Step 6: Verify historical evidence remained byte-identical**

If Step 2 created the before snapshot, create the after snapshot and compare:

```powershell
$root = Join-Path $env:LOCALAPPDATA 'Byte-MCP\ox'
$before = Join-Path $env:TEMP 'q03ja-ox-evidence-before.json'
$after = Join-Path $env:TEMP 'q03ja-ox-evidence-after.json'
Get-ChildItem $root -File -Recurse |
  Sort-Object FullName |
  ForEach-Object {
    [pscustomobject]@{
      Path = $_.FullName
      Length = $_.Length
      SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
  } | ConvertTo-Json -Depth 3 | Set-Content $after -Encoding utf8
if ((Get-Content $before -Raw) -ne (Get-Content $after -Raw)) {
  throw 'Historical OX evidence changed during Q03J-A qualification.'
}
```

Expected: no difference.

- [ ] **Step 7: Verify no external-provider execution path exists in the new tests**

Run:

```bash
git grep -n "ai-gateway.vercel.sh\|api.z.ai\|wolfram" -- tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_q03ja_transport_evidence.py
```

Any Vercel URL occurrence must be an assertion against a request captured by `MockTransport` or a monkeypatched local URL context. There must be no executable external provider call.

- [ ] **Step 8: Review the final diff against every frozen invariant**

Run:

```bash
git diff da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843...HEAD -- src/byte_mcp/ox/client.py src/byte_mcp/ox/models.py src/byte_mcp/errors.py src/byte_mcp/ox/evidence.py src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py tests/ox
```

Manually confirm:
- request JSON still sets `stream` to `False`;
- no retry/reconnect/fallback code exists;
- Q03I tag formatting is unchanged;
- the 900-second outer deadline remains;
- only bounded diagnostic fields are persisted;
- partial body bytes are counted but never persisted as content;
- all ambiguity remains `OUTCOME_UNKNOWN`;
- successful response artifact still precedes terminal success;
- public `ox_get_review` projection did not gain Q03J-A-only fields.

- [ ] **Step 9: Record the actual candidate SHA and push only after local qualification**

Run:

```bash
git rev-parse HEAD
git push -u origin fix/ox-runtime-q03ja-transport-diagnostics
```

Record the exact SHA printed by `git rev-parse HEAD`. Expected CI:
- Ubuntu Python 3.12 install/pip check, compile, Ruff, full pytest PASS;
- Windows Python 3.12 install/pip check, compile, Ruff, full pytest PASS;
- Windows launcher PASS;
- Windows launcher on Pester 6 PASS.

Do not promote the runtime even if CI is green.

- [ ] **Step 10: Report qualification and STOP**

Report the exact predecessor SHA, the exact candidate SHA from Step 9, actual focused-test result, actual full-pytest result, actual Ruff/compile/pip-check/launcher results, historical-evidence comparison result, and counts of external provider requests. The required fixed facts are:

```text
predecessor = da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843
historical evidence changed = no
OX provider requests = 0
Wolfram provider requests = 0
runtime promoted = no
main merged = no
```

Do not invent pass counts or candidate identity. STOP for Nolan's explicit authorization before runtime promotion or any live OX canary.

---

## Plan Self-Review Checklist

Before execution begins, verify this plan against the approved spec:

- Every Q03J-A observation field is created, observed, persisted, validated, reconstructed, and privacy-tested.
- Complete HTTP transport is distinguishable from transport interruption and from payload/protocol invalidity.
- Legacy events remain readable without synthetic new fields.
- Review and revalidation metadata paths are symmetrical.
- Natural initial, base continuation, and revalidation success paths persist metadata only after outcome and before audit.
- Provider errors record outcome first, then metadata, then audit.
- `stream=false`, one POST, Q03I tags, timeouts, and Q03H ownership remain frozen.
- No public MCP projection widening occurs.
- No supervisor, launcher, `jobs.py`, settings, routing, or retry-policy production change is planned.
- All new live-like HTTP tests are loopback-only or `MockTransport`; no provider request is needed.
- Qualification ends before runtime promotion or live canary.
