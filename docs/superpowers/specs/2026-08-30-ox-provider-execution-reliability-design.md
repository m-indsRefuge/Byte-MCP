# OX Provider Execution Reliability — Design

Date: 2026-08-30
Baseline: `012ea48fbc4924a5aa90cc102c32a5f41c5418ab`
Target branch: `design/ox-provider-execution-reliability`

## Problem

The combined Byte-MCP server and OX preparation boundary are working, but the live OX approval path can leave a review in `OUTCOME_UNKNOWN` while the Web UI surfaces only a later lifecycle error such as `review state does not permit this operation`. That response is safe but operationally ambiguous: it can hide the actual provider/transport outcome and makes it difficult to distinguish a first transmission failure from a duplicate approval invocation.

The current OX implementation already prevents duplicate provider sends by claiming a durable transmission intent before the HTTP request. That protection must remain. The repair is therefore not to weaken the review state machine, but to make outbound execution and duplicate-call handling deterministic and observable.

## Design principle

Use the proven Wolfram execution model as the behavioral reference without modifying Wolfram itself:

- exactly one provider request per authorized attempt;
- no automatic retry;
- explicit bounded outcome classification;
- provider execution separated from higher-level lifecycle logic;
- safe structured diagnostics returned to the MCP caller;
- no provider/transport error may be masked by a later review-state error.

OX retains its stronger approval, manifest, evidence, and retry controls.

## Scope

This subsystem covers:

`OX approval -> durable attempt claim -> provider execution -> terminal outcome -> durable evidence -> MCP result`

Likely production files:

- `src/byte_mcp/ox/client.py`
- `src/byte_mcp/ox/natural_service.py`
- `src/byte_mcp/ox/service.py`
- `src/byte_mcp/ox/evidence.py`
- `src/byte_mcp/ox/models.py`
- `src/byte_mcp/server.py`
- new `src/byte_mcp/ox/execution.py` if the execution boundary warrants its own unit

Tests will live under `tests/ox/` and server contract tests.

## Non-goals

- Do not change any Wolfram implementation or qualification behavior.
- Do not remove OX's two-phase human approval requirement.
- Do not remove immutable manifest or payload binding.
- Do not add automatic retries.
- Do not permit a duplicate approval invocation to create a second provider attempt.
- Do not change OX's provider, model, endpoint, bundle scope, or privacy policy.
- Do not redesign continuation or revalidation beyond changes required to use the same execution result contract safely.

## Architecture

### 1. OX-local provider execution result

Introduce a small OX-local result contract representing one provider attempt. Conceptually:

```text
ProviderAttemptResult
- outcome: NOT_SENT | REJECTED | COMPLETED | OUTCOME_UNKNOWN
- safe_error_type: optional bounded symbolic error class
- response: optional validated ProviderResult
```

The execution unit owns the call to `OXClient.complete()` and converts known provider exceptions into this result instead of allowing transport/provider exceptions to leak across the service boundary.

`safe_error_type` must contain only a bounded class name such as `OXTransportError`, `OXRateLimitError`, or `OXAuthenticationError`. It must never contain credentials, request bodies, provider response bodies, absolute paths, headers, or exception text.

### 2. One attempt, one terminal transition

For a genuinely new approved review:

1. Verify the review is `PREPARED` and rebuild the exact approved bundle.
2. Atomically claim one transmission intent and allocate one attempt ID.
3. Persist the immutable attempt identity and initial thread messages.
4. Execute exactly one provider request.
5. Persist any canonical provider response before higher-level interpretation.
6. Append exactly one terminal attempt outcome.
7. Return a structured MCP result containing the durable outcome.

No hidden retry or second provider call is allowed anywhere in this path.

### 3. Duplicate approval becomes safe observation, not a second send

A repeated `ox_review(review_id=..., approve=true, retry=false)` for a review that already has an initial attempt must never call the provider again.

Instead of surfacing a generic lifecycle exception, the service returns a bounded status packet for the existing attempt, for example:

```text
review_id
attempt_id
state
attempt_outcome
replayed: true
safe_error_type: optional
response_available: bool
```

This is not a retry and does not change evidence. It is an idempotent observation of the already-claimed initial approval operation.

