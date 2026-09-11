# NVIDIA-01 — Exactly-Once Hosted Chat Transport Design

Date: 2026-09-08
Repository: `m-indsRefuge/Byte-MCP`
Design branch: `feat/nvidia-provider-n01-transport`
Qualified predecessor: `48c076512f233127ab119c522d9f4cd620587078` (NVIDIA-00)
Status: APPROVED ARCHITECTURE — DESIGN SPECIFICATION AWAITING USER REVIEW

## 1. Purpose

NVIDIA-01 adds the first provider-neutral inference-request and exactly-once HTTP transport implementation to Byte-MCP, with NVIDIA hosted `/v1/chat/completions` as the first consumer.

The phase exists to prove that Byte-MCP can execute one bounded provider request without importing OX-specific machinery, while preserving the strongest reliability lessons learned from OX:

- immutable prepared request identity;
- exact wire-byte binding;
- exactly one provider transmission;
- zero automatic retry;
- zero redirect following;
- zero model/provider fallback;
- bounded component timeouts plus an absolute deadline;
- safe receive-path observation;
- deterministic attempt outcomes;
- provider-specific HTTP/application classification above a provider-neutral transport;
- complete separation between transport completion and protocol/result usability.

NVIDIA-01 is an offline implementation and qualification phase. It performs no live NVIDIA inference and no live NVIDIA catalog request.

## 2. Architectural decision

Byte-MCP will use **Option C** from the approved NVIDIA-01 architecture discussion:

> Build a new provider-neutral request/transport layer alongside OX, with NVIDIA as its first consumer. Keep OX frozen until NVIDIA proves the shared abstraction.

NVIDIA-01 does **not** refactor OX into the shared transport and does **not** build a second bespoke OX-style NVIDIA subsystem.

The resulting conceptual architecture is:

```text
src/byte_mcp/
  providers/
    __init__.py
    models.py          # NVIDIA-00
    outcomes.py        # NVIDIA-00
    registry.py        # NVIDIA-00
    requests.py        # NVIDIA-01
    transport.py       # NVIDIA-01

  nvidia/
    __init__.py
    errors.py          # extended in NVIDIA-01
    settings.py        # extended in NVIDIA-01
    catalog.py         # NVIDIA-00, unchanged except separately justified compatibility repair
    registry.py        # NVIDIA-00, unchanged
    chat.py            # NVIDIA-01

  ox/                  # frozen
  wolfram/             # frozen
  server.py            # unchanged
```

## 3. Scope

NVIDIA-01 implements:

1. deterministic provider request preparation;
2. canonical JSON wire bytes;
3. provider-neutral request hashes;
4. a provider-neutral async exactly-once HTTP POST transport;
5. bounded transport observation;
6. provider-neutral transport failure/outcome mapping;
7. bounded NVIDIA chat request construction;
8. safe NVIDIA HTTP rejection classification;
9. bounded NVIDIA chat response parsing;
10. explicit separation between HTTP/transport outcome and usable-result state;
11. offline tests proving zero retry/fallback and exact byte identity;
12. regression and isolation gates against the qualified NVIDIA-00/OX/Wolfram baseline.

## 4. Non-goals

NVIDIA-01 does **not**:

- perform a live NVIDIA request;
- perform a live `/v1/models` request;
- expose an NVIDIA inference MCP tool;
- create or mutate a durable review/attempt database;
- implement two-phase human approval;
- implement durable provider-start evidence;
- implement a provider job lane or runtime scheduler;
- implement model routing;
- automatically qualify or enable any model;
- add streaming responses;
- add tools/function calling;
- add image or multimodal inputs;
- add embeddings or reranking;
- add response-format/JSON-mode behavior;
- add model-specific reasoning controls;
- add automatic retries, reconnects, request replay, model fallback, or provider fallback;
- change OX execution behavior;
- change Wolfram behavior;
- migrate OX onto the new transport;
- promote or restart the local Byte-MCP runtime;
- add dependencies.

NVIDIA-02 will own durable prepared-request evidence, explicit authorization, provider-start evidence, and the first live Nemotron Lightning canary.

