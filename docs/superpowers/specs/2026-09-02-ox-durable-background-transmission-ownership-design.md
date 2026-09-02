# Q03H — Durable Background OX Transmission Ownership

Date: 2026-09-02
Status: Frozen design
Repository: Byte-MCP
Subsystem: OX validation
Base checkpoint: `e953b1eb3bb4893a98b6cf6fdfe9961873c708b7`

## 1. Authority and scope

This document records the approved Q03H architecture from the current execution directive. It does not replace or reinterpret that directive. Where repository facts conflict with this design, implementation stops and returns the exact conflict for Nolan's decision rather than inventing another design.

Q03H changes the ownership of long-running OX provider work. It removes provider execution from an individual MCP request's lifetime and makes the Byte-MCP daemon runtime session the in-process owner after durable claim and accepted launch.

Q03H is a safety, concurrency, durability, and evidence-integrity change. Exactly-once provider transmission, immutable evidence, explicit human authorization, and truthful ambiguity handling take precedence over convenience, throughput, and implementation speed.

## 2. Established Q03G baseline

At the approved base:

- `server.ox_review(...)`, provider-bearing continuation modes, and provider-bearing revalidation modes offload synchronous service calls with `asyncio.to_thread(...)`.
- Initial natural review uses `json_mode=False`.
- Natural OX review text is authoritative.
- The raw provider response is canonical evidence and is persisted before higher-level natural-text usability checks.
- Byte-derived structured findings are a separate local immutable operation.
- No findings record is distinct from an explicitly recorded empty findings set.
- Replay during `TRANSMITTING` returns local evidence and performs no additional provider request.
- Replay after `REVIEWED` returns local evidence and performs no provider request.
- `FAILED` and `OUTCOME_UNKNOWN` require an explicit retry mode and renewed human approval.
- No automatic retry exists.
- The provider request has a 900-second absolute deadline.
- Wolfram V1.1 is a separate capability and remains unchanged.

`OX-000010` proved provider-free that Q03G replay safety prevents a second request while an attempt is `TRANSMITTING`, but also exposed that cancellation of the outer MCP coroutine does not reliably own the lifetime of a worker started through `asyncio.to_thread(...)`. Q03H fixes ownership rather than extending MCP timeouts or shielding the same coupling.

## 3. Goals

Q03H will:

1. Return provider-bearing MCP operations promptly after a durable attempt is claimed and a background launch is accepted.
2. Give one daemon runtime session sole in-process ownership of each accepted provider job until terminalization.
3. Provide one shared provider lane across all OX review, continuation, retry, and revalidation transmissions.
4. Prevent a different operation from claiming an attempt while the lane is occupied.
5. Make same-operation replay return bounded local launch evidence without another attempt, worker, or provider call.
6. Persist runtime ownership with every new Q03H attempt.
7. Persist a single append-only `PROVIDER_REQUEST_STARTED` event immediately before the one external request boundary.
8. Retain an authoritative `AttemptOutcome` and bounded safe transport diagnostics.
9. Recover unfinished work owned by an earlier runtime to `OUTCOME_UNKNOWN` locally and without transmission.
10. Preserve natural OX response authority, Byte-derived findings provenance, explicit approval, historical evidence, provider-free retrieval, and Wolfram isolation.

## 4. Non-goals and forbidden substitutions

Q03H does not:

- add a queue, database-backed worker system, Redis, scheduler, or multiple provider lanes;
- add automatic polling or provider-status reconciliation;
- retry because a caller disappeared, a worker failed, a daemon restarted, a transport result is unknown, or a replay occurred;
- solve cancellation by increasing MCP timeouts or wrapping `asyncio.to_thread(...)` in `asyncio.shield(...)`;
- create unowned fire-and-forget tasks;
- let a background worker re-enter a public transmission method that can allocate another attempt;
- reuse a historical attempt ID;
- convert natural OX review or revalidation to provider-side findings JSON;
- heuristically parse natural Markdown into canonical findings;
- make a second provider call to structure findings;
- add public MCP tools or broaden existing tool argument schemas;
- modify historical OX evidence;
- modify Wolfram source, schemas, routing, or provider behavior;
- modify runtime deployment, daemon ownership, Scheduled Tasks, or production configuration;
- authorize merge, push, promotion, deployment, restart, or a live canary.

## 5. Immutable historical evidence

The following attempts remain historical evidence and must never be retried or mutated:

- `OX-000007-A001` — immutable `OUTCOME_UNKNOWN`.
- `OX-000008-A001` — immutable `OUTCOME_UNKNOWN`.
- `OX-000009-A001` — immutable `COMPLETED`; no A002 may be created.
- `OX-000010-A001` — immutable `OUTCOME_UNKNOWN`; no retry or A002 is allowed without a future fresh explicit Nolan approval.

