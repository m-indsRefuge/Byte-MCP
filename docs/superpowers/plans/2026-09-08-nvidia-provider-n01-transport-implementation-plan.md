# NVIDIA-01 Exactly-Once Hosted Chat Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the provider-neutral prepared-request and exactly-once async HTTP transport contracts, then add a bounded NVIDIA hosted `/v1/chat/completions` adapter, entirely offline and without modifying OX/Wolfram behavior.

**Architecture:** Extend the NVIDIA-00 provider-neutral package with deterministic request preparation and an async one-shot transport that sends the exact hashed bytes, records bounded receive metadata, and maps ambiguous failures conservatively. Add an NVIDIA chat adapter above that transport for text-only non-streaming request construction, safe status classification, bounded response parsing, and hosted settings; keep durable authorization/evidence and live execution for NVIDIA-02.

**Tech Stack:** Python 3.12+, stdlib dataclasses/enums/hashlib/json/datetime/asyncio, existing `httpx>=0.28.1,<1`, pytest, Ruff. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-nvidia-provider-n01-transport-design.md`

## Global Constraints

- Work on `feat/nvidia-provider-n01-transport`; qualified predecessor is `48c076512f233127ab119c522d9f4cd620587078`.
- NVIDIA-01 performs zero live NVIDIA requests, including zero `/v1/models` and zero `/v1/chat/completions` calls.
- Tests use only `httpx.MockTransport`, custom injected `httpx.AsyncBaseTransport`, static fixtures, and deterministic local timing controls.
- Exactly one provider HTTP request maximum per `execute_once` call; zero automatic retry, reconnect, replay, alternate URL, model fallback, or provider fallback.
- `follow_redirects=False` and `trust_env=True` for production transport.
- `NVIDIA_API_KEY` is the only hosted NVIDIA credential; `NGC_API_KEY` is never a hosted fallback.
- Production NVIDIA origin is fixed to `https://integrate.api.nvidia.com`; endpoint path is fixed to `/v1/chat/completions`.
- Prepared request canonical JSON uses `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, encoded UTF-8.
- Canonical request body maximum is exactly `4_000_000` bytes.
- Buffered decoded response body maximum is exactly `8_000_000` bytes.
- Any response-size abort before complete response consumption is `OUTCOME_UNKNOWN`.
- Connect timeout/error and pool timeout map to `NOT_SENT`; write/read/protocol/general HTTP transport failures and absolute deadline map to `OUTCOME_UNKNOWN`.
- A fully received 2xx HTTP response maps to transport outcome `COMPLETED`; a fully received 3xx/4xx/5xx maps to `REJECTED`.
- A malformed 2xx response remains transport `COMPLETED` with NVIDIA protocol/result failure at the adapter layer.
- `ProviderTransmissionContext` must bind `expected_request_sha256` to `PreparedProviderRequest.request_sha256` before any transmission.
- Provider-neutral transport accepts only a bounded header mapping whose keys are exactly `Authorization`, `Content-Type`, and `Accept`; arbitrary extra headers are rejected locally before transport.
- The API key, authorization header, request body, response body, arbitrary headers, raw provider prose, and raw `httpx` exception strings never enter ordinary returned metadata, durable evidence, or exception messages.
- NVIDIA-01 supports text messages only with roles `system`, `user`, `assistant`; no tool messages, tools, multimodal content, streaming, response format, reasoning dialect fields, or provider routing hints.
- Request bounds: `0 <= temperature <= 2`, `0 < top_p <= 1`, `1 <= max_tokens <= 65536`, `n == 1`, `stream == false`; booleans are rejected as numeric values.
- Provider-neutral code must not import `byte_mcp.ox`, `byte_mcp.nvidia`, or provider-specific exceptions.
- Frozen paths: `src/byte_mcp/ox/**`, `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, `pyproject.toml`.
- Expected unchanged NVIDIA-00 paths: `src/byte_mcp/nvidia/catalog.py`, `src/byte_mcp/nvidia/registry.py`; if a compatibility edit becomes necessary, STOP before mutation and surface the reason.
- Historical OX evidence is immutable.
- NVIDIA-01 does not expose or register an MCP inference tool.
- NVIDIA-01 does not implement durable attempts, durable provider-start evidence, authorization state, provider lanes, runtime promotion, or live canary execution.
- Baseline-aware format gate: every Python file added or modified by NVIDIA-01 must pass `ruff format --check`; repository-wide historical format failures are acceptable only when proven unchanged from `48c076512f233127ab119c522d9f4cd620587078` and outside the NVIDIA-01 changed-file set.
- Final qualification requires full pytest, whole-repository Ruff lint, changed-scope Ruff format, frozen-path verification, and fresh GitHub Actions CI on the final pushed commit before claiming NVIDIA-01 qualified.

---

## Planned File Structure

Create:

```text
src/byte_mcp/providers/requests.py
src/byte_mcp/providers/transport.py
src/byte_mcp/nvidia/chat.py

tests/providers/test_requests.py
tests/providers/test_transport.py
tests/nvidia/test_chat_request.py
tests/nvidia/test_chat_response.py
tests/nvidia/test_chat_execution.py
tests/nvidia/test_n01_security_invariants.py
```

Modify only:

```text
src/byte_mcp/providers/__init__.py
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/errors.py
src/byte_mcp/nvidia/settings.py
```

Do not modify any other production file in NVIDIA-01.

---

### Task 1: Canonical Prepared Provider Requests

**Files:**
- Create: `src/byte_mcp/providers/requests.py`
- Create: `tests/providers/test_requests.py`
- Modify: `src/byte_mcp/providers/__init__.py`

**Interfaces:**
- Consumes: `validate_model_id(model_id: object) -> str` from `byte_mcp.providers.models`.
- Produces: `PreparedProviderRequest`, `prepare_provider_request(...)`, `MAX_PREPARED_BODY_BYTES`.

Required public signature:

```python
def prepare_provider_request(
    *,
    provider_id: str,
    method: str,
    target_origin: str,
    endpoint_path: str,
    model_id: str,
    body: object,
) -> PreparedProviderRequest: ...
```

Required dataclass fields:

```python
@dataclass(frozen=True, slots=True, repr=False)
class PreparedProviderRequest:
    provider_id: str
    method: str
    target_origin: str
    endpoint_path: str
    model_id: str
    body_bytes: bytes
    payload_sha256: str
    request_sha256: str
```

- [ ] **Step 1: Write failing canonicalization and identity tests**

Create `tests/providers/test_requests.py` with focused tests equivalent to:

```python
import hashlib
import json

import pytest

from byte_mcp.providers.requests import (
    MAX_PREPARED_BODY_BYTES,
    prepare_provider_request,
)


def make_request(body):
    return prepare_provider_request(
        provider_id="nvidia-api-catalog",
        method="POST",
        target_origin="https://integrate.api.nvidia.com",
        endpoint_path="/v1/chat/completions",
        model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
        body=body,
    )


def test_preparation_canonicalizes_exact_wire_bytes_and_hashes_them():
    request = make_request({"z": 1, "a": "é"})
    expected = json.dumps(
        {"z": 1, "a": "é"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert request.body_bytes == expected
    assert request.payload_sha256 == hashlib.sha256(expected).hexdigest()


def test_request_hash_changes_when_destination_or_body_changes():
    first = make_request({"value": 1})
    second = make_request({"value": 2})
    assert first.request_sha256 != second.request_sha256


def test_repr_omits_body_content():
    request = make_request({"messages": [{"content": "TOP SECRET"}]})
    text = repr(request)
    assert "TOP SECRET" not in text
    assert request.request_sha256 in text


def test_invalid_json_numbers_fail_before_request_creation():
    with pytest.raises(ValueError):
        make_request({"temperature": float("nan")})


def test_body_bound_is_enforced_before_transport():
    with pytest.raises(ValueError, match="prepared request body exceeds limit"):
        make_request({"content": "x" * MAX_PREPARED_BODY_BYTES})
```

Also test exact rejection of:
- method other than `POST`;
- target origin other than `https://integrate.api.nvidia.com` for the NVIDIA-shaped fixture;
- endpoint path lacking a leading `/` or containing query/fragment/whitespace;
- invalid provider slug;
- invalid model ID;
- non-JSON-serializable values;
- booleans or strange object types only insofar as JSON serialization rules reject them.

- [ ] **Step 2: Run focused tests and prove RED**

Run:

```powershell
python -m pytest tests/providers/test_requests.py -q
```

Expected: collection fails because `byte_mcp.providers.requests` does not exist.

- [ ] **Step 3: Implement canonical preparation**

Implement `src/byte_mcp/providers/requests.py` with these exact invariants:

```python
MAX_PREPARED_BODY_BYTES = 4_000_000
REQUEST_SCHEMA = "byte-mcp-provider-request-v1"
```

Canonical helper:

```python
def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("request body is not valid canonical JSON") from None
    return text.encode("utf-8")
```

Hash metadata using the exact canonical envelope from the spec:

```python
metadata = {
    "endpoint_path": endpoint_path,
    "method": method,
    "model_id": model_id,
    "payload_sha256": payload_sha256,
    "provider_id": provider_id,
    "request_schema": REQUEST_SCHEMA,
    "target_origin": target_origin,
}
```

Validate `provider_id` with the same lowercase slug shape already used by provider identities, validate `model_id` with `validate_model_id`, require uppercase `POST`, require absolute HTTPS origin without path/query/fragment, and require a clean absolute endpoint path beginning `/` with no `?`, `#`, CR, LF, or spaces.

Implement a custom safe `__repr__` that exposes bounded metadata/hashes only.

- [ ] **Step 4: Export the new provider-neutral request API**

Update `src/byte_mcp/providers/__init__.py` to export:

```python
MAX_PREPARED_BODY_BYTES
PreparedProviderRequest
prepare_provider_request
```

Do not change existing exports.

- [ ] **Step 5: Run focused tests and Ruff**

```powershell
python -m pytest tests/providers/test_requests.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

Expected: PASS.

- [ ] **Step 6: Inspect diff and commit Task 1**

```powershell
git diff --check
git status --short
git add src/byte_mcp/providers/requests.py src/byte_mcp/providers/__init__.py tests/providers/test_requests.py
git commit -m "feat: add canonical provider request identity"
```

---

### Task 2: Transmission Context, Timeout Policy, Observation, and Transport Error Contracts

**Files:**
- Create: `src/byte_mcp/providers/transport.py`
- Create: `tests/providers/test_transport.py`
- Modify: `src/byte_mcp/providers/__init__.py`

**Interfaces:**
- Consumes: `PreparedProviderRequest`, `ProviderAttemptOutcome`, `ProviderTransportFailureKind`.
- Produces: `ProviderTransmissionContext`, `ProviderTimeoutPolicy`, `ProviderTransportObservation`, `ProviderTransportResponse`, `ProviderTransportError`, `execute_once(...)` scaffold completed in Task 3.

Required dataclasses:

```python
@dataclass(frozen=True, slots=True)
class ProviderTransmissionContext:
    provider_started_at: str
    expected_request_sha256: str

@dataclass(frozen=True, slots=True)
class ProviderTimeoutPolicy:
    connect_seconds: float
    write_seconds: float
    read_seconds: float
    pool_seconds: float
    absolute_deadline_seconds: float

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
    provider_started_at: str
    provider_finished_at: str
    elapsed_ms: int
    transport_failure_kind: ProviderTransportFailureKind | None
    trust_env_enabled: bool
    proxy_environment_present: bool

@dataclass(frozen=True, slots=True, repr=False)
class ProviderTransportResponse:
    outcome: ProviderAttemptOutcome
    status_code: int
    body: bytes
    observation: ProviderTransportObservation
```

Required safe error:

```python
class ProviderTransportError(ByteMCPError):
    attempt_outcome: ProviderAttemptOutcome
    transport_failure_kind: ProviderTransportFailureKind
    transport_observation: ProviderTransportObservation
```

- [ ] **Step 1: Add failing validation/security tests for transport contracts**

Extend `tests/providers/test_transport.py` with tests that prove:

```python
ProviderTransmissionContext(
    provider_started_at="2026-09-08T20:00:00+00:00",
    expected_request_sha256="a" * 64,
)
```

is valid, while naive timestamps, malformed hashes, non-finite/zero/negative timeout values, and timeout values above `600` fail closed.

Test that `repr(ProviderTransportResponse(...body=b"SECRET"...))` never includes `SECRET`.

Test that `ProviderTransportError` stringification contains enum values but never an injected raw exception message.

- [ ] **Step 2: Run focused tests and prove RED**

```powershell
python -m pytest tests/providers/test_transport.py -q
```

Expected: collection or attribute failures for missing transport contracts.

- [ ] **Step 3: Implement immutable transport contracts and internal receive tracker**

Implement:

```python
MAX_RESPONSE_BODY_BYTES = 8_000_000
MAX_TIMEOUT_SECONDS = 600.0
_ALLOWED_HEADER_NAMES = frozenset({"authorization", "content-type", "accept"})
```

`ProviderTimeoutPolicy.__post_init__` must reject booleans, non-numeric values, non-finite values, values `<= 0`, and values `> 600`.

`ProviderTransmissionContext.__post_init__` must require timezone-aware ISO-8601 and lowercase 64-character hex request SHA-256.

Implement an internal mutable `_TransportTracker` patterned on the already-proven OX receive observation, but importing only provider-neutral types.

Recognized proxy environment keys:

```python
(
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)
```

Only record whether any are present; never retain values.

- [ ] **Step 4: Export contract types**

Update `src/byte_mcp/providers/__init__.py` with the new public contract types but do not export internal tracker/helpers.

- [ ] **Step 5: Run focused tests and Ruff**

```powershell
python -m pytest tests/providers/test_transport.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

Expected: PASS for contract-only tests; request execution tests remain absent until Task 3.

- [ ] **Step 6: Commit Task 2**

```powershell
git diff --check
git add src/byte_mcp/providers/transport.py src/byte_mcp/providers/__init__.py tests/providers/test_transport.py
git commit -m "feat: add provider transport contracts"
```

---

### Task 3: Exactly-Once Async Provider Transport

**Files:**
- Modify: `src/byte_mcp/providers/transport.py`
- Modify: `tests/providers/test_transport.py`

**Interfaces:**
- Consumes: Task 1 prepared requests and Task 2 transport contracts.
- Produces:

```python
async def execute_once(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    timeout_policy: ProviderTimeoutPolicy,
    *,
    headers: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderTransportResponse: ...
```

- [ ] **Step 1: Add RED tests for exact transmission and request-hash binding**

Use `httpx.MockTransport`/custom async handlers. Required tests include:

```python
@pytest.mark.asyncio
async def test_execute_once_sends_exact_prepared_bytes_once():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert await request.aread() == prepared.body_bytes
        assert request.method == "POST"
        assert str(request.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
        return httpx.Response(200, json={"ok": True})

    response = await execute_once(
        prepared,
        ProviderTransmissionContext(
            provider_started_at="2026-09-08T20:00:00+00:00",
            expected_request_sha256=prepared.request_sha256,
        ),
        short_policy,
        headers={
            "Authorization": "Bearer SECRET",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        transport=httpx.MockTransport(handler),
    )
    assert len(calls) == 1
    assert response.outcome is ProviderAttemptOutcome.COMPLETED
```

Also require tests proving:
- mismatched `expected_request_sha256` fails before handler invocation;
- unknown/extra headers fail before handler invocation;
- missing Authorization or wrong Content-Type/Accept fail before handler invocation;
- redirects are returned as `REJECTED`, not followed;
- a 400/401/429/500 complete response is transport `REJECTED`;
- handler call count remains exactly one for every complete response and transport failure;
- no retry/replay occurs after failure.

- [ ] **Step 2: Add RED tests for transport failure mapping**

Create a tiny custom `httpx.AsyncBaseTransport` that raises each failure on `handle_async_request` and assert:

```text
ConnectTimeout  -> NOT_SENT / CONNECT_TIMEOUT
ConnectError    -> NOT_SENT / CONNECT_ERROR
PoolTimeout     -> NOT_SENT / POOL_TIMEOUT
ReadTimeout     -> OUTCOME_UNKNOWN / READ_TIMEOUT
ReadError       -> OUTCOME_UNKNOWN / READ_ERROR
WriteTimeout    -> OUTCOME_UNKNOWN / WRITE_TIMEOUT
WriteError      -> OUTCOME_UNKNOWN / WRITE_ERROR
RemoteProtocolError -> OUTCOME_UNKNOWN / REMOTE_PROTOCOL_ERROR
other httpx.HTTPError -> OUTCOME_UNKNOWN / HTTP_TRANSPORT_ERROR
```

Use `raise ProviderTransportError(...) from None` behavior and assert `exc.__cause__ is None` and no secret/raw exception message appears in `str(exc)`.

- [ ] **Step 3: Add RED tests for absolute deadline and response bound**

Use a deterministic async transport/byte stream that sleeps beyond a sub-second `absolute_deadline_seconds` and prove:

```text
OUTCOME_UNKNOWN / ABSOLUTE_DEADLINE
```

Use a streaming response that yields bytes totaling more than `8_000_000` before EOF and prove the operation aborts as `OUTCOME_UNKNOWN` with bounded observation and no resend.

- [ ] **Step 4: Run tests and verify RED**

```powershell
python -m pytest tests/providers/test_transport.py -q
```

Expected: failures because `execute_once` behavior is not implemented.

- [ ] **Step 5: Implement `execute_once` with one `AsyncClient` and one stream call**

Production structure must be equivalent to:

```python
async with httpx.AsyncClient(
    transport=transport,
    timeout=httpx.Timeout(
        connect=timeout_policy.connect_seconds,
        read=timeout_policy.read_seconds,
        write=timeout_policy.write_seconds,
        pool=timeout_policy.pool_seconds,
    ),
    follow_redirects=False,
    trust_env=True,
) as client:
    async with asyncio.timeout(timeout_policy.absolute_deadline_seconds):
        async with client.stream(
            prepared_request.method,
            prepared_request.target_origin + prepared_request.endpoint_path,
            headers=validated_headers,
            content=prepared_request.body_bytes,
        ) as response:
            ...
```

Before creating the client:
- validate request hash binding;
- validate headers against exact allow-list/required values;
- never reconstruct or reserialize the body.

Inside the stream:
- mark response headers immediately;
- read with `response.aiter_bytes()`;
- mark first/last body timestamps and decoded byte counts;
- if adding a chunk would exceed `MAX_RESPONSE_BODY_BYTES`, raise an internal sentinel caught outside as `ProviderTransportError(OUTCOME_UNKNOWN, HTTP_TRANSPORT_ERROR or a dedicated local sentinel mapped without expanding the frozen enum)`.

Do **not** add a new provider-neutral failure enum unless the spec is amended. Prefer an internal private sentinel that surfaces `OUTCOME_UNKNOWN` with `HTTP_TRANSPORT_ERROR` while tests separately assert the local bound condition through safe metadata if necessary.

When EOF is reached:

```python
outcome = (
    ProviderAttemptOutcome.COMPLETED
    if 200 <= status_code < 300
    else ProviderAttemptOutcome.REJECTED
)
```

- [ ] **Step 6: Run focused tests and Ruff**

```powershell
python -m pytest tests/providers/test_requests.py tests/providers/test_transport.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

Expected: PASS.

- [ ] **Step 7: Inspect for retry/fallback anti-patterns and commit**

```powershell
git grep -n -E "retry|backoff|tenacity|fallback|alternate" -- src/byte_mcp/providers
```

Review every hit; comments/tests may mention prohibition, production must contain no retry/fallback mechanism.

```powershell
git diff --check
git add src/byte_mcp/providers/transport.py tests/providers/test_transport.py
git commit -m "feat: add exactly-once provider transport"
```

---

### Task 4: NVIDIA Chat Request Validation and Preparation

**Files:**
- Create: `src/byte_mcp/nvidia/chat.py`
- Create: `tests/nvidia/test_chat_request.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `prepare_provider_request`, `PreparedProviderRequest`, `validate_model_id`, `NVIDIA_PROVIDER`.
- Produces: `NvidiaChatMessage`, `prepare_nvidia_chat_request(...)`, `NVIDIA_CHAT_ENDPOINT_PATH`.

Required public constants:

```python
NVIDIA_CHAT_TARGET_ORIGIN = "https://integrate.api.nvidia.com"
NVIDIA_CHAT_ENDPOINT_PATH = "/v1/chat/completions"
```

Required message type:

```python
@dataclass(frozen=True, slots=True)
class NvidiaChatMessage:
    role: str
    content: str
```

Required preparation signature:

```python
def prepare_nvidia_chat_request(
    *,
    model_id: str,
    messages: Sequence[NvidiaChatMessage | Mapping[str, object]],
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 1024,
) -> PreparedProviderRequest: ...
```

- [ ] **Step 1: Add failing request-shape tests**

Create tests proving the exact canonical body decodes to:

```python
{
    "max_tokens": 1024,
    "messages": [{"content": "hello", "role": "user"}],
    "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "n": 1,
    "stream": False,
    "temperature": 0.2,
    "top_p": 0.95,
}
```

Assert provider identity/path/origin/model fields on the prepared request.

- [ ] **Step 2: Add failing validation tests**

Parameterize rejection of:
- empty messages;
- role outside `system`, `user`, `assistant`;
- message mappings with fields other than exactly `role` and `content`;
- non-string/empty content if the spec requires non-empty text (use non-empty text for NVIDIA-01 to avoid meaningless calls);
- bool temperature/top_p/max_tokens;
- NaN/Infinity;
- temperature `<0` or `>2`;
- top_p `<=0` or `>1`;
- max_tokens `<1` or `>65536`;
- invalid model IDs.

Also assert generated body contains none of:

```text
tools
tool_choice
response_format
chat_template_kwargs
reasoning_budget
seed
providerOptions
```

- [ ] **Step 3: Run tests and prove RED**

```powershell
python -m pytest tests/nvidia/test_chat_request.py -q
```

Expected: collection fails because `byte_mcp.nvidia.chat` does not exist.

- [ ] **Step 4: Implement bounded NVIDIA request preparation**

Normalize mappings into immutable messages, reject unknown fields, validate numbers using `math.isfinite`, then call `prepare_provider_request` once with the fixed NVIDIA provider/origin/path and the validated body mapping.

Do not read the API key in request preparation.

- [ ] **Step 5: Export request API and run focused gates**

Update `src/byte_mcp/nvidia/__init__.py` to export only safe preparation/message/constants required by callers. Do not expose any secret-bearing execution helper.

```powershell
python -m pytest tests/nvidia/test_chat_request.py tests/providers/test_requests.py -q
python -m ruff check src/byte_mcp/nvidia/chat.py tests/nvidia/test_chat_request.py src/byte_mcp/nvidia/__init__.py
python -m ruff format --check src/byte_mcp/nvidia/chat.py tests/nvidia/test_chat_request.py src/byte_mcp/nvidia/__init__.py
```

- [ ] **Step 6: Commit Task 4**

```powershell
git diff --check
git add src/byte_mcp/nvidia/chat.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_chat_request.py
git commit -m "feat: prepare bounded NVIDIA chat requests"
```

---

### Task 5: NVIDIA Chat Response and Safe HTTP Error Classification

**Files:**
- Modify: `src/byte_mcp/nvidia/chat.py`
- Modify: `src/byte_mcp/nvidia/errors.py`
- Create: `tests/nvidia/test_chat_response.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `ProviderTransportResponse`.
- Produces: `NvidiaChatFailureKind`, `NvidiaChatError`, `NvidiaChatUsage`, `NvidiaChatResult`, `parse_nvidia_chat_response(...)`, `classify_nvidia_http_rejection(...)`.

Required bounded failure enum:

```python
class NvidiaChatFailureKind(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    REQUEST = "REQUEST"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    RATE_LIMIT = "RATE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"
    REDIRECT_REJECTED = "REDIRECT_REJECTED"
    PROTOCOL = "PROTOCOL"
```

Required result types:

```python
@dataclass(frozen=True, slots=True)
class NvidiaChatUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None

@dataclass(frozen=True, slots=True)
class NvidiaChatResult:
    response_id: str | None
    model_id: str
    content: str
    finish_reason: str | None
    usage: NvidiaChatUsage
```

- [ ] **Step 1: Add RED tests for safe status classification**

Test exact mapping:

```text
300-399 -> REDIRECT_REJECTED
400 -> REQUEST
401 -> AUTHENTICATION
403 -> PERMISSION
404 -> UNAVAILABLE
413 -> REQUEST_TOO_LARGE
422 -> REQUEST
429 -> RATE_LIMIT
500-599 -> UNAVAILABLE
other non-2xx -> REQUEST
```

`NvidiaChatError` message must be only the bounded enum value and must not include response body text.

- [ ] **Step 2: Add RED tests for successful envelope parsing**

Use a complete 200 transport response whose JSON body contains:

```python
{
    "id": "chatcmpl-123",
    "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello"},
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    },
    "ignored_provider_field": {"anything": "discarded"},
}
```

Assert only bounded result fields survive.

- [ ] **Step 3: Add RED tests for malformed 2xx protocol responses**

Reject safely when:
- JSON is invalid;
- top-level value is not mapping;
- returned `model` is absent or differs from requested model;
- `choices` is not a list of exactly one usable choice;
- choice index is not `0`;
- assistant message role is not `assistant`;
- content is not a string;
- finish reason is non-string or exceeds a bounded length;
- response ID is non-string or exceeds a bounded length;
- usage counters are negative, booleans, non-integers, or implausibly large beyond a fixed safe metadata ceiling.

A malformed 2xx must raise `NvidiaChatError(PROTOCOL)` and tests must retain/assert that the originating transport response outcome was `COMPLETED`; do not transform it into `OUTCOME_UNKNOWN`.

- [ ] **Step 4: Run tests and prove RED**

```powershell
python -m pytest tests/nvidia/test_chat_response.py -q
```

- [ ] **Step 5: Implement safe parsing and classification**

Implement JSON decode from the already-bounded `ProviderTransportResponse.body`. Do not retain raw payload in result/error objects.

For complete rejected responses, classify by status only for NVIDIA-01; do not inspect arbitrary provider prose. If later NVIDIA documentation requires bounded provider error codes, add them only in a future approved amendment.

Use explicit maximum metadata lengths, e.g. response ID and finish reason `<= 256` characters, and usage counters `<= 2_147_483_647`.

- [ ] **Step 6: Export safe result/error API and run focused gates**

```powershell
python -m pytest tests/nvidia/test_chat_response.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia
```

- [ ] **Step 7: Commit Task 5**

```powershell
git diff --check
git add src/byte_mcp/nvidia/chat.py src/byte_mcp/nvidia/errors.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_chat_response.py
git commit -m "feat: parse bounded NVIDIA chat responses"
```

---

### Task 6: NVIDIA Hosted Chat Settings and Offline Execution Adapter

**Files:**
- Modify: `src/byte_mcp/nvidia/settings.py`
- Modify: `src/byte_mcp/nvidia/chat.py`
- Create: `tests/nvidia/test_chat_execution.py`
- Modify: `tests/nvidia/test_settings.py`

**Interfaces:**
- Consumes: Task 3 `execute_once`, Task 4 prepared request, Task 5 response parser/errors.
- Produces: `NVIDIA_CHAT_TIMEOUT_POLICY`, `execute_prepared_nvidia_chat(...)`.

Required execution signature:

```python
async def execute_prepared_nvidia_chat(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    settings: NvidiaHostedSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> NvidiaChatResult: ...
```

This is an internal/library execution API only; it is not registered as MCP and does not create durable attempts.

- [ ] **Step 1: Add RED settings tests**

Extend `tests/nvidia/test_settings.py` to prove chat timeout settings default to:

```text
connect_seconds = 10
write_seconds = 30
read_seconds = 300
pool_seconds = 10
absolute_deadline_seconds = 300
```

Prefer a single immutable `ProviderTimeoutPolicy` property or explicit fields that deterministically construct it. Environment configuration, if exposed, must be bounded to production-safe ranges and must never permit values above 600 or arbitrary origin overrides.

Preserve existing catalog timeout behavior exactly.

- [ ] **Step 2: Add RED execution tests using MockTransport only**

Test:
- missing API key fails `CONFIGURATION` before handler invocation;
- exact headers are `Authorization`, `Content-Type: application/json`, `Accept: application/json`;
- API key never enters prepared body/hash/repr/result/error;
- successful one-response flow returns parsed `NvidiaChatResult`;
- complete 401/403/404/413/429/5xx responses become the correct bounded `NvidiaChatError` without raw provider text;
- provider-neutral `ProviderTransportError` propagates without being reclassified as deterministic NVIDIA rejection;
- request hash mismatch fails before network;
- handler invocation count is exactly one on all contacted paths.

- [ ] **Step 3: Run tests and prove RED**

```powershell
python -m pytest tests/nvidia/test_settings.py tests/nvidia/test_chat_execution.py -q
```

- [ ] **Step 4: Implement settings extension and execution adapter**

Keep `NvidiaHostedSettings` secret-safe. Construct authorization only immediately before `execute_once`:

```python
headers = {
    "Authorization": f"Bearer {settings.api_key}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
```

Then:

```python
transport_response = await execute_once(...)
if transport_response.outcome is ProviderAttemptOutcome.REJECTED:
    raise classify_nvidia_http_rejection(transport_response.status_code) from None
return parse_nvidia_chat_response(
    transport_response,
    expected_model_id=prepared_request.model_id,
)
```

Do not catch `ProviderTransportError` except to re-raise unchanged if necessary for typing/control flow.

Do not call catalog discovery, model registry transition, OX, Wolfram, or server registration.

- [ ] **Step 5: Run focused suites and Ruff**

```powershell
python -m pytest tests/providers tests/nvidia -q
python -m ruff check src/byte_mcp/providers src/byte_mcp/nvidia tests/providers tests/nvidia
python -m ruff format --check src/byte_mcp/providers src/byte_mcp/nvidia tests/providers tests/nvidia
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```powershell
git diff --check
git add src/byte_mcp/nvidia/settings.py src/byte_mcp/nvidia/chat.py tests/nvidia/test_settings.py tests/nvidia/test_chat_execution.py
git commit -m "feat: execute NVIDIA chat through shared transport"
```

---

### Task 7: NVIDIA-01 Security and Isolation Regression Gate

**Files:**
- Create: `tests/nvidia/test_n01_security_invariants.py`
- No production modification expected.

**Interfaces:**
- Consumes all NVIDIA-01 public/library interfaces.
- Produces no runtime interface; freezes security and architectural invariants.

- [ ] **Step 1: Add security/isolation tests**

Create tests that inspect source/import/runtime behavior and prove:

1. provider-neutral modules do not import `byte_mcp.nvidia`, `byte_mcp.ox`, or `byte_mcp.wolfram`;
2. NVIDIA chat modules do not import OX or Wolfram;
3. no NVIDIA inference tool is registered in `src/byte_mcp/server.py`;
4. no retry/backoff package or retry loop/helper appears in NVIDIA-01 production source;
5. no model/provider fallback behavior exists;
6. request `repr`, transport response `repr`, transport error strings, NVIDIA error strings, and result reprs never contain a test secret;
7. response headers and raw bodies are absent from `ProviderTransportObservation`;
8. prepared request hash is stable and exact body bytes are unchanged between prepare and transmitted request;
9. transmission context mismatch causes zero transport invocations;
10. catalog/registry remain isolated and do not qualify/enable a model as a side effect of chat preparation/execution;
11. environment containing only `NGC_API_KEY` still produces missing hosted credential behavior;
12. imports with invalid NVIDIA configuration do not break core/OX/Wolfram imports.

Use static source inspection only for architectural invariants; behavioral invariants must exercise code with local mocks.

- [ ] **Step 2: Run security tests**

```powershell
python -m pytest tests/nvidia/test_n01_security_invariants.py -q
```

Expected: PASS after any test-only corrections. If a production defect is discovered, repair only the approved NVIDIA-01 files, rerun the owning focused task tests, then rerun this gate.

- [ ] **Step 3: Run complete NVIDIA/provider suite**

```powershell
python -m pytest tests/providers tests/nvidia -q
```

Expected: PASS.

- [ ] **Step 4: Commit security gate**

```powershell
git diff --check
git add tests/nvidia/test_n01_security_invariants.py
git commit -m "test: freeze NVIDIA-01 transport security invariants"
```

---

### Task 8: Final Qualification, Baseline-Aware Formatting, and CI Handoff

**Files:**
- No production change expected.
- No additional test file expected unless a verified NVIDIA-01 defect requires a scoped fix.

**Interfaces:**
- Qualification only.

- [ ] **Step 1: Verify exact changed-file scope against qualified predecessor**

Run:

```powershell
git diff --name-only 48c076512f233127ab119c522d9f4cd620587078...HEAD
```

Allowed production paths are only:

```text
src/byte_mcp/providers/__init__.py
src/byte_mcp/providers/requests.py
src/byte_mcp/providers/transport.py
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/errors.py
src/byte_mcp/nvidia/settings.py
src/byte_mcp/nvidia/chat.py
```

Allowed test/docs paths are only:

```text
tests/providers/test_requests.py
tests/providers/test_transport.py
tests/nvidia/test_chat_request.py
tests/nvidia/test_chat_response.py
tests/nvidia/test_chat_execution.py
tests/nvidia/test_n01_security_invariants.py
docs/superpowers/specs/2026-09-08-nvidia-provider-n01-transport-design.md
docs/superpowers/plans/2026-09-08-nvidia-provider-n01-transport-implementation-plan.md
```

If any of these appear, STOP and report before proceeding:

```text
src/byte_mcp/ox/**
src/byte_mcp/wolfram/**
src/byte_mcp/server.py
pyproject.toml
src/byte_mcp/nvidia/catalog.py
src/byte_mcp/nvidia/registry.py
```

- [ ] **Step 2: Run focused NVIDIA/provider qualification**

```powershell
python -m pytest tests/providers tests/nvidia -q
```

Expected: PASS.

- [ ] **Step 3: Run full repository regression and compile**

```powershell
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m pytest -q
```

Expected: compile exit 0; pytest PASS with zero failures.

- [ ] **Step 4: Run whole-repository lint**

```powershell
python -m ruff check .
```

Expected: PASS.

- [ ] **Step 5: Run NVIDIA-01 changed-scope format gate**

```powershell
python -m ruff format --check `
  src/byte_mcp/providers `
  src/byte_mcp/nvidia `
  tests/providers `
  tests/nvidia
```

Expected: PASS for every NVIDIA-01-created/modified Python file.

- [ ] **Step 6: Record repository-wide format result baseline-aware**

Run once:

```powershell
python -m ruff format --check .
```

If this exits non-zero, compare failing file paths to the exact `48c0765...` baseline. Acceptance is allowed only when every remaining formatting failure existed at the qualified predecessor and no NVIDIA-01 changed file fails. Do not reformat unrelated historical files.

Record:

```text
repository_wide_format: PASS
```

or, if historical debt still exists:

```text
repository_wide_format: PRE_EXISTING_BASELINE_FAILURES_ONLY
nvidia_01_new_format_failures: 0
```

Never report the whole repository as format-clean unless the command actually exits 0.

- [ ] **Step 7: Reconfirm zero provider activity and absence of runtime integration**

Confirm from execution history and source scope:

```text
NVIDIA catalog calls: 0
NVIDIA inference calls: 0
OX provider calls: 0
Wolfram provider calls: 0
other provider/model calls: 0
automatic retries: 0
fallbacks: 0
runtime promotion: NO
MCP NVIDIA inference registration: NO
```

- [ ] **Step 8: Verify local clean state and commit history**

```powershell
git status --short --branch
git log --oneline de1b931e000969210379c8326f0f8c9a097ccbb2..HEAD
```

Working tree must be clean before handoff/push.

- [ ] **Step 9: Push only after the executor's authorization includes push**

If push is explicitly authorized in the execution prompt, perform a normal fast-forward push of `feat/nvidia-provider-n01-transport`. Never force push.

If push is not authorized, stop with the local final HEAD and provide exact push command for Nolan.

- [ ] **Step 10: Require fresh GitHub Actions CI before final NVIDIA-01 qualification**

After the final commit is pushed, GitHub Actions must run on the exact remote HEAD. Required CI evidence:
- Linux Python 3.12 install/compile/lint/test PASS;
- Windows Python 3.12 install/compile/lint/test PASS;
- Windows launcher jobs PASS.

Do not claim `NVIDIA-01_STATUS: QUALIFIED` until that fresh CI run succeeds on the exact final branch HEAD.

Final report format:

```text
=== NVIDIA-01 IMPLEMENTATION REPORT ===

repository:
branch:
qualified_predecessor: 48c076512f233127ab119c522d9f4cd620587078
spec_head: de1b931e000969210379c8326f0f8c9a097ccbb2
final_head:

tasks:
  Task 1: PASS
  Task 2: PASS
  Task 3: PASS
  Task 4: PASS
  Task 5: PASS
  Task 6: PASS
  Task 7: PASS
  Task 8: PASS

provider_calls:
  NVIDIA_catalog: 0
  NVIDIA_inference: 0
  OX: 0
  Wolfram: 0
  other: 0

automatic_retries: 0
fallbacks: 0

focused_tests:
full_pytest:
compile:
ruff_check:
changed_scope_format:
repository_wide_format:

frozen_paths_modified:
  src/byte_mcp/ox/**: NO
  src/byte_mcp/wolfram/**: NO
  src/byte_mcp/server.py: NO
  pyproject.toml: NO
  src/byte_mcp/nvidia/catalog.py: NO
  src/byte_mcp/nvidia/registry.py: NO

fresh_github_ci:
  exact_head:
  linux_python_3_12:
  windows_python_3_12:
  windows_launcher:

spec_deviations:
unresolved_issues:

NVIDIA-01_STATUS: QUALIFIED | NOT_QUALIFIED
```

---

## Execution Stop Conditions

Stop before mutation or further execution if any of the following occurs:

1. branch identity or qualified predecessor cannot be verified;
2. approved spec is missing or differs materially from `de1b931e000969210379c8326f0f8c9a097ccbb2` without a documented amendment;
3. any production change outside the planned NVIDIA-01 file set appears necessary;
4. OX, Wolfram, server, dependency, catalog, or registry mutation appears necessary;
5. a live provider request appears necessary for a test or verification step;
6. a real API credential appears in tracked content, test snapshots, exception text, logs, or evidence;
7. the implementation would require retry, replay, alternate target/model/provider, or redirect following;
8. the exact prepared bytes cannot be proven identical to the transmitted bytes;
9. an ambiguous transport failure would be mapped to deterministic rejection/completion;
10. response-size abort cannot be kept conservatively `OUTCOME_UNKNOWN`;
11. durable authorization/evidence or runtime/MCP integration becomes necessary before NVIDIA-02;
12. final tests/CI cannot be freshly verified.

Preserve completed commits and return a deterministic resume receipt instead of broadening scope.