## 5. Frozen isolation boundaries

During NVIDIA-01, the following paths are frozen:

```text
src/byte_mcp/ox/**
src/byte_mcp/wolfram/**
src/byte_mcp/server.py
pyproject.toml
```

`src/byte_mcp/nvidia/catalog.py` and `src/byte_mcp/nvidia/registry.py` are also expected to remain unchanged. If a compatibility change to either NVIDIA-00 file is proven strictly necessary, execution must surface the exact reason before mutation rather than silently broadening scope.

Historical OX evidence is immutable.

No provider-neutral NVIDIA-01 module may import `byte_mcp.ox` or `byte_mcp.nvidia`.

## 6. Provider-neutral prepared request

NVIDIA-01 introduces an immutable `PreparedProviderRequest` in the provider-neutral layer.

Minimum contract:

```text
PreparedProviderRequest
  provider_id: str
  method: str
  target_origin: str
  endpoint_path: str
  model_id: str
  body_bytes: bytes
  payload_sha256: str
  request_sha256: str
```

For NVIDIA-01:

```text
method = "POST"
target_origin = "https://integrate.api.nvidia.com"
endpoint_path = "/v1/chat/completions"
provider_id = "nvidia-api-catalog"
```

The object is frozen/immutable.

Its ordinary `repr` must never include `body_bytes`, message content, system-managed API credentials, or authorization headers. It may expose only bounded metadata such as provider/model/path and hashes.

### 6.1 Target validation

NVIDIA-01 supports `POST` only.

A provider-neutral prepared target must satisfy all of the following:

- method is exactly `POST`;
- target origin uses HTTPS;
- target origin contains scheme + host only, with optional explicit port;
- target origin contains no user info, path, query, or fragment;
- endpoint path begins with `/`;
- endpoint path contains no scheme, authority, query, or fragment;
- provider/model identifiers pass existing NVIDIA-00 validation.

The NVIDIA adapter fixes the exact NVIDIA target and does not accept caller-controlled production origins.

### 6.2 Exact wire-byte rule

The request body is converted to canonical JSON **exactly once** during preparation.

Canonical serialization is defined as UTF-8 JSON with:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

Array ordering is preserved. Object keys are sorted. NaN and Infinity are forbidden.

The resulting `body_bytes` are the exact bytes later transmitted by the transport.

The transport must send the bytes using request content/body semantics. It must not pass the original Python mapping through `httpx`'s `json=` parameter, because that could serialize a representation different from the one that was hashed and authorized.

### 6.3 Request body bound

Canonical request bytes are limited to:

```text
4,000,000 bytes
```

An oversized prepared request fails locally before transport execution and therefore has outcome semantics equivalent to `NOT_SENT` once an attempt exists in NVIDIA-02.

NVIDIA-01 request preparation itself does not create an attempt outcome because it occurs before transmission.

### 6.4 Payload hash

`payload_sha256` is:

```text
SHA256(body_bytes)
```

encoded as lowercase hexadecimal.

### 6.5 Request identity hash

`request_sha256` is derived from a canonical metadata envelope that binds the exact payload to the exact logical destination:

```json
{
  "endpoint_path": "/v1/chat/completions",
  "method": "POST",
  "model_id": "<model-id>",
  "payload_sha256": "<payload-sha256>",
  "provider_id": "nvidia-api-catalog",
  "request_schema": "byte-mcp-provider-request-v1",
  "target_origin": "https://integrate.api.nvidia.com"
}
```

The metadata envelope is canonicalized using the same canonical JSON rule and hashed with SHA-256.

Therefore `request_sha256` changes if any of the following changes:

- provider identity;
- method;
- target origin;
- endpoint path;
- model identity;
- exact body bytes.

The system-managed API key is not part of either hash.

## 7. Transmission context

The shared transport must not decide when durable provider execution began.

It therefore consumes a caller-supplied immutable transmission context:

```text
ProviderTransmissionContext
  provider_started_at: str
  expected_request_sha256: str
```

`provider_started_at` must be timezone-aware ISO-8601.

