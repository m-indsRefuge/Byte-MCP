# Q03J-A OX Transport Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, durable HTTP receive-phase diagnostics to the existing non-streaming OX provider path without changing provider semantics, authority, retry behavior, or request count.

**Architecture:** Keep the Vercel AI Gateway request at `stream=false`, but consume the HTTP response incrementally with HTTPX so Byte-MCP can observe response-header arrival and decoded body progress. Snapshot those observations into one immutable `ProviderTransportObservation`, carry it on successful `ProviderResult` values and bounded provider errors, and append it through the existing `PROVIDER_TRANSPORT_METADATA` evidence event after the authoritative attempt outcome. Preserve legacy metadata readers and the existing public MCP projection.

**Tech Stack:** Python 3.12, HTTPX `>=0.28.1,<1`, asyncio, pytest, Ruff, append-only JSONL evidence, existing Q03H background provider lane and Q03I Vercel reporting tags.

**Spec:** `docs/superpowers/specs/2026-09-05-ox-transport-diagnostics-design.md`

## Global Constraints

- Qualified predecessor is `da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843` (Q03I).
- Implement in an isolated worktree/branch created from the committed Q03J-A design/plan branch, not from `main`.
- Provider endpoint remains `https://ai-gateway.vercel.sh/v1/chat/completions`.
- Model remains `zai/glm-5.3-flash`; provider allowlist remains Z.AI only.
- JSON request field remains exactly `"stream": false`.
- Reasoning effort and maximum-output-token configuration remain unchanged.
- Q03I `ai-reporting-tags` remain unchanged.
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
- No OX, Wolfram, Vercel AI Gateway, Z.AI, or other external provider request is authorized during implementation or qualification. All new HTTP tests must use `httpx.MockTransport` or loopback (`127.0.0.1`).
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
  - Switch local HTTP response consumption from buffered `client.post()` to one `client.stream(..., stream response locally)` context while keeping the JSON body `stream=false`.
  - Parse the accumulated complete body bytes through the existing status/JSON/provider-envelope semantics.
  - Attach the observation to success and complete-response errors; attach a partial observation to transport errors.
- Modify `src/byte_mcp/ox/evidence.py`
  - Extend existing `PROVIDER_TRANSPORT_METADATA` persistence and reconstruction with the new bounded fields.
  - Keep the existing legacy call shape readable/writable for internal compatibility.
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

Do not create a new production transport subsystem or new provider client. The Q03J-A change belongs at the current OX client/evidence boundary.

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

- [ ] **Step 1: Create the focused Q03J-A test file with a canonical observation fixture and frozen-value test**

Add `tests/ox/test_q03ja_transport_diagnostics.py` beginning with:

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


def test_q03ja_protocol_and_transport_errors_can_carry_only_bounded_observation() -> None:
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

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py -q
```

Expected: collection/import failure because `ProviderTransportObservation` and the new keyword carriers do not exist yet.

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

Append this field to `ProviderResult` so all existing positional construction remains valid:

```python
transport_observation: ProviderTransportObservation | None = None
```

- [ ] **Step 4: Extend provider-call errors without introducing a runtime import cycle**

At the top of `src/byte_mcp/errors.py`, enable postponed annotations and use a type-checking-only model import:

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

Extend `OXTransportError.__init__` with the same optional keyword and pass it to `super()` while preserving all existing legacy fields:

```python
transport_observation: ProviderTransportObservation | None = None,
```

and:

```python
super().__init__(
    attempt_outcome=attempt_outcome,
    transport_observation=transport_observation,
)
```

Do not store the originating HTTPX exception or its message.

- [ ] **Step 5: Update the existing bounded error-state assertion**

In `tests/ox/test_client.py`, add `"transport_observation"` to `_APPROVED_TRANSPORT_ERROR_FIELDS`, then change the exact equality check to require the old core fields and allow only the expanded approved set:

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

Keep `_assert_state_does_not_retain_transport_failure(...)` unchanged so the new observation is recursively checked for secret/exception retention.

- [ ] **Step 6: Run the task tests GREEN**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_client.py -q
```

Expected: PASS for the new contract tests and all existing client safety tests.

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
- Produces: `_post_with_total_deadline(...) -> tuple[int, bytes]` while mutating only the private tracker supplied by `OXClient.complete()`.
- Produces: every real `OXClient` success and every complete-response provider error carrying a completed observation; every transport failure carrying a partial observation.

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
        remaining = content_length - len(body)
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