Q03H must read evidence produced before runtime ownership, provider-start, and transport metadata fields existed. No migration or retrofit of historical immutable evidence is permitted. The provider-free Q03G historical acceptance script remains a required gate.

## 6. Runtime-owned single provider lane

The Byte-MCP OX runtime creates one focused in-process job manager for its daemon lifetime. The preferred module is `src/byte_mcp/ox/jobs.py`.

The manager:

- owns one unique `runtime_session_id` for the daemon lifetime;
- exposes one active provider lane shared by every provider-bearing OX operation;
- reserves that lane before a conflicting durable attempt can be claimed;
- accepts only an already-claimed immutable launch descriptor;
- prevents duplicate submission of an attempt;
- runs accepted provider work independently of MCP, browser, or tunnel cancellation;
- releases the lane exactly once after terminalization;
- exposes only bounded local reservation, launch, and replay state;
- is not durable state and never supersedes evidence after restart.

The runtime session identifier must be local, bounded, non-secret, safe to persist, and collision-resistant. It must not derive from an API key, credential, provider token, machine secret, or user identifier.

There is no queue. A different operation presented while the lane is reserved or active is rejected locally before transmission intent or attempt allocation. That rejection makes no provider request and leaves the prepared operation eligible. A same-operation replay after durable launch acceptance returns or reconstructs the active launch receipt and does not create another worker, attempt, or provider request.

Short-lived reservation of the lane is distinct from accepted provider work. If validation or durable claim fails before acceptance, the reservation is released and the original evidence error remains authoritative. If thread submission fails after claim but before provider-boundary entry, the attempt is terminalized `NOT_SENT`, no provider call occurs, the lane is released once, and any future resend still requires the existing explicit retry controls.

## 7. The seven provider-bearing paths

All seven paths use the same job manager, runtime session, provider lane, durable ownership model, and one-request worker boundary.

| Path | Existing service entry point | Required authorization and identity | Natural provider mode |
|---|---|---|---|
| 1. Initial review approval | `transmit_review(review_id)` | Existing approved `PREPARED` scope | `json_mode=False` |
| 2. Initial-review retry | `retry_review(review_id, renewed_approval=True)` | Explicit retry mode and renewed human approval | `json_mode=False` |
| 3. Continuation message | `continue_message(review_id, message)` | Existing reviewed thread plus exact new user message | `json_mode=False` |
| 4. Continuation retry | `retry_continuation(review_id, attempt_id, renewed_approval=True)` | Latest failed continuation attempt ID and renewed human approval | `json_mode=False` |
| 5. Blind revalidation approval | `transmit_blind_revalidation(revalidation_id)` | Existing approved prepared revalidation | `json_mode=False` |
| 6. Revalidation retry | `retry_revalidation(revalidation_id, renewed_approval=True)` | Explicit retry mode, prior phase, and renewed human approval | `json_mode=False` |
| 7. Targeted revalidation | `run_targeted_revalidation(revalidation_id, finding_ids)` | Valid blind result and exact Byte-derived findings/adjudication provenance | `json_mode=False` |

Local-only operations remain synchronous and provider-free:

- review preparation;
- revalidation preparation;
- findings recording;
- adjudication;
- `ox_get_review` and every evidence-retrieval view.

Shared interfaces are implemented sequentially. Initial review and retry are completed and reviewed before continuation work; continuation is completed and reviewed before revalidation work; retrieval and qualification follow all transmission paths.

## 8. Claim and worker separation

Provider-bearing flows are split into a local claim stage and a worker stage.

The local stage:

1. validates or rebuilds the exact approved scope;
2. derives a bounded operation identity without retaining secret or unbounded content in manager state;
3. reserves the shared provider lane before a conflicting attempt can be claimed;
4. claims exactly one attempt atomically;
5. persists transmission intent and runtime-session ownership together;
6. persists immutable attempt identity and exact history binding;
7. persists required system or user thread content exactly once;
8. creates an internal immutable launch descriptor;
9. submits that descriptor to the manager;
10. returns a bounded launch receipt after acceptance.

The worker stage:

1. receives an already-claimed descriptor and cannot allocate an attempt;
2. writes `PROVIDER_REQUEST_STARTED` immediately before the external request call;
3. makes exactly one provider request with `json_mode=False`;
4. persists the raw successful provider response before natural-text usability checks;
5. appends the natural assistant response to the correct thread;
6. records the terminal authoritative outcome;
7. finalizes bounded safe transport timing and classification metadata;
8. audits the terminal result without secrets or arbitrary exception text;
9. releases the provider lane exactly once.