`expected_request_sha256` must be a lowercase SHA-256 hex digest and must exactly match the `PreparedProviderRequest.request_sha256` supplied to execution.

The transport may defensively validate these values, but it does not create durable evidence for them.

This is intentional. NVIDIA-02 must be able to perform:

```text
prepare request
  -> persist immutable request identity
  -> obtain explicit human authorization
  -> durably persist provider_started_at + approved request_sha256
  -> immediately call execute_once(...)
```

without changing the NVIDIA-01 transport API.

A request-hash mismatch must fail locally without network transmission. NVIDIA-02 will terminalize such a future attempt as `NOT_SENT`; NVIDIA-01 itself does not persist attempt state.

## 8. Provider-neutral authorization value

Execution credentials remain separate from prepared request identity and durable request evidence.

NVIDIA-01 introduces a small immutable/redacted execution credential wrapper conceptually equivalent to:

```text
ProviderAuthorization
  authorization_header_value: str
```

Rules:

- value is non-empty and bounded;
- CR/LF/control-character injection is rejected;
- ordinary `repr` reveals only that authorization is configured;
- the value is never persisted by transport observation or returned domain objects.

The provider-neutral transport does not accept arbitrary execution-time headers.

It sets only:

```text
Authorization: <ProviderAuthorization value>
Content-Type: application/json
Accept: application/json
```

This prevents un-hashed caller-controlled headers from silently changing request semantics after `request_sha256` has been frozen.

NVIDIA constructs the value as:

```text
Bearer <NVIDIA_API_KEY>
```

## 9. Timeout policy

NVIDIA-01 introduces a provider-neutral immutable `ProviderTimeoutPolicy`.

Production NVIDIA defaults are:

```text
connect_seconds: 10
write_seconds: 30
read_seconds: 300
pool_seconds: 10
absolute_deadline_seconds: 300
```

All timeout values must be finite positive numbers with a hard maximum of 600 seconds.

The generic contract may accept sub-second positive values so deterministic tests can exercise absolute-deadline behavior without slow tests.

`NvidiaHostedSettings.load()` gains these exact bounded environment settings:

```text
BYTE_MCP_NVIDIA_CHAT_CONNECT_TIMEOUT_SECONDS
  default 10, allowed 1..60

BYTE_MCP_NVIDIA_CHAT_WRITE_TIMEOUT_SECONDS
  default 30, allowed 1..120

BYTE_MCP_NVIDIA_CHAT_READ_TIMEOUT_SECONDS
  default 300, allowed 1..600

BYTE_MCP_NVIDIA_CHAT_POOL_TIMEOUT_SECONDS
  default 10, allowed 1..60

BYTE_MCP_NVIDIA_CHAT_ABSOLUTE_DEADLINE_SECONDS
  default 300, allowed 1..600
```

The resulting production values are converted into `ProviderTimeoutPolicy` before provider start.

The absolute deadline wraps the complete provider operation and is authoritative even if an individual component timeout is longer.

No timeout path grants retry authority.

## 10. Provider-neutral transport observation

NVIDIA-01 introduces an immutable bounded `ProviderTransportObservation` containing only metadata:

```text
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
```

It must never retain:

- response body bytes;
- request body bytes;
- authorization headers;
- arbitrary request headers;
- arbitrary response headers;
- exception strings;
- provider prose.

`decoded_body_bytes_received` counts decoded bytes yielded by `httpx`, consistent with the existing OX receive-path convention.

## 11. Exactly-once provider-neutral HTTP transport

The shared transport exposes one async execution operation conceptually equivalent to:

```text
await execute_once(
  prepared_request,
  transmission_context,
  authorization,
  timeout_policy,
  transport=<optional injected httpx async transport>,
)
```

The operation performs exactly one HTTP request.

Production transport uses `httpx.AsyncClient` with:

```text
follow_redirects = False
trust_env = True
```

`trust_env=True` preserves existing Byte-MCP/OX proxy-environment compatibility. The observation records whether recognized proxy environment variables were present. Proxy values are never persisted.