def _run_server(server: _RawHTTPServer):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
```

The server must never bind outside `127.0.0.1`.

- [ ] **Step 2: Add RED tests for actual HTTP parser boundaries**

Add tests that monkeypatch `_GATEWAY_URL` to the loopback server and shorten only test-local timeouts. Use the following exact raw responses:

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

For each case call `OXClient.complete(...)` once and assert:

```python
error = raised.value
obs = error.transport_observation
assert server.request_count == 1
assert error.attempt_outcome == "OUTCOME_UNKNOWN"
assert error.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
```

Then assert the phase-specific observations:

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

Always `shutdown()`, `server_close()`, and join the server thread in `finally`.

- [ ] **Step 3: Add RED tests for headers-then-read-timeout, valid success, malformed JSON, and proxy privacy**

Use a server that sends `HEADERS_NO_BODY` and holds the socket open longer than a test-local `read=0.05`. Assert `READ_TIMEOUT`, headers present, zero body bytes, and exactly one request.

For success, serialize a minimal valid body:

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
```

Return it with an exact `Content-Length`. Assert:

```python
result = client.complete(...)
obs = result.transport_observation
assert server.request_count == 1
assert obs is not None
assert obs.response_headers_received is True
assert obs.http_status_code == 200
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received == len(payload)
assert obs.transport_failure_kind is None
assert 0 <= obs.response_headers_elapsed_ms <= obs.first_body_elapsed_ms
assert obs.first_body_elapsed_ms <= obs.last_body_elapsed_ms <= obs.elapsed_ms
```

For malformed JSON, return `b'{"broken":'` with the correct length and assert `OXProtocolError(attempt_outcome="COMPLETED")` carries a completed observation with the exact byte count and `transport_failure_kind is None`.

For proxy privacy, set a sentinel proxy value in `HTTP_PROXY`/`HTTPS_PROXY`, use `httpx.MockTransport` so no proxy is contacted, and assert only `proxy_environment_present is True`; the sentinel must not appear in `repr(result)`, `repr(observation)`, or any error `__dict__`.

- [ ] **Step 4: Run the new parser-boundary tests and confirm RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_diagnostics.py -q
```

Expected: failures because the current buffered `client.post()` cannot report the approved phase metadata and successful `ProviderResult` has no populated observation.

- [ ] **Step 5: Implement the private tracker in `client.py`**

Add fixed configuration and the private mutable tracker. Do not expose it outside the client module:

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

Do not add a response body, header mapping, URL, or exception to `_TransportTracker`.

- [ ] **Step 6: Replace buffered response consumption with one locally streamed HTTP response**

Change `_post_with_total_deadline` to accept `tracker` and return status plus complete decoded bytes:

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

The `client.stream(...)` call controls only HTTPX's local buffering. The JSON body built by `OXClient.complete()` must remain `"stream": False`.

- [ ] **Step 7: Snapshot observations on every terminal client path**

In `OXClient.complete()`:

1. Capture `provider_started_at` and `started_monotonic_ns` exactly once before `asyncio.run`.
2. Create `_TransportTracker(started_monotonic_ns)`.
3. Call `_post_with_total_deadline(..., tracker=tracker)` exactly once.
4. For each transport exception, map the existing outcome/kind and create `observation = tracker.snapshot(kind)`.
5. Construct `OXTransportError` with the existing legacy timing fields populated from the observation and with `transport_observation=observation`.
6. On complete HTTP transport, create `observation = tracker.snapshot(None)` once and use it for status/protocol/success paths.

The transport error construction must remain equivalent to:

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

- [ ] **Step 8: Parse the accumulated complete body without relying on a buffered `httpx.Response`**

Refactor the HTTP-error helper to consume `status_code`, `response_body`, and `observation`:

```python
@staticmethod
def _raise_http_error(
    status: int,
    response_body: bytes,
    observation: ProviderTransportObservation,
) -> None:
    ...
```

Change `_safe_error_code` to parse the complete bytes with `json.loads(response_body)` and return only the bounded error code. Every raised HTTP-status domain error receives `transport_observation=observation`.

For the 2xx path parse with:

```python
try:
    raw_response = json.loads(response_body)