The worker must not call any of these allocation-capable public methods:

- `transmit_review(...)`;
- `retry_review(...)`;
- `continue_message(...)`;
- `retry_continuation(...)`;
- `transmit_blind_revalidation(...)`;
- `retry_revalidation(...)`;
- `run_targeted_revalidation(...)`.

An unexpected worker exception must be converted to truthful bounded terminal evidence. If provider-boundary status is ambiguous, the outcome is `OUTCOME_UNKNOWN`. Failure to persist terminal evidence fails the lane closed for that runtime rather than allowing another provider launch to overtake an unresolved transmitting attempt.

## 9. Launch receipt contract

An accepted initial launch reports logically:

```json
{
  "review_id": "OX-000012",
  "attempt_id": "OX-000012-A001",
  "state": "TRANSMITTING",
  "launch_accepted": true,
  "replayed": false,
  "provider_request_performed": false
}
```

The worker being scheduled does not prove that the request boundary was entered. Therefore `provider_request_performed` remains `false` in launch receipts.

A same-operation replay while active reports logically:

```json
{
  "review_id": "OX-000012",
  "attempt_id": "OX-000012-A001",
  "state": "TRANSMITTING",
  "launch_accepted": false,
  "replayed": true,
  "provider_request_performed": false
}
```

Continuation and revalidation launch receipts carry the same bounded flags plus their existing review, revalidation, attempt, and phase identity. Existing useful response fields are preserved additively where truthful. A launch receipt never fabricates the eventual natural response; completed content is read through `ox_get_review`.

Ordinary initial approval after `REVIEWED` retains Q03G local replay behavior: zero provider calls, no new attempt, and the existing natural review reconstructed from immutable evidence.

## 10. Durable ownership and event model

Every new Q03H transmission intent atomically includes:

- attempt ID;
- manifest digest;
- owning `runtime_session_id`;
- recorded timestamp;
- phase where required.

The immutable attempt identity also records the runtime session and exact history digest. Persisting ownership in the intent event closes the crash window that would otherwise exist between attempt allocation and writing the separate identity file.

Immediately before calling `OXClient.complete(...)`, the worker appends exactly one event whose logical and persisted event type is:

`PROVIDER_REQUEST_STARTED`

The event contains only bounded safe fields:

- attempt ID;
- owning runtime session ID;
- recorded timestamp;
- phase or operation type needed to disambiguate continuation and revalidation.

This event proves only that Byte-MCP entered the provider request boundary. It does not prove the provider received, processed, or completed the request. `AttemptOutcome` remains the authoritative safety result.

Reconstruction validates ordering, current-attempt identity, runtime ownership, phase, and uniqueness. A duplicate provider-start event or transport metadata event is malformed evidence, not a second authority.

## 11. Success ordering

For a successful initial natural review, the required order is:

1. rebuild and verify approved scope;
2. reserve the provider lane;
3. persist `TRANSMISSION_INTENT`;
4. persist attempt identity including runtime ownership;
5. persist system and user thread messages;
6. accept the background launch;
7. permit the MCP launch receipt to return;
8. append `PROVIDER_REQUEST_STARTED`;
9. make exactly one provider request;
10. persist the raw provider response;
11. validate natural assistant content as usable;
12. append the assistant thread message;
13. record `ATTEMPT_OUTCOME=COMPLETED`;
14. finalize audit and safe diagnostic metadata;
15. release the provider lane.

Continuation and revalidation use the analogous sequence while preserving their exact existing history and provenance bindings. Failure handling must not reorder evidence so that a crossed or possibly crossed provider boundary appears unsent.

## 12. Transport outcomes and bounded diagnostics

The existing authoritative outcomes remain unchanged. Q03H adds a fixed diagnostic classification, not another outcome state.

The fixed failure-kind allow-list is:

- `ABSOLUTE_DEADLINE`;
- `READ_TIMEOUT`;
- `READ_ERROR`;
- `WRITE_TIMEOUT`;
- `WRITE_ERROR`;
- `REMOTE_PROTOCOL_ERROR`;
- `HTTP_TRANSPORT_ERROR`;
- `CONNECT_TIMEOUT`;
- `CONNECT_ERROR`;
- `POOL_TIMEOUT`.

Required mappings are:

| Failure | Authoritative outcome | Diagnostic kind |
|---|---|---|
| Python `TimeoutError` from the absolute deadline | `OUTCOME_UNKNOWN` | `ABSOLUTE_DEADLINE` |
| `httpx.ConnectTimeout` | `NOT_SENT` | `CONNECT_TIMEOUT` |
| `httpx.ConnectError` | `NOT_SENT` | `CONNECT_ERROR` |
| `httpx.PoolTimeout` | `NOT_SENT` | `POOL_TIMEOUT` |
| `httpx.ReadTimeout` | `OUTCOME_UNKNOWN` | `READ_TIMEOUT` |
| `httpx.ReadError` | `OUTCOME_UNKNOWN` | `READ_ERROR` |
| `httpx.WriteTimeout` | `OUTCOME_UNKNOWN` | `WRITE_TIMEOUT` |
| `httpx.WriteError` | `OUTCOME_UNKNOWN` | `WRITE_ERROR` |
| `httpx.RemoteProtocolError` | `OUTCOME_UNKNOWN` | `REMOTE_PROTOCOL_ERROR` |
| Other `httpx.HTTPError` | `OUTCOME_UNKNOWN` | `HTTP_TRANSPORT_ERROR` |

If Byte-MCP proves the provider boundary was never entered, the terminal outcome is `NOT_SENT`. Any ambiguous local or transport failure is `OUTCOME_UNKNOWN`. Ambiguity must never be downgraded to `NOT_SENT`. Existing safe `REJECTED` and provider-completed protocol mappings remain authoritative.

Safe persisted timing may include provider-started timestamp, provider-finished or provider-failed timestamp, and non-negative elapsed milliseconds. Evidence and retrieval must never persist or expose:

- exception messages or arbitrary exception class names;
- `repr(exc)`;
- stack traces in immutable evidence;
- authorization headers, API keys, or cookies;
- unbounded response or error bodies;
- secret-bearing environment values.

The existing raw provider response remains the only canonical raw provider payload persisted after successful receipt.

## 13. Restart and recovery semantics

An unfinished transmitting attempt belongs only to the runtime session that claimed it.

At startup, after creating the new runtime session ID and before exposing the OX service:

- an unfinished attempt bearing a different runtime session ID becomes `OUTCOME_UNKNOWN` immediately and locally;
- recovery makes zero provider requests, creates zero attempts, and performs zero retries;
- an unfinished attempt bearing the current runtime session ID is not recovered as foreign;
- an old attempt with no runtime session field remains readable and falls back to the existing 1,800-second stale/orphan recovery rule;
- explicit runtime ownership recovery takes precedence over the stale horizon;
- the prior runtime's worker is never silently resumed.

Recovery is append-only and idempotent. It cannot relabel a terminal historical attempt or create a retry.

## 14. Authorization and retry semantics

Q03H changes execution ownership, not authorization.

- Initial and revalidation retry require the existing explicit retry mode and renewed human approval.
- Continuation retry requires the exact latest failed continuation attempt ID and renewed approval.
- No path retries automatically.
- Replay does not constitute approval for another attempt.
- `OUTCOME_UNKNOWN` never authorizes an implicit resend.
- MCP cancellation, worker failure, runtime restart, and transport failure do not authorize a retry.

Preparation, scope rebuilding, manifest validation, credential rejection, evidence-integrity guards, and history/provenance checks continue to fail before provider contact.

## 15. Natural response and Byte-derived evidence

Every natural Q03H provider request uses the existing natural-language mandate and `json_mode=False`. Q03H must not restore `response_format={"type":"json_object"}` on these paths.

The natural provider response remains authoritative. On success, its raw response is persisted before assistant text and completion. Byte-derived structured findings remain a separate local-only immutable operation with explicit provenance. An absent findings artifact remains different from an explicitly recorded empty findings set. Targeted revalidation consumes only validated Byte-derived findings and adjudication provenance; it does not treat local interpretation as verbatim OX output.

## 16. Retrieval, API, and security boundaries

`ox_get_review(..., view="attempts")` remains provider-free and authoritative. Where available, it exposes only bounded fields:

- attempt identity;
- outcome;
- runtime session ID;
- whether the provider boundary was entered;
- fixed transport failure kind;
- safe timing.

Historical attempts lacking Q03H fields remain readable with those optional fields absent. Retrieval never contacts OX and never emits credentials, unsafe exception details, or unbounded transport content.

The four public OX tools remain:

- `ox_review`;
- `ox_continue`;
- `ox_revalidate`;
- `ox_get_review`.

Their argument schemas remain unchanged. Provider-bearing modes return launch receipts instead of waiting for the final provider result. Preparation and local-only modes remain synchronous. Completed natural content is retrieved from local evidence.

## 17. Wolfram and provider boundaries