The transport must not contain a retry loop, retry helper, backoff helper, reconnect helper, alternate target URL, alternate model, or alternate provider.

### 11.1 Pre-transmission local checks

All request construction, JSON serialization, hashing, NVIDIA request validation, timeout construction, and credential loading occur before the future NVIDIA-02 provider-start evidence write.

Immediately before network dispatch, `execute_once` performs only bounded deterministic checks of already-created objects, including the request-hash equality check.

No catalog lookup, model lookup, filesystem access, payload reconstruction, payload reserialization, DNS probe, or auxiliary provider operation is allowed between future durable provider-start evidence and the one HTTP request.

### 11.2 Exact transmission

The transport constructs the URL from the validated `target_origin + endpoint_path` and transmits:

```text
method: POST
Content-Type: application/json
Accept: application/json
Authorization: <redacted execution credential>
body: prepared_request.body_bytes
```

The provider-neutral transport does **not** know the NVIDIA API key as a named setting and never stores the authorization value after execution.

The transport rejects attempts to override the prepared method/URL/body or add arbitrary headers through separate caller arguments.

### 11.3 Response-body bound

The transport buffers at most:

```text
8,000,000 decoded response bytes
```

If consuming the response would exceed this bound before complete response consumption, the local receive operation aborts and the attempt is classified conservatively as:

```text
OUTCOME_UNKNOWN
```

This rule applies regardless of the HTTP status already received. Headers alone are not proof that Byte-MCP received a complete terminal provider response.

No oversized-response path may automatically retry or resend.

## 12. Provider-neutral transport outcomes

NVIDIA-01 uses the NVIDIA-00 `ProviderAttemptOutcome` values unchanged:

```text
NOT_SENT
REJECTED
COMPLETED
OUTCOME_UNKNOWN
```

The transport maps failures as follows.

### 12.1 NOT_SENT

The following are classified as `NOT_SENT` because Byte-MCP has trustworthy local evidence that no provider-capable remote service accepted request bytes:

```text
CONNECT_TIMEOUT
CONNECT_ERROR
POOL_TIMEOUT
```

### 12.2 OUTCOME_UNKNOWN

The following are classified as `OUTCOME_UNKNOWN` because transmission may have occurred and Byte-MCP lacks proof of a complete terminal response:

```text
ABSOLUTE_DEADLINE
READ_TIMEOUT
READ_ERROR
WRITE_TIMEOUT
WRITE_ERROR
REMOTE_PROTOCOL_ERROR
HTTP_TRANSPORT_ERROR
```

A local response-size abort before complete response consumption is also `OUTCOME_UNKNOWN`.

No `OUTCOME_UNKNOWN` path may resend automatically.

### 12.3 Complete HTTP responses

A fully received HTTP response has deterministic transport outcome:

```text
2xx          -> COMPLETED
3xx/4xx/5xx  -> REJECTED
```

`REJECTED` describes transmission/HTTP completion only. It grants no retry permission.

## 13. Provider-neutral transport error

Transport failures surface as a bounded provider-neutral error object containing at least:

```text
attempt_outcome
transport_failure_kind
transport_observation
```

Its string representation contains only bounded enum values/metadata.

It must not retain the original `httpx` exception as `__cause__` or `__context__`, and must not propagate raw exception text.

NVIDIA-specific code must not translate a provider-neutral ambiguous transport error into a deterministic application rejection.

## 14. NVIDIA hosted settings extension

`NvidiaHostedSettings` remains the single hosted NVIDIA credential/configuration object.

Existing rules remain frozen:

- `NVIDIA_API_KEY` is the only hosted credential;
- `NGC_API_KEY` is not a fallback;
- production origin is fixed;
- key is absent from `repr`;
- missing configuration fail-isolates NVIDIA.

NVIDIA-01 adds the five chat timeout values defined in section 9. It does not add an arbitrary production base-URL override.

The production chat target is exactly:

```text
https://integrate.api.nvidia.com/v1/chat/completions
```

## 15. NVIDIA chat request contract

NVIDIA-01 supports one deliberately small non-streaming text-chat request shape.

Minimum typed request input:

```text
model_id
messages
temperature
top_p
max_tokens
```

Wire body:

```json
{
  "max_tokens": 1024,
  "messages": [
    {"content": "...", "role": "user"}
  ],
  "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
  "n": 1,
  "stream": false,
  "temperature": 0.2,
  "top_p": 0.95
}
```

### 15.1 Message roles

NVIDIA-01 text-chat messages allow only:

```text
system
user
assistant
```

Tool messages are excluded because tool calling is out of scope.

Each message must contain exactly:

```text
role: bounded role enum/string
content: str
```

Unknown message fields are rejected before request preparation rather than forwarded.

### 15.2 Numeric bounds

The adapter validates:

```text
0 <= temperature <= 2
0 < top_p <= 1
1 <= max_tokens <= 65536
n == 1
stream == false
```

Booleans are not accepted as numeric values. NaN and Infinity are forbidden.

These are Byte-MCP safety/schema bounds, not claims that every NVIDIA model supports the maximum values.

### 15.3 Excluded NVIDIA/model-specific fields

NVIDIA-01 does not send:

```text
tools
tool_choice
response_format
chat_template_kwargs
reasoning_budget
reasoning effort fields
images/audio/video
seed
stop extensions
provider-specific routing hints
```

Model-specific reasoning controls belong to NVIDIA-03 characterization, not shared transport.

## 16. NVIDIA chat adapter ownership

`byte_mcp.nvidia.chat` owns:

- NVIDIA chat request validation;
- construction of the canonical request mapping;
- creation of `PreparedProviderRequest`;
- NVIDIA `ProviderAuthorization` construction at execution time;
- safe HTTP status classification;
- successful response-envelope parsing;
- bounded `NvidiaChatResult` values.

It does not own:

- durable authorization;
- durable evidence;
- provider lane ownership;
- retries;
- routing;
- qualification state transitions;
- runtime/MCP registration.

## 17. NVIDIA safe HTTP rejection classification

For a fully received non-2xx response, NVIDIA maps status to a bounded chat failure kind:

```text
3xx        REDIRECT_REJECTED
400        REQUEST
401        AUTHENTICATION
403        PERMISSION
404        MODEL_OR_ENDPOINT_UNAVAILABLE
413        REQUEST_TOO_LARGE
422        REQUEST
429        RATE_LIMIT
5xx        PROVIDER_UNAVAILABLE
other 4xx  REQUEST
```

Classification is based on HTTP status and, only where necessary, a bounded allow-listed provider error code field.

Arbitrary provider error prose is never returned or persisted.

A full non-2xx response remains transport outcome `REJECTED` even if the body is malformed or absent. Application classification may fall back to the bounded status-based category.

## 18. Successful response-envelope contract

A 2xx response is transport outcome `COMPLETED` before protocol parsing begins.

The NVIDIA parser requires a bounded OpenAI-compatible object with:

```text
model: string
choices: list containing exactly one choice
choices[0].index: 0
choices[0].message.role: "assistant"
choices[0].message.content: string
choices[0].finish_reason: bounded string or null
id: optional bounded string
usage: optional bounded token counters
```

The returned `model` must equal the prepared request's `model_id` exactly.

Unknown top-level, choice-level, message-level, and usage fields are ignored rather than persisted.

### 18.1 Result bounds

`NvidiaChatResult` retains only:

```text
model_id
content
finish_reason
response_id | None
usage | None
request_sha256
payload_sha256
transport_observation
```

Assistant `content` is bounded indirectly by the 8 MB complete response-body limit. `NvidiaChatResult.__repr__` must not include assistant content; it may expose only bounded metadata such as model, character count, hashes, finish reason, and usage.

The result is provider output data only. It is never interpreted as executable instructions.

The adapter does not persist it automatically.

### 18.2 Bounded scalar fields

If present:

- `finish_reason` must be `null` or a string of at most 64 characters containing only ASCII letters, digits, `.`, `_`, or `-`;
- response `id` must be a string of at most 256 characters with no control characters.

The assistant content may contain arbitrary Unicode text because it is provider output, but it remains bounded by the complete response-body cap.