except Exception:
    raise OXProtocolError(
        attempt_outcome="COMPLETED",
        transport_observation=observation,
    ) from None
```

Wrap any `_parse_response(...)` `OXProtocolError` into a new bounded `OXProtocolError` carrying the same attempt outcome plus the observation. Return:

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

Alternatively, pass the observation directly when constructing the final `ProviderResult`; do not mutate a frozen result.

- [ ] **Step 9: Extend the absolute-deadline regression with Q03J-A assertions**

In `tests/ox/test_provider_total_deadline.py`, import `OXTransportFailureKind` and add:

```python
error = exc_info.value
assert error.transport_failure_kind is OXTransportFailureKind.ABSOLUTE_DEADLINE
obs = error.transport_observation
assert obs.response_headers_received is True
assert obs.response_body_started is True
assert obs.decoded_body_bytes_received > 0
assert obs.elapsed_ms >= obs.last_body_elapsed_ms
```

Do not change the production 900-second default; the test continues monkeypatching a tiny local absolute deadline.

- [ ] **Step 10: Run Task 2 tests GREEN**

Run:

```bash
python -m pytest \
  tests/ox/test_q03ja_transport_diagnostics.py \
  tests/ox/test_client.py \
  tests/ox/test_client_timeout.py \
  tests/ox/test_provider_total_deadline.py \
  tests/ox/test_q03i_gateway_request_attribution.py \
  -q
```

Expected: PASS. Confirm the Q03I attribution test still sees exactly one request and the body still contains `"stream": false`.

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
- Produces: `EvidenceStore.record_provider_transport_metadata(..., observation=...)` and revalidation equivalent while retaining the legacy `provider_finished_at` / `elapsed_ms` / `transport_failure_kind` keyword path.
- Produces: reconstructed attempts containing the new fields only when a Q03J-A event actually recorded them.

- [ ] **Step 1: Write RED evidence tests for full Q03J-A metadata and legacy compatibility**

Create `tests/ox/test_q03ja_transport_evidence.py` with the same manifest/runtime constants and minimal preparation helpers used by `tests/ox/test_evidence.py`. Add a helper returning a valid observation.

Test a completed review attempt:

```python
store.record_provider_request_started(...)
store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.COMPLETED)
store.record_provider_transport_metadata(
    review_id,
    attempt_id,
    runtime_session_id=RUNTIME_SESSION_ID,
    observation=observation(),
)
attempt = store.get_review(review_id)["attempts"][-1]
assert attempt["response_headers_received"] is True
assert attempt["http_status_code"] == 200
assert attempt["response_body_started"] is True
assert attempt["decoded_body_bytes_received"] == 128
assert attempt["trust_env_enabled"] is True
assert attempt["proxy_environment_present"] is False
```

Add a legacy test that calls the existing three metadata keywords without `observation` and asserts every Q03J-A field is absent from the reconstructed attempt.

- [ ] **Step 2: Write RED validation tests for inconsistent or unsafe observations**

Use `dataclasses.replace(valid, ...)` and assert `OXEvidenceError` for at least these cases:

```python
replace(valid, response_headers_received=False, http_status_code=200)
replace(valid, response_body_started=False, decoded_body_bytes_received=1)
replace(valid, response_body_started=True, decoded_body_bytes_received=0)
replace(valid, first_body_elapsed_ms=500, response_headers_elapsed_ms=1000)
replace(valid, last_body_elapsed_ms=5000, elapsed_ms=4000)
replace(valid, trust_env_enabled=1)  # type: ignore[arg-type]
replace(valid, proxy_environment_present="yes")  # type: ignore[arg-type]
replace(valid, http_status_code=999)
```

Also append a hand-written event containing only one Q03J-A field to `events.jsonl` and assert reconstruction rejects it as malformed. This proves partial new-schema events do not silently become trusted evidence.

- [ ] **Step 3: Write RED revalidation-symmetry and duplicate tests**

Prepare a blind revalidation attempt, record provider start and terminal outcome, then call `record_revalidation_provider_transport_metadata(..., observation=valid)`. Assert the same fields reconstruct under the revalidation attempt.

Call the method a second time for the same attempt and assert the existing duplicate/already-recorded error remains.

- [ ] **Step 4: Run evidence tests and confirm RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py tests/ox/test_evidence.py -q
```

