# Q03J-A — OX Transport Diagnostics Design

Date: 2026-09-05

Repository: `m-indsRefuge/Byte-MCP`

Qualified predecessor: `da4034f56ab953cb22ad3eeb2f9f50ee1aa9c843` (Q03I)

Status: APPROVED DESIGN — IMPLEMENTATION NOT YET AUTHORIZED

## 1. Purpose

Q03J-A adds bounded transport-phase observability to the existing OX provider path without changing provider response semantics.

The immediate problem is that historical OX attempts `OX-000010-A001` and `OX-000011-A001` ended in `httpx.RemoteProtocolError` after approximately 341–344.5 seconds, while `OX-000012-A001` completed successfully in 111.60 seconds through the same Vercel AI Gateway → Z.AI → `zai/glm-5.3-flash` route.

The present Q03I client records the aggregate transport failure kind and elapsed time, but a non-streaming `httpx.AsyncClient.post()` buffers the complete response before returning. Therefore a `RemoteProtocolError` can occur before Byte-MCP receives a usable `httpx.Response` object even if HTTP response headers or some body bytes were already received.

Q03J-A instruments the receive path so future attempts can distinguish:

- connection failure before usable response headers;
- headers received but no response body bytes;
- response body started but was interrupted;
- complete HTTP response followed by protocol/payload validation failure;
- ordinary complete provider success.

Q03J-A is diagnostic infrastructure only. It does not claim that streaming SSE is the correct fix and does not change the provider request to streaming.

## 2. Scope

Q03J-A changes only local Byte-MCP transport observation and durable metadata.

The provider request remains:

- endpoint: `https://ai-gateway.vercel.sh/v1/chat/completions`;
- model: `zai/glm-5.3-flash`;
- provider allowlist: Z.AI only;
- JSON request field: `stream=false`;
- reasoning effort: unchanged;
- maximum output-token configuration: unchanged;
- Q03I `ai-reporting-tags`: unchanged;
- one outbound POST per attempt;
- zero automatic retries;
- redirects disabled;
- HTTPX connect/read/write/pool timeouts unchanged;
- 900-second absolute receive deadline unchanged.

The implementation changes how Byte-MCP consumes the non-streaming HTTP response. Byte-MCP will use HTTPX's incremental response interface so it can observe headers and body progress while still requesting a non-streaming provider response.

## 3. Non-goals

Q03J-A does not:

- set `stream=true`;
- implement SSE;
- add reconnect/resume behavior;
- retry a failed HTTP request;
- create A002 automatically;
- introduce provider fallback;
- change provider/model selection;
- change request payload semantics;
- increase timeouts;
- change Q03H shared provider-lane ownership;
- change two-phase approval requirements;
- modify historical OX evidence;
- change supervisor repair policy;
- solve cross-process fencing;
- add arbitrary HTTP or exception logging;
- expose response content, prompts, credentials, repository content, proxy URLs, or environment values through diagnostic metadata;
- prove a Vercel/Z.AI 341–345 second timeout.

Streaming resilience is a separate future Q03J-B design. Supervisor/active-provider lifetime protection is a separate reliability track.

## 4. Frozen safety invariants

Q03J-A must preserve all Q03H/Q03I authority and durability invariants.

1. Exactly one OX provider POST may be dispatched per attempt.
2. No automatic retry, reconnect, resume, fallback, or second dispatch.
3. A002 requires a separately authorized retry under the existing contract.
4. The Q03H shared provider lane remains authoritative across all provider-bearing OX operations.
5. Attempt identity and runtime-session ownership remain unchanged.
6. Q03I reporting tags remain deterministic and derived only from validated attempt identity.
7. `RemoteProtocolError` remains `OUTCOME_UNKNOWN`.
8. Any ambiguous interruption after request transmission remains `OUTCOME_UNKNOWN`.
9. Partial body content never authorizes `COMPLETED`.
10. Partial body content never authorizes retry.
11. The 900-second absolute receive deadline is one wall-clock bound over request send, response-header wait, and complete-body receive.
12. Body activity must not renew or extend that absolute deadline.
13. A successful provider response artifact must still be durably persisted before assistant/result terminalization.
14. Historical evidence is append-only and immutable.
15. Evidence-finalization failure remains fail-closed and must never trigger provider resend.