### 18.3 Usage

If `usage` is present, accepted fields are:

```text
prompt_tokens
completion_tokens
total_tokens
```

Each must be a non-negative integer no greater than `2_147_483_647` if present. Booleans are rejected as integers. Unknown usage fields are discarded.

Missing usage is allowed.

### 18.4 Protocol failure after complete transport

If a fully received 2xx response has malformed JSON, the wrong model, malformed choices, invalid content, or otherwise fails the bounded response contract:

```text
transport outcome: COMPLETED
NVIDIA chat error kind: PROTOCOL
```

NVIDIA-01 does not add a second provider-neutral result-state enum. The distinction is represented by `ProviderAttemptOutcome.COMPLETED` plus the NVIDIA-specific bounded `PROTOCOL` error.

This distinction is frozen.

Protocol failure must never be rewritten as `OUTCOME_UNKNOWN` merely because the provider's complete response was unusable.

Likewise, protocol failure does not authorize an automatic retry.

## 19. NVIDIA chat error contract

NVIDIA application/protocol failures surface through a bounded NVIDIA-specific error carrying at least:

```text
kind
attempt_outcome
transport_observation
request_sha256
```

For complete HTTP rejection:

```text
attempt_outcome = REJECTED
```

For malformed successful response:

```text
attempt_outcome = COMPLETED
kind = PROTOCOL
```

The error must not retain:

- provider response prose;
- raw body bytes;
- system-managed API key;
- authorization headers;
- arbitrary headers;
- raw `httpx` exception text.

## 20. Credential boundary

The system-managed NVIDIA API key is never inserted by Byte-MCP into:

- `PreparedProviderRequest`;
- canonical request body;
- payload hash;
- request identity hash;
- transport observation;
- chat result;
- chat error `repr`/`str`;
- test snapshots;
- durable evidence in future phases.

User-provided message content remains user-controlled data; Byte-MCP does not claim to detect secrets a caller intentionally places inside a prompt.

The NVIDIA adapter adds the Authorization header only at the final execution boundary:

```text
Authorization: Bearer <NVIDIA_API_KEY>
```

Redirect following is disabled, so the bearer credential is never intentionally forwarded to a redirect target.

## 21. Provider-start adjacency preparation

NVIDIA-01 itself does not persist provider-start evidence.

However, its API is designed so NVIDIA-02 can enforce the following adjacency:

```text
durable provider_started_at + approved request_sha256 write
  -> execute_once(prepared_request, matching transmission_context)
  -> exactly one HTTP transmission
```

No catalog call, model lookup, payload reserialization, filesystem scan, or other potentially blocking operation may be required between the future durable provider-start write and `execute_once`.

All validation/preparation that can fail must occur before NVIDIA-02 records provider start, except for bounded defensive object/hash consistency checks that perform no I/O and cannot contact a provider.

This requirement is a design constraint on NVIDIA-01 even though durable evidence arrives in NVIDIA-02.

## 22. Offline testing strategy

All NVIDIA-01 tests are provider-offline.

No real NVIDIA API key is required.

All HTTP tests use injected `httpx` transports or deterministic local async test doubles.

### 22.1 Prepared request tests

Verify:

- canonical JSON is deterministic;
- dict key ordering does not change `body_bytes` or hashes;
- message list ordering does change identity when semantically changed;
- `payload_sha256` hashes exact transmitted bytes;
- `request_sha256` changes when target/provider/model/path/body changes;
- target origin/path validation fails closed;
- system-managed API credential is absent from prepared state;
- `repr` does not expose request content;
- 4 MB request bound is enforced before transport;
- NaN/Infinity and unsupported values fail closed.

### 22.2 Transmission/authorization tests

Verify:

- transmission context requires timezone-aware `provider_started_at`;
- transmission context requires lowercase SHA-256 expected request identity;
- expected hash mismatch fails with zero network calls;
- authorization wrapper is redacted;
- CR/LF/control characters in authorization are rejected;
- no arbitrary caller headers can be added at execution.

### 22.3 Transport tests

Verify:

- exactly one POST maximum;
- exact prepared `body_bytes` reach the injected transport;
- zero `json=` reserialization;
- redirects are not followed;
- no retry after HTTP 429/5xx;
- no retry after transport failure;
- no alternate provider/model/origin;
- connect timeout/error/pool timeout -> `NOT_SENT`;
- write/read/protocol/absolute-deadline failures -> `OUTCOME_UNKNOWN`;
- full 2xx -> `COMPLETED`;
- full 3xx/4xx/5xx -> `REJECTED`;
- response observation contains metadata only;
- every response-size overflow before complete consumption -> `OUTCOME_UNKNOWN`;
- proxy presence is recorded as boolean only;
- provider-start timestamp is preserved from caller context;
- raw exceptions do not survive in exception cause/context.

### 22.4 NVIDIA request tests

Verify:

- exact NVIDIA origin/path;
- only `NVIDIA_API_KEY` is used;
- five production timeout settings have the exact defaults/bounds in section 9;
- supported roles only;
- unknown message fields rejected;
- numeric bounds enforced;
- `n=1` and `stream=false` fixed;
- unsupported tools/reasoning/multimodal fields cannot enter the request;
- Nemotron Lightning can be represented without model-specific transport branching;
- preparation performs zero provider calls.

### 22.5 NVIDIA response/error tests

Verify:

- status classification table;
- provider prose discarded;
- exact returned model match;
- one assistant choice/index 0;
- bounded content/finish/id/usage parsing;
- unknown fields discarded;
- result `repr` does not expose assistant content;
- malformed 2xx -> `COMPLETED` + NVIDIA `PROTOCOL` error;
- non-2xx complete response -> `REJECTED`;
- raw body/headers/key absent from returned errors/results except the explicitly returned assistant content field.

### 22.6 Security/isolation tests

Verify:

- provider-neutral modules import no NVIDIA/OX/Wolfram package;
- NVIDIA transport code imports no OX/Wolfram package;
- no NVIDIA inference MCP tool exists;
- OX/Wolfram/server/dependencies remain unchanged;
- no live provider network route is exercised by tests;
- no retry/fallback helper exists in the NVIDIA-01 execution path.

## 23. Quality gates

NVIDIA-01 uses the baseline-aware quality policy established during NVIDIA-00.

Required:

1. all NVIDIA-01-created/modified Python files pass `ruff format --check`;
2. NVIDIA-01 introduces zero new Ruff formatting violations;
3. `python -m ruff check .` passes;
4. the full Python test suite passes;
5. Python compilation passes;
6. GitHub Actions CI passes on both Windows and Linux for the final pushed commit;
7. Windows launcher tests continue to pass;
8. frozen paths remain unchanged.

Repository-wide historical Ruff formatting debt that is byte-for-byte unchanged from the qualified NVIDIA-00 predecessor is not repaired as part of NVIDIA-01 and does not block qualification.

The repository-wide `ruff format --check .` result may remain non-zero only when every remaining failure is proven to predate NVIDIA-01 and lies outside the NVIDIA-01 changed-file set.

## 24. Provider call boundary

During NVIDIA-01 design, implementation, and qualification:

```text
NVIDIA live catalog calls: 0
NVIDIA live inference calls: 0
OX provider calls: 0
Wolfram provider calls: 0
other external model/provider calls: 0
automatic retries: 0
fallbacks: 0
```

The first live `/v1/chat/completions` request belongs to NVIDIA-02 and requires a separate explicit authorization tied to an immutable prepared request identity.

## 25. Expected implementation file boundary

The implementation plan should preferentially limit production changes to:

```text
src/byte_mcp/providers/__init__.py
src/byte_mcp/providers/requests.py
src/byte_mcp/providers/transport.py
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/errors.py
src/byte_mcp/nvidia/settings.py
src/byte_mcp/nvidia/chat.py
```

Expected new tests:

```text
tests/providers/test_requests.py
tests/providers/test_transport.py
tests/nvidia/test_chat_request.py
tests/nvidia/test_chat_transport.py
tests/nvidia/test_chat_response.py
tests/nvidia/test_n01_security_invariants.py
```

