# NVIDIA-01 Exactly-Once Hosted Chat Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement provider-neutral prepared-request identity and exactly-once async HTTP transport, then add a bounded NVIDIA hosted `/v1/chat/completions` adapter without touching OX/Wolfram behavior or making any live provider call.

**Architecture:** Extend `byte_mcp.providers` with canonical request preparation and one-shot transport contracts. Add `byte_mcp.nvidia.chat` above that shared transport for NVIDIA request validation, safe HTTP classification, and bounded OpenAI-compatible chat response parsing; durable authorization/evidence remains NVIDIA-02.

**Tech Stack:** Python 3.12+, stdlib `asyncio`, `dataclasses`, `datetime`, `enum`, `hashlib`, `json`, `math`, existing `httpx>=0.28.1,<1`, pytest, Ruff. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-nvidia-provider-n01-transport-design.md`

## Global Constraints

- Branch: `feat/nvidia-provider-n01-transport`.
- Qualified predecessor: `48c076512f233127ab119c522d9f4cd620587078`.
- Approved spec head: `de1b931e000969210379c8326f0f8c9a097ccbb2`.
- Zero live NVIDIA catalog or inference requests during implementation/tests.
- Zero OX, Wolfram, or other provider/model requests.
- Exactly one HTTP request maximum per `execute_once()` call; zero retry, replay, reconnect helper, redirect following, alternate URL, model fallback, or provider fallback.
- Production transport: `follow_redirects=False`, `trust_env=True`.
- Hosted credential: `NVIDIA_API_KEY` only; never fall back to `NGC_API_KEY`.
- NVIDIA production target is exactly `https://integrate.api.nvidia.com/v1/chat/completions`.
- Canonical JSON: `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, UTF-8.
- Request body bound: `4_000_000` bytes.
- Response body bound: `8_000_000` decoded bytes.
- Any local response-size abort before EOF is `OUTCOME_UNKNOWN` and uses existing `ProviderTransportFailureKind.HTTP_TRANSPORT_ERROR`; do not add a new failure enum in NVIDIA-01.
- `CONNECT_TIMEOUT`, `CONNECT_ERROR`, `POOL_TIMEOUT` -> `NOT_SENT`.
- `ABSOLUTE_DEADLINE`, `READ_TIMEOUT`, `READ_ERROR`, `WRITE_TIMEOUT`, `WRITE_ERROR`, `REMOTE_PROTOCOL_ERROR`, `HTTP_TRANSPORT_ERROR` -> `OUTCOME_UNKNOWN`.
- Fully received 2xx -> `COMPLETED`; fully received 3xx/4xx/5xx -> `REJECTED`.
- Malformed fully received 2xx remains transport `COMPLETED` and becomes NVIDIA `PROTOCOL` failure only at the adapter layer.
- `ProviderTransmissionContext.expected_request_sha256` must equal `PreparedProviderRequest.request_sha256` before any transport object is invoked.
- Transport header keys are exactly `Authorization`, `Content-Type`, `Accept`; extra/missing headers fail locally. Required values: `Content-Type=application/json`, `Accept=application/json`, non-empty `Authorization` beginning `Bearer `.
- API key, authorization header, request body, response body, arbitrary headers, raw provider prose, and raw `httpx` exception text must not appear in ordinary reprs/errors/observations.
- NVIDIA-01 message roles: `system`, `user`, `assistant` only. Message content may be any string, including the empty string; the adapter does not invent a non-empty-content rule not present in the approved spec.
- Request bounds: `0 <= temperature <= 2`, `0 < top_p <= 1`, `1 <= max_tokens <= 65536`; bool/NaN/Infinity rejected.
- `n=1` and `stream=False` are generated constants, not caller parameters.
- No tools, tool messages, multimodal content, streaming, JSON mode, response-format, reasoning controls, seed, stop extensions, or provider routing hints.
- Provider-neutral code must not import NVIDIA/OX/Wolfram packages.
- Frozen: `src/byte_mcp/ox/**`, `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, `pyproject.toml`, `src/byte_mcp/nvidia/catalog.py`, `src/byte_mcp/nvidia/registry.py`.
- No MCP NVIDIA inference registration, runtime promotion, durable attempt/evidence store, authorization state machine, or provider lane in NVIDIA-01.
- Baseline-aware format gate: every NVIDIA-01 changed Python file must pass `ruff format --check`; historical failures outside the changed set may remain only if proven unchanged from the qualified predecessor.
- Final qualification requires full pytest, compile, Ruff lint, changed-scope format, frozen-path verification, and fresh GitHub Actions CI on exact final pushed HEAD.

---

## File Map

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

---

### Task 1: Canonical Prepared Provider Requests

**Files:**
- Create: `src/byte_mcp/providers/requests.py`
- Create: `tests/providers/test_requests.py`
- Modify: `src/byte_mcp/providers/__init__.py`

**Produces:** immutable `PreparedProviderRequest` with fields `provider_id`, `method`, `target_origin`, `endpoint_path`, `model_id`, `body_bytes`, `payload_sha256`, `request_sha256`; and function `prepare_provider_request(*, provider_id: str, method: str, target_origin: str, endpoint_path: str, model_id: str, body: object) -> PreparedProviderRequest`.

- [ ] **Step 1: Write RED tests** proving canonical key order, UTF-8 non-ASCII handling, exact `payload_sha256`, stable `request_sha256`, changed hash when body/destination changes, safe repr, invalid JSON numbers, invalid provider/model/origin/path/method, and `4_000_000` byte bound.

Representative assertion:

```python
expected = json.dumps(
    {"z": 1, "a": "é"},
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
assert prepared.body_bytes == expected
assert prepared.payload_sha256 == hashlib.sha256(expected).hexdigest()
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/providers/test_requests.py -q
```

Expected: import/collection failure because module does not exist.

- [ ] **Step 3: Implement minimal preparation** with constants:

```python
MAX_PREPARED_BODY_BYTES = 4_000_000
REQUEST_SCHEMA = "byte-mcp-provider-request-v1"
```

Canonical metadata envelope must be exactly:

```python
{
    "endpoint_path": endpoint_path,
    "method": method,
    "model_id": model_id,
    "payload_sha256": payload_sha256,
    "provider_id": provider_id,
    "request_schema": REQUEST_SCHEMA,
    "target_origin": target_origin,
}
```

Require uppercase `POST`; absolute HTTPS origin with no path/query/fragment; endpoint starts `/` and contains no query, fragment, CR/LF, or spaces. Hash exact canonical bytes. `repr` excludes `body_bytes`.

- [ ] **Step 4: Export** `PreparedProviderRequest`, `prepare_provider_request`, `MAX_PREPARED_BODY_BYTES` from `byte_mcp.providers`.

- [ ] **Step 5: GREEN + Ruff**

```powershell
python -m pytest tests/providers/test_requests.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/providers/requests.py src/byte_mcp/providers/__init__.py tests/providers/test_requests.py
git commit -m "feat: add canonical provider request identity"
```

---

### Task 2: Provider Transport Contracts

**Files:**
- Create: `src/byte_mcp/providers/transport.py`
- Create: `tests/providers/test_transport.py`
- Modify: `src/byte_mcp/providers/__init__.py`

**Produces:**

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

class ProviderTransportError(ByteMCPError):
    attempt_outcome: ProviderAttemptOutcome
    transport_failure_kind: ProviderTransportFailureKind
    transport_observation: ProviderTransportObservation
```

- [ ] **Step 1: Write RED tests** for timezone-aware `provider_started_at`, lowercase 64-hex expected hash, timeout finite positive values `<=600`, safe response repr/error text, and observation metadata-only contract.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/providers/test_transport.py -q
```

- [ ] **Step 3: Implement contracts** with:

```python
MAX_RESPONSE_BODY_BYTES = 8_000_000
MAX_TIMEOUT_SECONDS = 600.0
```

Implement private `_TransportTracker`; recognized proxy env keys are uppercase/lowercase HTTP/HTTPS/ALL proxy names and only presence is recorded.

- [ ] **Step 4: Export public contract types** from `byte_mcp.providers`.

- [ ] **Step 5: GREEN + Ruff**

```powershell
python -m pytest tests/providers/test_transport.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/providers/transport.py src/byte_mcp/providers/__init__.py tests/providers/test_transport.py
git commit -m "feat: add provider transport contracts"
```

---

### Task 3: Exactly-Once Async Transport Execution

**Files:**
- Modify: `src/byte_mcp/providers/transport.py`
- Modify: `tests/providers/test_transport.py`

**Produces:** `execute_once(prepared_request: PreparedProviderRequest, transmission_context: ProviderTransmissionContext, timeout_policy: ProviderTimeoutPolicy, *, headers: Mapping[str, str], transport: httpx.AsyncBaseTransport | None = None) -> ProviderTransportResponse`.

- [ ] **Step 1: Write RED tests** proving exact prepared bytes sent once; exact URL/method; hash mismatch -> zero handler calls; missing/extra/wrong headers -> zero calls; redirect not followed; complete 4xx/5xx -> `REJECTED`; complete 2xx -> `COMPLETED`; all contacted paths invoke handler exactly once.

- [ ] **Step 2: Write RED failure-mapping tests** using injected transports that raise each `httpx` exception and assert the frozen `NOT_SENT`/`OUTCOME_UNKNOWN` mapping. Assert `ProviderTransportError.__cause__ is None` and raw exception text is absent.

- [ ] **Step 3: Write RED deadline/body-bound tests** with an async stream that sleeps beyond a sub-second absolute deadline and another that exceeds `8_000_000` decoded bytes before EOF. Both must produce `OUTCOME_UNKNOWN`; body-bound uses `HTTP_TRANSPORT_ERROR`; call count remains one.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/providers/test_transport.py -q
```

- [ ] **Step 5: Implement one-shot execution** with exactly one `httpx.AsyncClient` and one `client.stream()` call:

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
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BODY_BYTES:
                    raise _ResponseBodyLimitExceeded
                body.extend(chunk)
```

Validate hash/header contract before client creation. Catch private `_ResponseBodyLimitExceeded` outside the stream and raise safe `ProviderTransportError` with `OUTCOME_UNKNOWN` + `HTTP_TRANSPORT_ERROR` from `None`. Never call `json=`.

- [ ] **Step 6: GREEN + Ruff**

```powershell
python -m pytest tests/providers/test_requests.py tests/providers/test_transport.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

- [ ] **Step 7: Commit**

```powershell
git add src/byte_mcp/providers/transport.py tests/providers/test_transport.py
git commit -m "feat: add exactly-once provider transport"
```

---

### Task 4: NVIDIA Chat Request Preparation

**Files:**
- Create: `src/byte_mcp/nvidia/chat.py`
- Create: `tests/nvidia/test_chat_request.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Produces:** constants `NVIDIA_CHAT_TARGET_ORIGIN = "https://integrate.api.nvidia.com"`, `NVIDIA_CHAT_ENDPOINT_PATH = "/v1/chat/completions"`; immutable `NvidiaChatMessage(role: str, content: str)`; function `prepare_nvidia_chat_request(*, model_id: str, messages: Sequence[NvidiaChatMessage | Mapping[str, object]], temperature: float = 0.2, top_p: float = 0.95, max_tokens: int = 1024) -> PreparedProviderRequest`.

- [ ] **Step 1: Write RED tests** for exact body keys/values, fixed provider/origin/path, roles `system/user/assistant`, exact mapping keys `role/content`, string content including empty string, non-empty message sequence, numeric bounds, bool/NaN/Infinity rejection, invalid model IDs, and absence of excluded fields.

Exact decoded body for baseline fixture:

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

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_chat_request.py -q
```

- [ ] **Step 3: Implement minimal request adapter**. Normalize accepted mappings to `NvidiaChatMessage`, reject unknown keys, validate finite numeric bounds, construct body once, call `prepare_provider_request` once. Do not read API key here.

- [ ] **Step 4: Export safe request APIs** from `byte_mcp.nvidia`.

- [ ] **Step 5: GREEN + Ruff**

```powershell
python -m pytest tests/nvidia/test_chat_request.py tests/providers/test_requests.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/nvidia/chat.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_chat_request.py
git commit -m "feat: prepare bounded NVIDIA chat requests"
```

---

### Task 5: NVIDIA Chat Response Parsing and Safe Rejection Classification

**Files:**
- Modify: `src/byte_mcp/nvidia/chat.py`
- Modify: `src/byte_mcp/nvidia/errors.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`
- Create: `tests/nvidia/test_chat_response.py`

**Produces:** enum `NvidiaChatFailureKind` with exactly `CONFIGURATION`, `AUTHENTICATION`, `PERMISSION`, `REQUEST`, `REQUEST_TOO_LARGE`, `RATE_LIMIT`, `UNAVAILABLE`, `REDIRECT_REJECTED`, `PROTOCOL`; `NvidiaChatError`; immutable `NvidiaChatUsage(prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None)`; immutable `NvidiaChatResult(response_id: str | None, model_id: str, content: str, finish_reason: str | None, usage: NvidiaChatUsage)`.

- [ ] **Step 1: Write RED status tests** for `3xx REDIRECT_REJECTED`, `400 REQUEST`, `401 AUTHENTICATION`, `403 PERMISSION`, `404 UNAVAILABLE`, `413 REQUEST_TOO_LARGE`, `422 REQUEST`, `429 RATE_LIMIT`, `5xx UNAVAILABLE`, other non-2xx `REQUEST`. Error text contains enum only, never body prose.

- [ ] **Step 2: Write RED parser tests** for one choice/index 0/assistant content, model equality, optional bounded id/finish reason, optional non-negative usage counters, unknown-field discard.

- [ ] **Step 3: Write RED protocol-failure tests** for malformed JSON/top-level/choices/index/role/content/model mismatch/oversized metadata/invalid usage. Assert transport response itself remains `COMPLETED` while parser raises NVIDIA `PROTOCOL`.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/nvidia/test_chat_response.py -q
```

- [ ] **Step 5: Implement** status-only rejection classification and bounded parsing. Bounds: response ID and finish reason max `256` chars; usage counters integer, not bool, range `0..2_147_483_647`. Discard raw envelope after parse.

- [ ] **Step 6: GREEN + Ruff**

```powershell
python -m pytest tests/nvidia/test_chat_response.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia
```

- [ ] **Step 7: Commit**

```powershell
git add src/byte_mcp/nvidia/chat.py src/byte_mcp/nvidia/errors.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_chat_response.py
git commit -m "feat: parse bounded NVIDIA chat responses"
```

---

### Task 6: Hosted Chat Settings and Offline Execution Adapter

**Files:**
- Modify: `src/byte_mcp/nvidia/settings.py`
- Modify: `src/byte_mcp/nvidia/chat.py`
- Modify: `tests/nvidia/test_settings.py`
- Create: `tests/nvidia/test_chat_execution.py`

**Produces:** fixed `NVIDIA_CHAT_TIMEOUT_POLICY = ProviderTimeoutPolicy(connect_seconds=10.0, write_seconds=30.0, read_seconds=300.0, pool_seconds=10.0, absolute_deadline_seconds=300.0)`; function `execute_prepared_nvidia_chat(prepared_request: PreparedProviderRequest, transmission_context: ProviderTransmissionContext, settings: NvidiaHostedSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> NvidiaChatResult`.

- [ ] **Step 1: Write RED settings tests** preserving catalog settings and proving fixed chat timeout values. Do not add arbitrary base URL configuration.

- [ ] **Step 2: Write RED execution tests** using MockTransport only: missing key -> `CONFIGURATION` with zero calls; exact three headers; secret absent from prepared hashes/reprs/results/errors; one successful call; complete rejection mappings; transport errors propagate unchanged; hash mismatch -> zero calls; each contacted path exactly one call.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest tests/nvidia/test_settings.py tests/nvidia/test_chat_execution.py -q
```

- [ ] **Step 4: Implement execution adapter**. Construct ephemeral headers immediately before `execute_once()`. On `REJECTED`, map status to `NvidiaChatError`; on `COMPLETED`, parse response. Do not catch/reclassify `ProviderTransportError`. Do not call catalog, registry transitions, OX, Wolfram, or server registration.

- [ ] **Step 5: GREEN + Ruff**

```powershell
python -m pytest tests/providers tests/nvidia -q
python -m ruff check src/byte_mcp/providers src/byte_mcp/nvidia tests/providers tests/nvidia
python -m ruff format --check src/byte_mcp/providers src/byte_mcp/nvidia tests/providers tests/nvidia
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/nvidia/settings.py src/byte_mcp/nvidia/chat.py tests/nvidia/test_settings.py tests/nvidia/test_chat_execution.py
git commit -m "feat: execute NVIDIA chat through shared transport"
```

---

### Task 7: Security and Isolation Invariants

**Files:**
- Create: `tests/nvidia/test_n01_security_invariants.py`
- No production modification expected.

- [ ] **Step 1: Write tests** proving provider-neutral modules import no NVIDIA/OX/Wolfram modules; NVIDIA chat imports no OX/Wolfram; server contains no NVIDIA inference registration; production contains no retry/backoff/fallback behavior; secrets are absent from all ordinary repr/error/result/observation surfaces; observation contains no bodies or headers; transmitted bytes equal prepared bytes exactly; request-hash mismatch causes zero calls; catalog/registry state does not change through preparation/execution; `NGC_API_KEY` alone never satisfies hosted credential; invalid NVIDIA configuration does not break core/OX/Wolfram imports.

- [ ] **Step 2: Run**

```powershell
python -m pytest tests/nvidia/test_n01_security_invariants.py -q
python -m pytest tests/providers tests/nvidia -q
```

Expected: PASS. If a production defect is found, repair only an approved NVIDIA-01 production file and rerun the owning focused suite plus this gate.

- [ ] **Step 3: Commit**

```powershell
git add tests/nvidia/test_n01_security_invariants.py
git commit -m "test: freeze NVIDIA-01 transport security invariants"
```

---

### Task 8: Final Qualification and CI Handoff

**Files:** no expected production changes.

- [ ] **Step 1: Verify changed scope**

```powershell
git diff --name-only 48c076512f233127ab119c522d9f4cd620587078...HEAD
```

Allowed production paths only:

```text
src/byte_mcp/providers/__init__.py
src/byte_mcp/providers/requests.py
src/byte_mcp/providers/transport.py
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/errors.py
src/byte_mcp/nvidia/settings.py
src/byte_mcp/nvidia/chat.py
```

Allowed non-production additions only:

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

Any OX/Wolfram/server/pyproject/catalog/registry change is a STOP.

- [ ] **Step 2: Run focused and full gates**

```powershell
python -m pytest tests/providers tests/nvidia -q
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m pytest -q
python -m ruff check .
python -m ruff format --check src/byte_mcp/providers src/byte_mcp/nvidia tests/providers tests/nvidia
```

All must pass except repository-wide historical format debt handled by Step 3.

- [ ] **Step 3: Run repository-wide format check once**

```powershell
python -m ruff format --check .
```

If non-zero, prove every failing file existed and already failed at `48c076512f233127ab119c522d9f4cd620587078`, and prove no NVIDIA-01 changed file is in the failure set. Do not reformat unrelated historical files.

- [ ] **Step 4: Verify zero provider/runtime activity**

Record exactly:

```text
NVIDIA catalog calls: 0
NVIDIA inference calls: 0
OX calls: 0
Wolfram calls: 0
other provider/model calls: 0
automatic retries: 0
fallbacks: 0
runtime promotion: NO
NVIDIA inference MCP registration: NO
```

- [ ] **Step 5: Verify clean local state**

```powershell
git status --short --branch
git log --oneline de1b931e000969210379c8326f0f8c9a097ccbb2..HEAD
```

- [ ] **Step 6: Push only when execution authorization explicitly permits it.** Normal fast-forward push only; never force push.

- [ ] **Step 7: Require fresh GitHub Actions CI** on exact final remote HEAD. Required jobs: Linux Python 3.12 compile/lint/test PASS, Windows Python 3.12 compile/lint/test PASS, both Windows launcher jobs PASS.

Only then may final report state `NVIDIA-01_STATUS: QUALIFIED`; otherwise state `NOT_QUALIFIED` with exact blocker and resume boundary.

---

## Stop Conditions

Stop rather than broaden scope if:

1. branch/predecessor/spec identity fails;
2. any frozen production path needs modification;
3. a live provider call appears necessary;
4. a real credential enters tracked content or ordinary evidence/output;
5. retry/replay/fallback/redirect following appears necessary;
6. exact hashed bytes cannot be proven identical to transmitted bytes;
7. an ambiguous transmission would be classified deterministic;
8. response-size abort cannot remain `OUTCOME_UNKNOWN`;
9. durable authorization/evidence/runtime/MCP integration becomes necessary before NVIDIA-02;
10. final tests or exact-head CI cannot be freshly verified.

Preserve completed commits and return a deterministic resume receipt rather than improvising.