Wolfram V1.1 remains fully separate. Q03H changes no Wolfram file, schema, routing, quota, client, service, runtime, or provider behavior. All Wolfram qualification is provider-free. No real OX or Wolfram call, real API key, retry of historical OX evidence, daemon control, Scheduled Task change, runtime promotion, deployment, merge, or push is authorized by Q03H implementation or qualification.

## 18. Acceptance criteria

Each identifier has exactly one primary owning test in the implementation plan.

- **Q03H-AC01:** A blocked fake provider worker does not hold the MCP initial-approval response open after durable launch acceptance.
- **Q03H-AC02:** Cancelling the outer MCP task after launch does not terminate runtime ownership or cause a duplicate worker, attempt, or provider call.
- **Q03H-AC03:** While one provider job is active, a different review, continuation, or revalidation launch fails locally with zero new attempts and zero provider calls.
- **Q03H-AC04:** Repeating the same active operation returns its active receipt with zero new attempts, jobs, or provider calls.
- **Q03H-AC05:** Every newly claimed Q03H provider attempt persists its owning runtime session ID.
- **Q03H-AC06:** `PROVIDER_REQUEST_STARTED` is written exactly once immediately before the one external request boundary.
- **Q03H-AC07:** Submission failure before provider-boundary entry terminalizes the claimed attempt `NOT_SENT` and makes no provider call.
- **Q03H-AC08:** A representative ambiguous transport failure records `OUTCOME_UNKNOWN`, a fixed bounded failure kind, and safe timing without arbitrary exception text.
- **Q03H-AC09:** Every currently handled HTTPX transport exception category maps to the correct authoritative outcome and fixed diagnostic kind.
- **Q03H-AC10:** Startup recovers a prior runtime's unfinished transmitting attempt to `OUTCOME_UNKNOWN` with zero provider requests, zero new attempts, and zero retries.
- **Q03H-AC11:** Background initial review makes exactly one provider call with `json_mode=False`, persists raw response before natural assistant thread text, and then records completion.
- **Q03H-AC12:** A renewed-approved initial retry creates exactly one new claimed job and returns promptly; no retry occurs without explicit retry mode and approval.
- **Q03H-AC13:** Continuation launches exactly one background job while preserving history binding, one user message, and natural response semantics.
- **Q03H-AC14:** Continuation retry still requires the latest failed continuation attempt ID and renewed approval and launches only one background attempt.
- **Q03H-AC15:** Blind revalidation launches once, returns promptly, and preserves natural `json_mode=False` behavior.
- **Q03H-AC16:** Explicit renewed-approved revalidation retry launches once and never creates an automatic retry.
- **Q03H-AC17:** Targeted revalidation retains Byte-derived findings provenance and launches exactly one natural background provider request.
- **Q03H-AC18:** Attempts retrieval exposes bounded Q03H metadata without credentials, exception strings, provider calls, or historical-read breakage.
- **Q03H-AC19:** The Q03G historical acceptance script and existing evidence semantics pass without evidence migration.
- **Q03H-AC20:** Existing Wolfram tests and schema checks pass, and no Wolfram code changes.

## 19. Qualification and evidence

Implementation uses deterministic fake clients, `threading.Event`, barriers, and bounded joins. No timing-only sleep assertion may stand in for concurrency ownership. Each behavioral task follows focused RED, minimal implementation, focused GREEN, related regression, lint or syntax validation, self-review, commit, and fresh independent review before the next shared interface changes.

Final provider-free qualification runs, in order:

1. focused Q03H tests;
2. all OX tests;
3. all Wolfram tests;
4. the full Python suite;
5. Ruff and compileall;
6. the Q03G historical evidence acceptance script;
7. repository and launcher checks;
8. Git diff, log, and clean-state checks.

A passing local branch is only locally qualified. Runtime promotion and any live OX canary require fresh explicit Nolan authorization.

## 20. Stop conditions

Implementation stops without improvisation if:

- repository, branch, base, or clean-state identity differs;
- the frozen design conflicts with immutable evidence or a real repository contract;
- historical evidence would need rewriting;
- runtime deployment, daemon restart, Scheduled Task mutation, merge, push, or live provider access becomes necessary;
- a test requires a real OX or Wolfram call or exposure of a credential;
- any provider call occurs unexpectedly;
- an implicit retry path appears;
- deterministic concurrency proof cannot be constructed;
- a required change crosses into an out-of-scope subsystem;
- three distinct repairs fail on the same architectural problem;
- the protected verification reserve is reached before a safe checkpoint.

The stop report records the exact task and step, repository identity, dirty state, evidence, safely completed work, smallest Nolan decision required, and confirmation that no unauthorized provider or deployment action occurred.