## 5. Current transport lifecycle

The current provider lifecycle is conceptually:

```text
claim attempt
  → persist attempt/input identity
  → submit background worker
  → record PROVIDER_REQUEST_STARTED
  → OXClient.complete()
      → one httpx POST
      → wait for complete buffered response
      → status handling
      → JSON parse
      → provider envelope validation
      → ProviderResult
  → persist provider response
  → append assistant/result evidence
  → record terminal outcome
  → audit
```

On transport error, current service behavior is:

```text
provider error
  → record authoritative attempt outcome
  → record PROVIDER_TRANSPORT_METADATA when available
  → audit
```

Q03J-A preserves this outcome-first failure ordering.

## 6. Proposed transport observation object

Introduce one immutable internal value object named `ProviderTransportObservation`.

The exact production type may be a frozen dataclass or equivalent immutable structure, but its schema is fixed as follows:

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

provider_finished_at: str
elapsed_ms: int

transport_failure_kind: OXTransportFailureKind | None

trust_env_enabled: bool
proxy_environment_present: bool
```

### 6.1 Field semantics

`response_headers_received`
: True only after HTTPX has returned a response with parsed HTTP response headers.

`response_headers_at`
: UTC ISO-8601 timestamp captured when response headers become available to Byte-MCP.

`response_headers_elapsed_ms`
: Monotonic elapsed milliseconds from the provider-call start boundary to header availability.

`http_status_code`
: Parsed HTTP status code when headers were received. Null when no usable response headers were obtained.

`response_body_started`
: True after the first decoded response-body byte is yielded by HTTPX.

`first_body_at`
: UTC ISO-8601 timestamp captured at first decoded body data.

`first_body_elapsed_ms`
: Monotonic elapsed milliseconds from provider-call start to first decoded body data.

`last_body_at`
: UTC ISO-8601 timestamp of the most recent decoded body data observed. Null when no body data was observed.

`last_body_elapsed_ms`
: Monotonic elapsed milliseconds from provider-call start to the most recent decoded body data.

`decoded_body_bytes_received`
: Count of response-body bytes delivered by HTTPX to Byte-MCP after HTTP-level decoding. This is explicitly not a TCP/TLS wire-byte count.

`provider_finished_at`
: UTC ISO-8601 timestamp captured when the HTTP receive operation reaches its local terminal point, whether success or failure.

`elapsed_ms`
: Monotonic elapsed milliseconds from provider-call start to the same local terminal point.

`transport_failure_kind`
: Existing bounded `OXTransportFailureKind`, or null when no transport-layer failure occurred.

`trust_env_enabled`
: Boolean describing whether the HTTPX client is operating with environment-derived networking configuration enabled. Q03J-A does not change this setting.

`proxy_environment_present`
: Boolean only. True when relevant proxy environment configuration is present; false otherwise. The environment keys/values and proxy addresses must never be persisted.

### 6.2 Forbidden fields

The observation must not contain:

- exception strings;
- traceback text;
- arbitrary response headers;
- request or response content;
- API keys;
- prompts/messages;
- bundle/repository content;
- proxy URLs/hosts/users/passwords;
- certificate paths;
- arbitrary environment-variable names or values.

A future safe Gateway request-ID field may be added only by separate explicit design approval after the exact returned header is confirmed and allow-listed.

## 7. HTTP receive design

### 7.1 Provider request remains non-streaming

The JSON body continues to send:

```json
{"stream": false}
```

Q03J-A uses incremental HTTP response consumption only for local diagnostics. It does not request token/event streaming from Vercel or Z.AI.

### 7.2 One client, one request, one deadline

Within the existing fresh `httpx.AsyncClient` context:

1. enter the existing 900-second `asyncio.timeout()`;
2. issue exactly one POST request;
3. obtain response headers incrementally;
4. capture bounded header timing/status metadata;
5. consume the complete response body incrementally;
6. update first/last-body timings and decoded byte count;
7. assemble the complete body in bounded memory compatible with the current response-size expectations;
8. close the response before exiting the request/client scope;
9. continue through the existing status/JSON/envelope parsing path.

The implementation must not call any second request API after a failure.

### 7.3 Absolute deadline

The 900-second absolute deadline covers:

```text
request send
→ response-header wait
→ complete response-body receive
```

It is not a per-chunk inactivity deadline and is never reset by body activity.

Existing HTTPX phase-specific timeouts remain unchanged and may fail earlier than the outer absolute deadline.

### 7.4 Body assembly

Q03J-A may assemble the complete non-streaming response body in memory because current `client.post()` already buffers the complete body before returning. The change must therefore not increase the intended response-size envelope beyond current behavior.

The implementation must not persist partial response content in Q03J-A. Only the bounded metadata above is durable on transport interruption. Partial-content durability belongs to Q03J-B's separately approved streaming-evidence contract.

## 8. Provider result and error propagation

### 8.1 Successful HTTP + valid provider payload

On complete valid success:

- return the existing `ProviderResult` semantics;
- carry the `ProviderTransportObservation` alongside the result through an internal API that does not change the public MCP schema;
- preserve the existing provider-response JSON artifact as authoritative response content evidence.

The observation is diagnostic metadata only.

### 8.2 Transport failure

On transport failure:

- preserve the existing `OXTransportError` class and `attempt_outcome` classification;
- attach the bounded `ProviderTransportObservation` to the transport error or otherwise make it available to the service through an equally narrow internal mechanism;
- do not add free-form provider/error text;
- record the authoritative outcome first;
- append bounded transport metadata second;
- audit third;
- stop without retry.

`RemoteProtocolError` remains:

```text
OUTCOME_UNKNOWN / REMOTE_PROTOCOL_ERROR
```

### 8.3 Complete HTTP response with protocol/payload failure

A full HTTP exchange may complete successfully while the returned payload is unusable.

Examples:

- malformed JSON;
- non-object JSON;
- invalid provider envelope;
- invalid assistant message shape.

Q03J-A must preserve the existing protocol-error outcome semantics while also preserving transport observation showing that the HTTP transport completed.

Example diagnostic state:

```text
response_headers_received = true
response_body_started = true
decoded_body_bytes_received > 0
transport_failure_kind = null
```

This distinction is central to Q03J-A:

```text
transport failed
```

must be distinguishable from:

```text
HTTP transport completed; provider payload was unusable
```

### 8.4 HTTP status errors

A complete HTTP response with status `>=400` continues through the existing HTTP-status classification logic.

The observation may record the bounded status/timing/byte metadata, but it must not alter the current mapping for authentication, permission, quota/rate limit, context/request rejection, or provider-unavailable errors.

## 9. Durable evidence contract

### 9.1 Extend existing metadata event

Q03J-A extends the existing append-only `PROVIDER_TRANSPORT_METADATA` event rather than adding a second parallel transport-event family.

Existing fields remain:

```text
provider_finished_at
elapsed_ms
transport_failure_kind
runtime_session_id
```

Q03J-A adds optional, validated fields corresponding to the observation schema.

### 9.2 Backward compatibility

Historical events remain valid.

For pre-Q03J-A attempts, absence of a new field means:

```text
not recorded by that schema version
```

It must never be interpreted as false, zero, or proof that a phase did not occur.

In particular, historical attempts `OX-000010-A001` and `OX-000011-A001` must not be retroactively assigned `response_headers_received=false` merely because that field did not exist.

No migration or rewrite of historical files is allowed.

### 9.3 Duplicate protection

The evidence store continues to reject duplicate provider transport metadata for the same attempt.

The same additive schema applies to review attempts and revalidation attempts through their existing parallel persistence functions.

### 9.4 Success ordering

For successful attempts, Q03J-A freezes the following required ordering:

```text
complete valid provider response available
→ persist existing provider response artifact
→ perform existing assistant/result processing
→ record authoritative COMPLETED outcome
→ persist provider transport metadata
→ audit
```

If the existing service architecture requires a slightly different placement of assistant/result processing while still preserving the historical response-before-terminal guarantee, the implementation plan must document the exact existing order and tests must prove no regression.

The mandatory invariants are:

- provider response evidence precedes successful terminalization;
- transport metadata does not become the authority for provider success;
- no diagnostic persistence failure may cause resend.

### 9.5 Failure ordering

For provider transport failure:

```text
record authoritative terminal outcome
→ persist provider transport metadata
→ audit
```

This matches the current Q03H/Q03I failure lifecycle.

### 9.6 Evidence-write failure

If required transport-metadata persistence fails during finalization:

- never resend the provider request;
- preserve the existing fail-closed lane/finalization behavior;
- do not synthesize success;
- do not create an additional attempt automatically.

## 10. Outcome matrix

| Condition | Required behavior |
| --- | --- |
| Pre-send configuration/validation failure | Existing `NOT_SENT` behavior |
| Connect/pool failure classified as provably pre-send under existing contract | Existing `NOT_SENT` behavior |
| Request may have left machine; no usable response headers | Existing ambiguity classification; no retry |
| Headers received; zero body bytes; remote interruption | `OUTCOME_UNKNOWN` |
| Headers received; partial body; remote interruption | `OUTCOME_UNKNOWN` |
| Partial body appears syntactically useful | Still `OUTCOME_UNKNOWN` |
| Absolute deadline during any send/receive phase | `OUTCOME_UNKNOWN / ABSOLUTE_DEADLINE` |
| Complete HTTP `>=400` response | Existing HTTP-status mapping |
| Complete HTTP 2xx response, malformed JSON/envelope | Existing protocol-error mapping plus complete transport observation |
| Complete valid provider response | Existing success lifecycle |
| Required evidence finalization fails | Fault closed; never resend |

## 11. Privacy and security

Q03J-A deliberately records metadata rather than payload excerpts.

The following rules are mandatory:

1. Never persist the configured OX API key.
2. Never persist request/response body fragments as diagnostics.
3. Never persist arbitrary exception text.
4. Never persist arbitrary HTTP headers.
5. Never persist proxy/environment values.
6. Never expose diagnostic metadata that contains repository content or prompts.
7. Existing secret-redaction protections for complete provider JSON remain unchanged.
8. All newly persisted fields must be type/bound validated by the evidence layer.
9. Public/bounded `ox_get_review` projections may expose only separately approved safe fields; Q03J-A does not require widening the MCP schema unless the implementation plan explicitly proposes a minimal bounded projection and receives approval.

## 12. Expected implementation scope

Production changes are expected to remain concentrated in:

- `src/byte_mcp/ox/client.py`
- `src/byte_mcp/ox/models.py`
- `src/byte_mcp/errors.py`
- `src/byte_mcp/ox/evidence.py`
- `src/byte_mcp/ox/service.py`
- `src/byte_mcp/ox/natural_service.py` only if needed for successful transport-metadata persistence

Focused tests will be added under `tests/ox/`.

Q03J-A should not require production changes to:

- `jobs.py`;
- supervisor/launcher scripts;
- MCP routing schemas;
- provider selection/settings;
- retry/approval policy;
- historical recovery semantics.

If implementation proves that those areas must change, Q03J-A must stop and be re-reviewed before scope expansion.

## 13. Test-first acceptance contract

Implementation must begin with RED tests and may not claim qualification until the following are covered without paid provider requests.

### 13.1 Real HTTP parser/transport boundaries

Use disposable loopback servers/transports to exercise:

1. connection closes before response headers;
2. valid headers then EOF with zero body;
3. valid headers plus truncated fixed `Content-Length` body;
4. truncated HTTP chunked body;
5. valid headers followed by read timeout;
6. complete HTTP 200 response;
7. complete HTTP response with malformed JSON;
8. complete HTTP response with invalid provider envelope;
9. absolute deadline during a continuous trickle;
10. absolute deadline before any response data.

Tests must assert:

- exact failure/outcome mapping;
- header/body progress fields;
- decoded byte count;
- monotonic timing relationships;
- exactly one outbound request;
- no fallback/retry.

### 13.2 Existing Q03H/Q03I invariants

Tests must prove:

- exact Q03I reporting tag unchanged;
- shared provider-lane contention unchanged;
- active replay creates no new attempt or provider request;
- continuation/revalidation paths preserve one-request semantics;
- explicitly authorized retry paths remain explicit and bounded;
- no A002 is created automatically;
- 900-second absolute deadline remains authoritative.

### 13.3 Evidence behavior

Tests must prove:

- additive metadata validation;
- pre-Q03J-A historical metadata remains readable;
- missing new fields are treated as unknown/not-recorded, not false/zero;
- duplicate metadata remains rejected;
- success response artifact precedes terminal success;
- failure outcome precedes transport metadata;
- required persistence failure never resends;
- review and revalidation metadata contracts remain symmetrical where applicable.

### 13.4 Privacy

Tests must prove diagnostic metadata excludes:

- API key;
- body content;
- arbitrary exception messages;
- proxy URL/value;
- prompt/repository content.

A split or unusual value must not accidentally enter the bounded schema through stringification.

## 14. Qualification gates

Q03J-A local qualification requires, at minimum:

1. focused RED established before production implementation;
2. focused GREEN after implementation;
3. full relevant OX test suite passes;
4. full repository pytest passes on the normal supported environments used by the project;
5. Ruff passes;
6. Python compile gate passes;
7. `pip check` passes;
8. launcher/supervisor qualification remains green if the repository's normal gate includes it;
9. diff scope reviewed against Q03I predecessor;
10. no historical OX evidence mutated;
11. zero OX provider requests during implementation/qualification;
12. zero Wolfram provider requests;
13. no runtime promotion without separate authorization;
14. no merge to main without separate authorization.

A later live diagnostic canary, if desired, requires a fresh two-phase OX approval and exactly one separately authorized provider request. It is not part of Q03J-A implementation authorization.

## 15. Relationship to Q03J-B and supervisor work

Q03J-A is intentionally the first stage of the revised repair roadmap.

```text
Q03I       attribution complete
  ↓