Expected: new tests fail because the evidence methods and reconstructor do not accept Q03J-A observations yet; legacy tests remain green.

- [ ] **Step 5: Add the observation import and exact Q03J-A event field set**

In `evidence.py` import `ProviderTransportObservation` and define:

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

`provider_finished_at`, `elapsed_ms`, and `transport_failure_kind` stay in the legacy portion of the event and are not duplicated in this set.

- [ ] **Step 6: Add strict observation validation and event serialization**

Implement a class/helper that returns a canonical mapping only after validating:

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
    ...
```

The completed implementation must enforce all of these relationships:

```text
headers false  -> header timestamp/elapsed/status are all null
headers true   -> header timestamp/elapsed/status are all valid
body false     -> first/last timestamps/elapsed are null and byte count == 0
body true      -> headers true, byte count > 0, first/last timestamps and elapsed are valid
100 <= status <= 599 when present
header_elapsed <= first_body_elapsed <= last_body_elapsed <= elapsed_ms
UTC header timestamp <= first body timestamp <= last body timestamp <= finished timestamp
transport_failure_kind is existing enum or null
all elapsed/byte counts are int, not bool, and >= 0
```

Return an explicit dict; never serialize `observation.__dict__` or arbitrary objects.

- [ ] **Step 7: Keep the evidence write API backward compatible internally**

Extend both metadata methods with optional `observation` while retaining their current named keywords. Use this shape:

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

If `observation is not None`, reject simultaneous legacy timing arguments, validate the observation, and build the event from it. If `observation is None`, require the existing legacy timestamp and elapsed value and emit exactly the historical event shape.

Apply the same rule to `record_revalidation_provider_transport_metadata` and continue including its required `phase` from the current attempt.

- [ ] **Step 8: Extend reconstruction without changing historical interpretation**

In `_apply_transport_metadata_event`:

1. Validate the existing legacy fields exactly as today.
2. Compute `present_q03ja_fields = _Q03JA_TRANSPORT_FIELDS.intersection(event)`.
3. If that set is non-empty, require it to equal `_Q03JA_TRANSPORT_FIELDS`.
4. Reconstruct a `ProviderTransportObservation` from the event plus the existing `provider_finished_at`, `elapsed_ms`, and `transport_failure_kind`, validate it with the same helper, then copy only the approved fields into the matching attempt.
5. If no Q03J-A field is present, leave the reconstructed attempt exactly legacy-shaped.

Do not fill absent fields with `False`, `0`, or `None` on historical attempts.

- [ ] **Step 9: Run Task 3 tests GREEN**

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

- [ ] **Step 1: Add an observed fake client and ordered evidence fixture**

In `tests/ox/test_q03ja_transport_evidence.py`, add an `ObservedNaturalClient` returning a valid natural `ProviderResult` with `transport_observation=observation()` and recording `client.complete` in a shared order list.

Add an `OrderedEvidenceStore(EvidenceStore)` that appends markers before delegating:

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

Use an ordered audit fixture that appends `"audit"` when the provider attempt is audited.

- [ ] **Step 2: Write RED success-ordering tests for natural initial and continuation**

For natural initial, use the existing preparation helpers and assert the provider segment ends exactly:

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

Then retrieve internal evidence with `store.get_review(review_id)` and assert the latest attempt contains the Q03J-A fields.

Establish a reviewed initial attempt, clear the order list, run one continuation, and assert the continuation attempt also records transport metadata after its terminal outcome and before audit.

- [ ] **Step 3: Write RED protocol/HTTP-error tests proving outcome-first metadata**

Create a fake client whose `complete()` raises:

```python
OXProtocolError(
    attempt_outcome="COMPLETED",
    transport_observation=observation(),
)
```

Run one provider path and assert:

```python
assert order.index("outcome:COMPLETED") < order.index("transport-metadata") < order.index("audit")
```

Repeat with one bounded HTTP-status domain error such as:

```python
OXProviderUnavailableError(
    attempt_outcome="REJECTED",
    transport_observation=observation(),
)
```

and assert the reconstructed attempt has the completed HTTP observation despite the rejected provider outcome.

- [ ] **Step 4: Write RED revalidation symmetry and public-projection tests**

Use the existing Q03H revalidation helpers to run one observed blind/targeted provider path. Assert internal revalidation evidence contains the Q03J-A metadata.

For a completed review, call:

```python
public_attempt = service.get_review(review_id, view="attempts")["attempts"][-1]
```

Assert these Q03J-A-only fields are absent:

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

This locks the approved non-expansion of the public MCP projection.

- [ ] **Step 5: Run service/evidence tests and confirm RED**

Run:

```bash
python -m pytest tests/ox/test_q03ja_transport_evidence.py -q
```

Expected: failures because current success paths do not persist transport metadata and generic protocol/HTTP errors do not trigger it.

- [ ] **Step 6: Add shared observation-recording helpers in `service.py`**

Import `ProviderTransportObservation` and add narrow helpers:

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

Keep these internal; do not add MCP arguments/results.

- [ ] **Step 7: Generalize provider-error finalization while preserving the legacy transport fallback**

In `_record_provider_error` and `_record_revalidation_provider_error`:

1. Record the authoritative outcome first exactly as today.
2. Read `observation = getattr(error, "transport_observation", None)`.
3. If it is a `ProviderTransportObservation`, call the new helper.
4. Otherwise retain the current `OXTransportError` legacy `kind/finished_at/elapsed_ms` persistence path unchanged.
5. Audit last.

This allows client-level protocol errors and HTTP-status errors to persist a completed HTTP observation without changing their outcome semantics.

- [ ] **Step 8: Persist successful observations after outcome and before audit across base service paths**

For every successful base-service terminalization in `service.py`, use:

```python
self._evidence.record_attempt_outcome(..., AttemptOutcome.COMPLETED)
self._record_review_transport_observation(
    descriptor.review_id,
    descriptor.attempt_id,
    result.transport_observation,
)
self._audit_attempt(...)
```

Apply the revalidation equivalent in `_run_claimed_revalidation_attempt`.

Cover both normal findings success and the existing invalid-findings branch that still terminalizes `COMPLETED`. Cover continuation success as well.

- [ ] **Step 9: Preserve observation on service-generated protocol errors**

Where `service.py` or `natural_service.py` creates a new `OXProtocolError` after receiving a `ProviderResult`, pass:

```python
transport_observation=(
    result.transport_observation if isinstance(result, ProviderResult) else None
)
```

This applies to invalid result shape / empty assistant-content checks. Do not change the existing attempt outcome chosen for those errors.

- [ ] **Step 10: Persist successful observations in natural initial/revalidation paths**

In `natural_service.py`, after the existing `COMPLETED` outcome and before the audit call, add the appropriate review/revalidation helper using `result.transport_observation`.

Do not change the existing raw-response-before-assistant/outcome ordering.

- [ ] **Step 11: Run Task 4 tests GREEN plus Q03H ownership regressions**

Run:

```bash
python -m pytest \
  tests/ox/test_q03ja_transport_evidence.py \
  tests/ox/test_background_job_manager.py \
  tests/ox/test_continue_provider_mcp_safety.py \
  tests/ox/test_revalidate_provider_mcp_safety.py \
  -q