The implementation plan may refine test filenames while preserving responsibility boundaries.

No NVIDIA-01 task should require production edits outside this boundary unless a separately surfaced compatibility blocker proves otherwise.

## 26. Acceptance criteria

NVIDIA-01 is qualified only when all of the following are evidenced:

1. `PreparedProviderRequest` binds exact canonical wire bytes to provider/target/model identity.
2. The transport sends the exact prepared bytes without JSON reserialization.
3. Exactly one POST is possible per execution invocation.
4. No automatic retry, reconnect, model fallback, provider fallback, arbitrary header override, or redirect following exists.
5. `ProviderTransmissionContext` binds provider start to the expected request hash.
6. Execution authorization is ephemeral/redacted and excluded from request identity/evidence.
7. Provider-neutral timeout and transport observation contracts are implemented and tested.
8. Transport failures map conservatively to `NOT_SENT` or `OUTCOME_UNKNOWN` according to this spec.
9. Every response-size abort before complete consumption is `OUTCOME_UNKNOWN`.
10. Fully received HTTP responses map deterministically to `COMPLETED` or `REJECTED`.
11. NVIDIA safely classifies complete HTTP rejections without propagating provider prose.
12. NVIDIA parses a bounded non-streaming OpenAI-compatible chat response.
13. A malformed complete 2xx response remains transport `COMPLETED` with NVIDIA `PROTOCOL` error.
14. System-managed API keys and authorization headers never enter prepared request identity, observations, results, or errors.
15. Request/response byte bounds are enforced.
16. NVIDIA chat remains text-only, non-streaming, single-choice, no-tools, no-reasoning-dialect infrastructure.
17. NVIDIA-00 model/registry/catalog contracts remain intact.
18. No NVIDIA inference MCP tool exists.
19. OX, Wolfram, server wiring, dependencies, and historical evidence remain unchanged.
20. All tests and lint/compile gates pass.
21. NVIDIA-01 changed-scope formatting passes with zero new formatting regressions.
22. Final pushed commit passes GitHub CI on Windows and Linux.
23. Zero live provider requests occur during NVIDIA-01.
24. NVIDIA-02 can persist provider start/request identity and invoke the transport immediately without payload reconstruction, catalog/model discovery, or arbitrary header mutation.

## 27. Phase transition to NVIDIA-02

After NVIDIA-01 qualification, NVIDIA-02 will design and implement the smallest durable canary path around one candidate model, initially Nemotron 3.5 Lightning.

NVIDIA-02 will add:

```text
immutable prepared canary identity
  -> durable preparation evidence
  -> explicit human approval
  -> durable provider-start evidence
  -> exactly one NVIDIA-01 transport call
  -> durable terminal evidence
```

NVIDIA-02 will not change the NVIDIA-01 exactly-once transport contract merely to accommodate the canary.

If the live request has an ambiguous transmission outcome, the attempt ends `OUTCOME_UNKNOWN` and no automatic resend occurs.

## 28. Frozen design decision

The NVIDIA-01 transport is the first implementation of a provider-neutral Byte-MCP execution substrate.

It is deliberately proven with NVIDIA before OX migration is considered.

The final ownership boundary is:

```text
provider request layer owns:
  canonical wire bytes
  payload hash
  request identity hash
  target identity

provider transport owns:
  exactly-one HTTP transmission
  execution request-hash binding
  ephemeral authorization handling
  bounded timeouts/deadline
  receive observations
  provider-neutral transport outcome
  zero retry/fallback

NVIDIA adapter owns:
  NVIDIA credential
  exact NVIDIA hosted origin
  NVIDIA chat request schema
  NVIDIA HTTP/application classification
  NVIDIA chat response parsing

future NVIDIA-02 evidence layer owns:
  prepared attempt identity
  explicit authorization state
  durable provider-start evidence
  durable terminal evidence

routing layer owns later:
  which QUALIFIED and ENABLED model is selected for which role
```

OX remains frozen until NVIDIA proves this architecture through NVIDIA-01 and the first governed NVIDIA-02 canary.