Q03J-A     non-streaming transport diagnostics
  ↓
Q03J-B     separately designed/approved SSE resilience, if still justified
```

A separate reliability track will address supervisor behavior that can terminate an active provider worker when the managed stack is repaired. That problem is real but must not be silently bundled into Q03J-A.

Q03J-B may later introduce an append-only raw SSE transcript plus deterministic reconstructed provider response. None of that artifact contract is implemented by Q03J-A.

## 16. Acceptance criteria

Q03J-A is complete only when all of the following are true:

- the provider request remains `stream=false`;
- exactly one POST is possible per attempt;
- Q03I reporting attribution is unchanged;
- response headers/body progress are observable through bounded typed metadata;
- a pre-header failure is distinguishable from a partial-body failure;
- complete HTTP transport is distinguishable from provider payload/protocol failure;
- 900-second absolute deadline is preserved;
- `RemoteProtocolError` remains `OUTCOME_UNKNOWN`;
- partial content cannot produce success or authorize retry;
- historical evidence remains immutable and backward compatible;
- metadata contains no response/prompt/proxy/credential content;
- initial, continuation, and revalidation provider paths preserve Q03H ownership semantics;
- all required offline tests and repository gates pass;
- implementation required zero OX/Wolfram provider requests.

## 17. Explicitly unresolved questions

No implementation-blocking design questions remain for Q03J-A.

The following external questions remain intentionally unresolved and are not prerequisites for implementation:

- which remote hop caused historical `RemoteProtocolError` failures;
- whether a 341–345 second threshold is repeatable;
- whether Vercel or Z.AI applies a duration/idle policy matching those failures;
- whether SSE will mitigate the failure mode;
- whether any historical failed request produced upstream work after Byte-MCP lost the response.

Q03J-A exists to make future evidence materially better without presupposing those answers.