```

Expected: PASS. No fake/provider test may dispatch more than its existing one call.

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

Use a sentinel value in all potentially dangerous inputs available to the test (`api_key`, proxy environment value, exception message, and malformed body). After an interrupted request, recursively inspect:

```python
error.__dict__
error.transport_observation
```

and after evidence persistence inspect the `PROVIDER_TRANSPORT_METADATA` JSONL record. Assert none contains the sentinel except that `proxy_environment_present` is the boolean `True`.

Do not weaken this test by string-replacing the sentinel before assertion.

- [ ] **Step 2: Add one-request assertions for every raw transport case**

Parameterize the loopback failure cases and assert `server.request_count == 1` for:

```text
pre-header EOF
headers then EOF
partial fixed-length body
partial chunked body
headers then read timeout
complete success
malformed complete JSON
```

There must be no test helper that implicitly calls `complete()` twice.

- [ ] **Step 3: Add explicit request-body and attribution regression assertions**

Either in the focused file or by invoking the existing Q03I test, assert the one captured request still has:

```python
assert body["stream"] is False
assert body["model"] == "zai/glm-5.3-flash"
assert body["providerOptions"] == {"gateway": {"only": ["zai"]}}
assert request.headers["ai-reporting-tags"] == (
    "component:byte-mcp-ox,review:OX-000001,attempt:OX-000001-A001"
)
```

No `ai-reporting-user` header may be introduced.

- [ ] **Step 4: Add a historical-event byte-preservation test**

Create a legacy review with a historical-format `PROVIDER_TRANSPORT_METADATA` event, capture `events.jsonl` bytes, call `get_review()`, then assert:

```python
assert events_path.read_bytes() == before
```

and that no Q03J-A fields have been synthesized into the attempt.

- [ ] **Step 5: Run the focused acceptance suite GREEN**

Run:

```bash
python -m pytest \
  tests/ox/test_q03ja_transport_diagnostics.py \
  tests/ox/test_q03ja_transport_evidence.py \
  tests/ox/test_client.py \
  tests/ox/test_client_timeout.py \
  tests/ox/test_provider_total_deadline.py \
  tests/ox/test_q03i_gateway_request_attribution.py \
  tests/ox/test_background_job_manager.py \
  tests/ox/test_continue_provider_mcp_safety.py \
  tests/ox/test_revalidate_provider_mcp_safety.py \
  tests/ox/test_evidence.py \
  -q