Explicit retry remains a separate action requiring `retry=true` and renewed human approval.

### 4. Known provider failures are structured results

The initial approval MCP call should return a structured terminal result for known provider outcomes instead of relying on FastMCP exception rendering.

Examples:

- connection definitely not established -> `NOT_SENT`
- HTTP rejection such as auth, permission, quota, rate limit, request/context, or provider 5xx -> `REJECTED`
- valid provider response -> `COMPLETED`
- ambiguous write/read/protocol transport failure -> `OUTCOME_UNKNOWN`

Local pre-transmission contract failures still raise normally because no provider attempt has occurred.

### 5. Durable safe error classification

Terminal attempt evidence and audit metadata should include `safe_error_type` for non-completed attempts when available.

The reconstructed review state remains derived from the existing append-only event history. `safe_error_type` is diagnostic metadata and must not alter delivery semantics.

### 6. Success-path evidence ordering

For a successful natural OX response:

1. transmission intent is already durable;
2. raw redacted provider response becomes durable;
3. natural assistant thread message becomes durable;
4. terminal outcome `COMPLETED` becomes durable;
5. MCP result is returned.

Byte-authored findings remain a later, separate local operation and are not part of this repair.

## Error handling

### Pre-provider failures

Manifest mismatch, changed scope, invalid state with no prior initial attempt, credential policy failure, or local evidence failure before the provider call must fail closed and make zero provider requests.

### Provider failures

Known provider errors are converted to `ProviderAttemptResult`, recorded durably once, audited with safe error class, and returned as structured MCP evidence.

### Ambiguous transport

`OUTCOME_UNKNOWN` remains conservative. The system must not infer that the request was not sent and must never retry automatically.

### Duplicate Web UI delivery

If the Web UI/tunnel/MCP layer delivers the same approval more than once, the first invocation owns the only provider attempt. Later invocations observe the durable initial attempt and return its state without allocating another attempt ID.

## Acceptance criteria

### Provider execution

- exactly one HTTP request for one newly approved attempt;
- zero automatic retries;
- each known provider error maps deterministically to the existing attempt outcome taxonomy;
- safe error class is persisted/audited without secret material;
- a valid response still persists raw canonical evidence before the natural assistant message and terminal completion event.

### Duplicate approval

- two concurrent or sequential `approve=true, retry=false` calls create at most one initial provider attempt;
- the second call returns a bounded replay/status result instead of `review state does not permit this operation`;
- no `A002` is created unless an explicit approved retry is requested.

### Retry

- `OUTCOME_UNKNOWN` is never retried implicitly;
- `retry=true` still requires renewed approval and allocates a new attempt;
- retry remains bound to the exact approved manifest/payload.

### Regression

- existing OX preparation, evidence, continuation, findings, and revalidation tests remain green unless deliberately updated to the new structured initial-outcome contract;
- Wolfram tests and behavior are unchanged;
- combined nine-tool server discovery remains unchanged;
- full Python, Ruff, compile, Windows launcher, and Pester gates pass.

## TDD scenarios

At minimum, write failing tests first for:

1. successful initial natural review -> `COMPLETED` and one provider call;
2. connect failure -> structured `NOT_SENT`, one attempt, no second send;
3. HTTP rejection -> structured `REJECTED` with safe error type;
4. read/write ambiguity -> structured `OUTCOME_UNKNOWN` with safe error type;
5. sequential duplicate approval after `OUTCOME_UNKNOWN` -> same A001 returned as replay, zero additional provider calls;
6. concurrent duplicate approval while first is in flight -> one provider call, second returns current durable attempt state;
7. duplicate approval after `COMPLETED` -> replay/status only, no second provider call;
8. explicit renewed retry after `OUTCOME_UNKNOWN` -> A002 and exactly one new provider call;
9. audit/evidence contains safe error class but no secret/request body;
10. Wolfram surface and behavior remain untouched.

## Rollout

Implementation occurs on an isolated branch from the exact accepted baseline/spec head. No live OX retry is used to debug the change. Verification uses mocks and CI first. Only after the full local/CI gate passes will a fresh OX Web UI acceptance review be prepared and explicitly approved.

`OX-000005` remains historical `OUTCOME_UNKNOWN` evidence and will not be reused for the acceptance test.