```

Expected: all selected tests PASS with no network access beyond test loopback.

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
- no unexpected production file outside the approved Q03J-A scope;
- no `jobs.py`, supervisor/launcher, provider settings, MCP schema, or retry-policy production change;
- `git diff --check` exits 0.

- [ ] **Step 2: Snapshot historical OX evidence read-only when the root exists**

On Windows PowerShell, use:

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

This is read-only. Do not run the Byte-MCP runtime, OX tools, or provider clients as part of qualification.

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

Expected: full repository PASS on the supported local environment. Do not exclude Q03J-A tests.

- [ ] **Step 5: Run Windows launcher qualification without changing launcher code**

On Windows PowerShell:

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: PASS under the project's installed supported Pester environment. The CI matrix will separately cover the normal launcher job and Pester 6 job.

- [ ] **Step 6: Verify historical evidence remained byte-identical**

If Step 2 created a snapshot:

```powershell
$root = Join-Path $env:LOCALAPPDATA 'Byte-MCP\ox'
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

- [ ] **Step 7: Verify no external-provider path was introduced into tests**

Inspect the new tests:

```bash
git grep -n "ai-gateway.vercel.sh\|api.z.ai\|wolfram" -- tests/ox/test_q03ja_transport_diagnostics.py tests/ox/test_q03ja_transport_evidence.py
```

Any occurrence of the Vercel URL must be an assertion against the request URL in an injected/loopback or `MockTransport` test, never a live request. There must be no executable external provider call.

- [ ] **Step 8: Review the final diff against every frozen invariant**

Run:

```bash
git diff da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843...HEAD -- \
  src/byte_mcp/ox/client.py \
  src/byte_mcp/ox/models.py \
  src/byte_mcp/errors.py \
  src/byte_mcp/ox/evidence.py \
  src/byte_mcp/ox/service.py \
  src/byte_mcp/ox/natural_service.py \
  tests/ox
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

- [ ] **Step 9: Push the implementation branch and wait for CI**

Push only after local qualification:

```bash
git push -u origin fix/ox-runtime-q03ja-transport-diagnostics
```

Expected CI:
- Ubuntu Python 3.12: install/pip check, compile, Ruff, full pytest PASS.
- Windows Python 3.12: install/pip check, compile, Ruff, full pytest PASS.
- Windows launcher: PASS.
- Windows launcher Pester 6: PASS.

Do not promote the runtime even if CI is green.

- [ ] **Step 10: Report the qualification checkpoint and STOP**

Report:

```text
Q03J-A OX TRANSPORT DIAGNOSTICS — LOCAL/CI QUALIFICATION
predecessor: da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843
candidate: <actual HEAD reported by git after implementation>
focused tests: <actual result>
full pytest: <actual result>
ruff: <actual result>
compile: <actual result>
pip check: <actual result>
launcher: <actual result>
historical evidence changed: no
OX provider requests: 0
Wolfram provider requests: 0
runtime promoted: no
main merged: no
```

The angle-bracket lines above are a **report format**, not values to put into code or tests; fill them only from actual executed command output at qualification time. STOP for Nolan's explicit authorization before runtime promotion or any live OX canary.

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
- All new live-like HTTP tests are loopback-only; no provider request is needed.
- Qualification ends before runtime promotion or live canary.
