# FINAL OX V2 — Clean-room architecture specification

**Status:** Final Milestone-A design, amended after Wave-1 architecture review.

This specification incorporates the supplied repository reconciliation against commit `94ff28810a06b7af2207196ac98c1152cc65b4b1`. It does not claim an independent inspection of that commit. No code or new capabilities are introduced by this document amendment.

The approved 2026-09-12 amendment closes A1–A7 from the Wave-1 review: exact credential exclusion before claim, finish-reason epistemics, process-local `TRANSMITTING`, definitive connect-failure treatment, explicit SEND/GET output semantics, versioned attempt-keyed parse receipts, and SQLite/schema/audit/ref-validation pins. It also records two conscious Milestone-A deferrals: no `REQUEST_STARTED`/`ABORTED_BEFORE_SEND` fact, and no heartbeat probe unless a failed strict lifetime qualification triggers a separately reviewed diagnostic.

## 1. Executive summary

OX V2 consists of three public tools, one transactional evidence store, and one controlled send path:

```
ox_v2_prepare
    Freeze scope, manifest, and exact request bytes
        ↓
Nolan explicitly approves the prepared identity in conversation
        ↓
ox_v2_send(review_id, prepared_sha256)
    Consume the review’s sole send opportunity durably
    Initiate at most one Vercel AI Gateway HTTP request
    Persist streamed response bytes before interpretation
        ↓
COMPLETED | FAILED | OUTCOME_UNKNOWN

ox_v2_get
    Retrieve existing evidence without provider activity
```

The governing guarantee is:

> **Byte-MCP initiates at most one Vercel AI Gateway HTTP request per prepared review.**

Byte-MCP performs zero application retries, redirects, fallback requests, reconnect/resume sends, or resends after restart. The selected provider is hard-allowlisted to Z.AI.

Nolan’s explicit conversational approval is an authorization boundary trusted by this system. Byte must honor it before invoking SEND. V2 does not claim protection against a malicious or authorization-violating assistant.

Synchronous SEND ownership remains conditional on a provider-free qualification of the deployed ChatGPT Web UI → MCP → Byte-MCP invocation lifetime. If that qualification fails, stop for architecture review. Do not implement a fallback ownership mechanism under this specification.

## 2. Problem statement

OX performs paid external review of an explicitly bounded repository snapshot.

V2 must preserve a clear connection between:

1. The prepared repository scope and request.
2. The exact identity Nolan authorized.
3. The immutable request supplied to transport.
4. The response evidence that became durable.
5. The interpretation evidence produced from that durable response.
6. The final outcome, including uncertainty.

Correctness means preventing local duplicate dispatch, preserving evidence, and avoiding unsupported success claims. It does not mean guaranteeing completion after interruption.

The reported historical remote connection failures justify incremental response capture. They do not establish which remote hop failed, and streaming is not a guaranteed remedy.

## 3. Non-goals

V2 initially excludes:

- Guaranteed completion after cancellation or process death.
- Proof of exactly one execution or charge inside Vercel or Z.AI.
- Automatic retry, reconnect, provider polling, or remote result retrieval.
- A retry/A002 workflow.
- Continuation or revalidation.
- Working-tree or uncommitted-content review.
- Automatic scope expansion or truncation.
- Automatic verification of the reviewer’s conclusions.
- Remote failure attribution beyond locally observable transport phase.
- Protection against an authorization-violating assistant, compromised service account, or malicious administrator.
- Migration or runtime reinterpretation of V1 evidence.
- Automatic restart finalization from a durable parse receipt.

Another paid review requires a fresh prepared review and explicit conversational authorization. It does not reopen the original send opportunity.

## 4. Architectural principles

**Freeze before approval.** Prepare and persist the exact request bytes; SEND does not reconstruct them.

**Trust the stated authorization boundary.** Nolan approves the exact identity in conversation; Byte sends only under that authorization.

**Consume before networking.** Commit the unique attempt before invoking transport.

**Preserve uncertainty.** An interrupted attempt never becomes automatically sendable.

**Persist before interpreting.** Received bytes become durable before response parsing or review extraction.

**Version interpretation.** Parser conclusions are immutable, attempt-keyed, and versioned separately from the database schema. A corrected parser may add a new receipt without rewriting an earlier receipt or the canonical response bytes.

**Separate receipt from outcome.** A complete HTTP response or durable parse receipt does not necessarily establish a successful review, a committed final outcome, or a particular upstream billing outcome.

**Use ordinary local transactions.** SQLite supplies atomic attempt creation and durable evidence ordering.

**Add no recovery framework.** Unfinished evidence remains unresolved after restart. Durable parse evidence may support a future separately authorized explicit finalization capability, but V2 Milestone A performs no startup sweep or automatic finalization.

## 5. Proposed module/package structure

```
src/byte_mcp/
    ox/                     # Frozen V1
    ox_v2/
        tools.py            # Three public schemas and authorization contract
        prepare.py          # Scope validation and immutable request assembly
        store.py            # SQLite transactions and retrieval
        send.py             # One request and incremental response receipt
        response.py         # Pure response validation and parse-receipt projection

tests/ox_v2/
```

Use ordinary functions and fixed data structures.

| ComponentRequirement served |                                                       |
| --------------------------- | ----------------------------------------------------- |
| Tools                       | Bounded public surface and exact-identity SEND input  |
| Prepare                     | Frozen repository scope and request identity          |
| Store                       | Replay prevention, durable evidence, and ordering     |
| Send                        | Controlled single-request execution                   |
| Response validation         | Incomplete or invalid responses cannot become success |

`response.py` is a testing boundary, not a service abstraction. It may remain inside `send.py` if small.

V2 must not subclass or import V1 execution services. Shared infrastructure is acceptable only where it does not bring V1 execution behavior, retry logic, logging leakage, or recovery machinery into V2.

## 6. Public MCP/tool contract

Expose exactly:

- `ox_v2_prepare`
- `ox_v2_send`
- `ox_v2_get`

All input schemas reject unknown fields.

### `ox_v2_prepare`

Input:

```
repository_id
subsystem_id
base_ref
target_ref
```

Repository and subsystem identifiers select an operator-maintained allow-list. They do not accept arbitrary filesystem roots.

Initial scope:

> Changes between two exact commits within the selected subsystem, plus context artifacts defined by the fixed preparation policy.

No arbitrary provider options, URLs, headers, scripts, or external artifact references.

Output:

```
review_id
prepared_sha256
repository_id
subsystem_id
base_commit
target_commit
artifact_count
request_byte_count
model_id
state = PREPARED
```

`request_byte_count` is an integer. The actual frozen request bytes remain restricted durable evidence and are not returned in ordinary MCP status output.

### `ox_v2_send`

Input consists only of:

```
review_id
prepared_sha256
```

SEND cannot redefine:

- Repository or subsystem.
- Base or target commits.
- Model or provider.
- Payload.
- Execution settings.

Byte may invoke this tool only after Nolan explicitly approves that exact prepared identity in conversation.

The tool verifies stored identity and consumes the review’s single send opportunity. It does not receive or require an independently verified host approval receipt.

On the original invocation, a `COMPLETED` SEND returns the complete review content derived from the sealed canonical response. That content-delivery result is bounded by the durable response limit, not by the 8 KiB operational-status limit. Non-completed SEND results remain bounded operational/status results.

A repeated call returns existing attempt evidence and never starts or resumes networking. Milestone A does not require replay to reproduce the complete review content after the original invocation has ended.

### `ox_v2_get`

Input:

```
review_id
```

Returns bounded identity, state, receipt facts, parse-receipt facts, safe diagnostics, and references to restricted evidence.

It performs no provider requests, writes, recovery, reconciliation, automatic parsing, or automatic finalization. Request and response bodies are not embedded in ordinary status results.

`docs/OX-V2.md` must document a restricted local inspection query/procedure for operators who need the canonical stored response evidence. A richer GET content-preview surface is explicitly outside Milestone A.

### Initial bounds

These are proposed local product bounds, not asserted provider limits:

| ItemBound                       |                     |
| ------------------------------- | ------------------- |
| Repository/subsystem identifier | 64 ASCII characters |
| Git ref input                   | 256 bytes           |
| Artifacts                       | 200                 |
| Serialized request body         | 2 MiB               |
| Stored response body            | 16 MiB              |
| Response chunk                  | 64 KiB              |
| SSE event                       | 1 MiB               |
| Public status/diagnostic result | 8 KiB               |
| Overall network deadline        | 900 seconds         |

The 8 KiB limit does not apply to the complete review content returned by a successful original SEND invocation. Reject oversized preparation without silently omitting content. Fix the output-token limit in the selected model profile before qualification.

## 7. State machine

Persist attempt existence and final evidence. Do not maintain a separate workflow-state ledger.

| StateMeaning      |                                                                     |
| ----------------- | ------------------------------------------------------------------- |
| `PREPARED`        | Valid prepared evidence exists; no attempt consumed                 |
| `TRANSMITTING`    | The current process is executing its successfully claimed attempt   |
| `COMPLETED`       | Durable, complete, valid successful response                        |
| `FAILED`          | Definitive local failure or durably evidenced unsuccessful response |
| `OUTCOME_UNKNOWN` | Send opportunity consumed; trustworthy final outcome unavailable    |

Durable interpretation:

```
No attempt                    → PREPARED
Attempt with final outcome    → that final outcome
Attempt without final outcome → OUTCOME_UNKNOWN
```

`TRANSMITTING` is not stored as workflow state. It is an optional process-local/public observation while the current live invocation owns a successfully claimed attempt. Live ownership takes presentation precedence over the durable `OUTCOME_UNKNOWN` projection. The ownership registry must be released in `finally`; once ownership disappears, presentation immediately falls back to the durable projection. `TRANSMITTING` does not prove that the provider received the request.

Legal execution:

```
PREPARED → TRANSMITTING → COMPLETED
                       → FAILED
                       → OUTCOME_UNKNOWN
```

Invalid identity or preflight rejection leaves the review `PREPARED`; no attempt was consumed.

An unfinished attempt may receive its first final result from the original live invocation. A persisted final outcome—including `OUTCOME_UNKNOWN`—is immutable.

After restart, unfinished attempts remain unknown. V2 neither resumes them nor writes a reconstructed final outcome, even when a complete response and parse receipt exist.

Illegal transitions include:

- Any transition back to `PREPARED`.
- Replacement of a final outcome.
- Creation of a second attempt for the review.

## 8. Prepare, approval, and send lifecycle

### PREPARE

1. Resolve the allow-listed repository.
2. Validate subsystem boundaries.
3. Resolve base and target to full commit identifiers.
4. Read committed Git objects.
5. Collect deterministic, sorted artifacts under the bounded preparation policy.
6. Construct the complete provider request body.
7. Persist the exact body and manifest in one transaction.
8. Return the approval identity only after commit succeeds.

PREPARE performs zero provider requests and requires no provider credential.

Use Git without external diff tools, text conversion, hooks, network fetching, submodule fetching, or shell interpolation. Missing local objects cause rejection. Unsafe ref input includes `:`, `..`, `@{`, backslash, control characters, empty path components, leading/trailing slash, and trailing dot.

Initially reject unsupported binary artifacts, submodules, and symlink artifacts in the selected review rather than following or silently omitting them. Rename handling must account for both paths at subsystem boundaries.

### Prepared identity

Persist:

```
request_body       Exact serialized UTF-8 bytes
request_sha256     SHA-256(request_body)

manifest           Exact stored bytes containing:
                     schema/preparation-policy version
                     review_id
                     repository/subsystem identity
                     base and target commits
                     scope and artifact inventory
                     artifact digests and lengths
                     fixed endpoint profile and model
                     execution bounds
                     request_sha256 and byte count

prepared_sha256    SHA-256(manifest)
```

Nolan approves:

```
review_id + prepared_sha256
```

One approval digest is sufficient because the manifest binds the exact request digest. A second displayed request digest is optional, not another approval phase.

The approval presentation includes repository, subsystem, commits, artifact count, request size, model, and the fact that interruption may consume the opportunity without producing a result. The inventory and exact request must be available for restricted local inspection.

### Conversational authorization

Nolan’s explicit conversational approval is the trusted authorization boundary.

Byte must:

1. Present the prepared identity.
2. Obtain Nolan’s explicit approval of that identity.
3. Invoke SEND with exactly that identity.

No approval daemon, signing keys, local approval service, PowerShell ceremony, or separate persistent approval workflow is introduced.

The attempt record stores `authorization_mode` and `authorization_asserted_at`. Initial `authorization_mode` is the closed value `EXPLICIT_CONVERSATION`; `authorization_asserted_at` records when Byte-MCP was invoked under that asserted mode. These fields prove only that the invocation asserted this authorization mode. They are not independent proof that Byte-MCP witnessed or cryptographically verified Nolan’s conversational act.

A future native host confirmation facility may strengthen this boundary without changing the V2 state machine.

### SEND

1. Byte confirms conversational authorization for the exact identity.
2. The server validates the input identity.
3. Load and hash-check stored manifest and body.
4. Confirm current policy still permits the repository and fixed endpoint.
5. Load the approved local credential and confirm supported transport settings and credential availability without networking.
6. Encode the exact credential as the bytes that would be used for the authorization header and fail closed if that exact credential occurs in either the frozen request body or frozen manifest. Do not add derivative/pattern secret guessing at this gate. A match leaves the review `PREPARED` and unconsumed.
7. Construct the request using verified stored body bytes.
8. Commit the review’s unique attempt, binding the submitted identity plus authorization assertion fields.
9. Only if that commit returns definite success, register live process ownership and invoke transport once.
10. Commit received bytes incrementally, including `received_at` per chunk.
11. Commit response closure evidence.
12. Parse durable evidence.
13. Commit an immutable versioned parse receipt.
14. Commit the final outcome before reporting it.
15. Release live process ownership in `finally`.

A policy change may deny sending. It must not rewrite the approved request.

## 9. At-most-once boundary

The exact guarantee is:

> **Byte-MCP initiates at most one Vercel AI Gateway HTTP request per prepared review.**

### Local proof

Make `attempt.review_id` a primary key.

The only route to transport requires the current invocation to have inserted that row successfully and received definite commit success.

Therefore:

1. At most one invocation wins the insert.
2. Replays encounter an existing row and return evidence.
3. The winning path invokes transport once.
4. No operation deletes, releases, or resets the attempt.
5. Restart never executes existing attempts.

Thus:

```
Gateway HTTP request initiations per prepared review ≤ 1
```

The count may be zero if the process crashes after consuming the opportunity.

If commit success is uncertain, do not send. A later read finding the attempt row does not grant execution authority.

### Conservative transmission boundary

The attempt commit precedes transport invocation.

After that commit, durable evidence must conservatively allow:

> The request may have been initiated.

This includes the crash gap between commit and networking. There is no local atomic transaction spanning storage and remote HTTP receipt.

A durable record does not prove that every body byte left the process. It binds the exact bytes supplied to the sole transport invocation.

Milestone A deliberately does not add `REQUEST_STARTED` or `ABORTED_BEFORE_SEND`. A process death after claim and before a connect result remains consumed and projects conservatively as unresolved. Observable definitive connect-phase failures are classified more precisely under Section 12 without reopening the send opportunity.

### Required local restrictions

Byte-MCP performs:

- Zero application retries.
- Zero redirects.
- Zero fallback requests.
- Zero reconnect/resume sends.
- Zero resend after restart.

The selected provider is hard-allowlisted to Z.AI.

### External infrastructure boundary

Byte-MCP does not claim to prove exactly one internal upstream provider/model execution inside Vercel or Z.AI.

Undocumented gateway retry behavior is an external infrastructure property. V2 does not compensate for it with additional local machinery, and proof of internal gateway execution count is not a V2 qualification gate.

### Assumptions

The local proof assumes:

- All V2 callers share one authoritative database.
- The database is not rolled back or copied into another active sender.
- Attempt records cannot be deleted through runtime operations.
- The configured transport contains no resend path.
- The assistant honors conversational authorization.

Hashes and uniqueness constraints do not prevent independent credentialed calls or privileged evidence tampering.

## 10. Transport and invocation ownership

Use one direct HTTP client request to the fixed Vercel AI Gateway Chat Completions endpoint with streaming enabled.

Required configuration:

- One POST invocation.
- Stored body supplied as bytes, without reserialization.
- Z.AI as the sole allowed provider.
- No model fallback list.
- No SDK or HTTP transport retries.
- No redirects or authentication-challenge resend.
- No reconnect or stream-resume behavior.
- TLS verification enabled.
- **`trust_env=False`****.**
- No provider tool execution or follow-up generation loop.
- No inherited session cookies or mutable global request hooks.

Use a monotonic 900-second overall network deadline, with proposed connect and write caps of 10 and 30 seconds. Do not add a shorter idle-read timeout merely to reproduce the historical failure window.

### Mandatory provider-free lifetime qualification

Before freezing synchronous SEND ownership, test the deployed:

```
ChatGPT Web UI → MCP → Byte-MCP
```

path for at least the required maximum invocation duration, including the time needed beyond the network deadline for bounded evidence finalization and return.

The qualification must:

- Use no provider requests or credentials.
- Exercise the actual deployed client and MCP path.
- Keep the invocation active for the required duration.
- Record whether completion reaches the caller or the path disconnects/cancels.
- Avoid relying solely on a direct local server test.

**If it passes:** retain synchronous SEND ownership; no background worker.

**If it fails:** stop for architecture review. Record the measured host constraint. That review must specify only the minimum execution-ownership primitive required by the measurement.

The strict qualification is deliberately silent. Do not add heartbeat traffic to the initial probe. If the strict probe fails, a heartbeat/keepalive experiment may be proposed only as a separately reviewed diagnostic during the resulting architecture review; it does not retroactively turn the strict failure into a PASS.

Do not restore V1 background jobs automatically. This specification does not design the fallback mechanism.

### Streaming receipt

For each bounded raw body chunk:

1. Receive bytes.
2. Commit those bytes with a contiguous sequence number and `received_at` timestamp.
3. Continue reading.

Do not parse SSE, decode JSON, assemble review text, or log content before the chunk is committed.

Request identity encoding. Preserve body bytes after HTTP framing removal and before text decoding. This is response-body evidence, not a network packet capture.

At clean HTTP completion:

1. Commit a receipt seal containing durable body length, digest, numeric status, and `http_complete=true`.
2. Parse the stored body using an explicit parser version.
3. Commit the attempt-keyed parse receipt for that parser version.
4. Project protocol validity from the canonical raw evidence plus that receipt.
5. Commit the final outcome.

Successful review completion requires:

- Clean HTTP completion.
- Valid supported SSE framing and JSON events.
- The protocol’s terminal marker.
- A supported successful finish reason.
- No error event, output truncation, or recognized unsupported tool-call/refusal completion.
- A structurally valid review result.

Recognized complete unsuccessful outcomes such as `length`, `content_filter`, `tool_calls`, or refusal are definitive and lead to `FAILED`. An unrecognized finish reason or otherwise complete-but-unsupported feature is not treated as bad news merely because the current parser does not understand it; it produces an `UNSUPPORTED_FEATURE` parse result and `OUTCOME_UNKNOWN`. Malformed/truncated syntax or missing required completion semantics produces an indeterminate parse result and `OUTCOME_UNKNOWN`.

A terminal marker alone does not excuse subsequent receipt failure. Clean EOF alone does not excuse a missing terminal marker.

### Cancellation

Under the qualified synchronous design, execution belongs to the MCP invocation.

Cancellation closes the connection and records `OUTCOME_UNKNOWN` where possible. Permit only bounded evidence cleanup; do not detach the provider operation.

If process death prevents cleanup, the durable attempt still prevents resend.

## 11. Durable evidence model and ordering

Evidence root:

```
%LOCALAPPDATA%\Byte-MCP\ox-v2\
    evidence.sqlite3
```

The database and journals are restricted evidence.

### Tables

| TableContents     |                                                                                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------------- |
| `prepared_review` | Immutable manifest, exact body, digests, creation time                                                         |
| `attempt`         | Unique review key, submitted prepared digest, claim time, authorization assertion, receipt seal, final outcome |
| `response_chunk`  | Review key, contiguous sequence number, raw bytes, `received_at`                                               |
| `parse_receipt`   | Review key + parser version, immutable closed parser result and versioned receipt bytes                         |

`review_id` is also the attempt identifier. One attempt per review requires no additional public attempt ID.

`parse_receipt` has primary key `(review_id, parser_version)`. A parser version may be written at most once for an attempt; later corrected parser versions may add new rows without mutating earlier receipts. The result vocabulary is closed and contains exactly:

```
VALID
INVALID
UNSUPPORTED_FEATURE
INDETERMINATE
```

`VALID` means the parser understood a complete supported successful review. `INVALID` means the parser understood complete evidence that definitively does not represent a successful supported review. `UNSUPPORTED_FEATURE` means complete evidence uses semantics the current parser version does not recognize or support and therefore cannot be safely classified as success or definitive failure. `INDETERMINATE` means available durable evidence lacks trustworthy completion/interpretability. Receipt bytes are restricted, bounded, versioned structured evidence; they contain no arbitrary exception or diagnostic free text.

Schema versioning and parser versioning are separate namespaces. `PRAGMA user_version` versions only the SQLite schema. Parser versions exist only in `parse_receipt` identities and receipt contents.

Every database connection must set and read back the required SQLite configuration before use:

```
PRAGMA foreign_keys=ON
PRAGMA journal_mode=DELETE
PRAGMA synchronous=FULL
PRAGMA busy_timeout=<finite approved milliseconds>
```

Initialization also sets the approved `PRAGMA user_version`. Readback mismatch disables use of that connection. Readers rely on the finite SQLite `busy_timeout` to tolerate a rollback-journal writer; expiry produces a bounded storage-busy failure rather than an unbounded application retry. The supported evidence root must be on a qualified local filesystem.

Enforce:

- Prepared rows are immutable.
- Attempts cannot be deleted.
- Claim identity and authorization assertion fields cannot change.
- Response chunks are append-only.
- Parse receipts are write-once per `(review_id, parser_version)`; multiple parser versions are permitted.
- Receipt and final-outcome fields are written once.
- No chunk append after sealing.
- No successful outcome without a verified complete receipt and `VALID` parse receipt for the parser version used by the original invocation.

Use constraints and narrow triggers where necessary.

### Ordering

```
Prepared evidence committed
    ↓
Unique attempt, submitted identity, and authorization assertion committed
    ↓
Process-local ownership registered
    ↓
Single transport invocation
    ↓
Response chunks committed
    ↓
Receipt seal committed
    ↓
Durable response parsed
    ↓
Versioned parse receipt committed
    ↓
Final outcome committed
    ↓
Process-local ownership released in finally
```

No separate summary/index artifact is required. GET uses primary-key retrieval plus bounded receipt lookup.

### Ambiguous failure

1. Preserve the committed response prefix.
2. If storage remains available, commit an incomplete receipt seal and `OUTCOME_UNKNOWN` where the original invocation can do so safely.
3. Preserve any parse receipt already committed.
4. Never erase partial evidence.
5. Never retry.

If storage fails, the existing attempt still blocks further sending. GET reports unresolved outcome.

Bytes received but not committed are not claimed as durable.

### Integrity limits

Hashes detect mismatches; they do not protect against a privileged actor rewriting content and hashes.

Unsupported storage, corruption, evidence rollback, or required-PRAGMA mismatch disables sending. Runtime must not create a replacement writable database automatically as a repair action.

## 12. Failure taxonomy

| SituationOutcomeReceipt knowledge                                    |                              |                              |
| -------------------------------------------------------------------- | ---------------------------- | ---------------------------- |
| Invalid scope, identity, policy, credential leak, or missing credential before claim | Tool error; no attempt | Not sent |
| No conversational authorization                                      | Byte must not invoke SEND    | No authorized dispatch       |
| Definite local failure after claim, before transport invocation      | `FAILED`                     | Not sent                     |
| Definitive connect-phase failure before any request-body write began | `FAILED`                     | Known not sent by Byte-MCP   |
| Write failure or uncertainty after request-body transmission may have begun | `OUTCOME_UNKNOWN`       | May have been received       |
| Read failure after request initiation                                | `OUTCOME_UNKNOWN`            | May have been received       |
| Complete non-success HTTP response                                   | `FAILED`                     | Complete response received   |
| Complete valid explicit stream error                                 | `FAILED`                     | Explicit unsuccessful result |
| Missing terminator, truncated body, disconnect                       | `OUTCOME_UNKNOWN`            | Incomplete evidence          |
| Complete recognized truncation, refusal, content filter, or unsupported tool-call result | `FAILED`          | Complete but unusable result |
| Complete response with unrecognized finish reason/feature            | `OUTCOME_UNKNOWN`            | Complete; parser unsupported |
| Malformed success body without trustworthy completion semantics      | `OUTCOME_UNKNOWN`            | Review outcome unproven      |
| Complete valid review                                                | `COMPLETED`                  | Complete successful result   |
| Storage failure after transport begins                               | Unknown or unfinalized claim | Evidence incomplete          |
| Unexpected internal exception after transport begins                 | `OUTCOME_UNKNOWN`            | Conservative uncertainty     |

A connect failure is definitive only when the transport layer classifies it in the connect phase (for example DNS/TCP/TLS establishment/connect timeout) and no request-body write began. If phase knowledge is ambiguous, classify conservatively as `OUTCOME_UNKNOWN`. A complete HTTP rejection does not establish whether an upstream charge occurred.

Use fixed categories such as:

```
IDENTITY_MISMATCH
SCOPE_INVALID
POLICY_DENIED
CREDENTIAL_UNAVAILABLE
CREDENTIAL_IN_PAYLOAD
EVIDENCE_INTEGRITY
STORAGE_FAILURE
STORAGE_BUSY
LOCAL_PRE_DISPATCH
CONNECT_FAILURE
WRITE_FAILURE
READ_FAILURE
REMOTE_PROTOCOL
DEADLINE
CANCELLED
HTTP_NON_SUCCESS
STREAM_INCOMPLETE
RESPONSE_INVALID
RESPONSE_UNSUPPORTED
RESPONSE_UNSUCCESSFUL
RESPONSE_LIMIT
INTERNAL_FAILURE
```

Exception types and observed transport phase may select categories. Exception messages are never persisted, and exception type alone does not prove whether transmission occurred.

## 13. Crash/restart semantics

| Crash pointDurable evidenceRestart behavior  |                                 |                                                          |
| -------------------------------------------- | ------------------------------- | -------------------------------------------------------- |
| Before attempt commit                        | Prepared review only            | Prepared; any later SEND requires explicit authorization |
| After claim, before connection               | Attempt without final result    | Unknown; consumed; never send                            |
| After request may have left process          | Attempt, possibly chunks        | Unknown; never send                                      |
| After headers                                | Attempt, possibly status/chunks | Unknown; never send                                      |
| After partial body                           | Committed prefix                | Unknown; preserve prefix                                 |
| After full body, before seal                 | Bytes may appear complete       | Unknown; no automatic inference                          |
| After complete durable receipt, before parse | Sealed complete response        | Unknown final outcome; expose receipt facts              |
| After parse, before parse-receipt commit      | Sealed response                 | Unknown; interpretation was not durable                  |
| After parse-receipt commit, before final outcome commit | Sealed response + versioned interpretation | Interpretation remains durable; final outcome remains unknown; no automatic finalization |
| After final commit, before MCP reply         | Final evidence                  | Replay returns existing final evidence                   |

There is no startup sweep, state repair, automatic parse recovery, attempt release, restart reconciliation, or automatic finalization from a parse receipt.

A complete sealed response or parse receipt without a final outcome remains available for restricted offline inspection. A future explicitly authorized capability may act on that durable evidence, but Milestone A does not.

## 14. Security and privacy constraints

### Authorization trust

Nolan’s conversational approval is trusted. Byte is responsible for honoring it.

The two SEND arguments establish identity, not independently verified human consent. `authorization_mode` and `authorization_asserted_at` record Byte-MCP’s authorization assertion, not host-attested proof. V2 does not claim otherwise.

### Credentials

- Use the existing operator-approved local credential source.
- Load credentials only for SEND.
- Before claim, scan the frozen request body and manifest for an exact match of the credential value that would be used for the authorization header.
- Any exact match fails closed before claim; the prepared review remains unconsumed.
- Do not add heuristic derivative/pattern secret matching to this credential gate.
- Place the credential only in the authorization header.
- Never put credentials in request JSON, manifests, attempt records, logs, diagnostics, or parse receipts.
- Do not fetch credentials through a network operation.
- Disable HTTP debug logging, request dumps, and content tracing.

### Evidence boundary

Restricted evidence contains the approved repository content, raw provider response, and bounded parse-receipt bytes. Ordinary operational metadata does not.

Provider bodies can contain sensitive information. Preserve raw bodies only inside restricted evidence; never copy excerpts into diagnostics.

Repository allow-listing does not prove secret absence. Apply explicit forbidden-file rules and support human inspection of the prepared payload. Do not claim perfect automated secret detection.

### Bounded diagnostics

Persist:

```
claimed_at
authorization_mode
authorization_asserted_at
headers_after_ms       nullable
first_byte_after_ms    nullable
last_byte_after_ms     nullable
elapsed_ms             nullable
http_status            nullable integer
durable_body_bytes
error_category         nullable enum
```

Each response chunk additionally stores `received_at`. Durations use a monotonic clock. Unknown crash-time values remain null.

Do not include:

- Arbitrary exception strings or tracebacks.
- Response or prompt excerpts.
- Arbitrary headers.
- Proxy URLs or hosts.
- Environment values.
- Certificate paths.
- Repository-sensitive content.
- Unbounded provider-generated identifiers.
- Free-text parser diagnostics.

Validation errors must not echo sensitive input values. Logging handlers must not automatically append captured exceptions.

### Filesystem assumptions

Require a private local evidence directory with restricted access to the database and journals. Reject redirection through untrusted reparse points.

The service process, OS account, storage, and assistant’s adherence to authorization form part of the trusted system. V2 does not harden against a malicious actor controlling those components.

Runtime startup must not weaken ACLs or change machine-wide security settings.

## 15. V1/V2 coexistence

- Keep `ox/` frozen.
- Preserve historical V1 evidence separately and read-only.
- Keep V1 retrieval separately named.
- Give V2 its own evidence root and tool registration.
- Do not interpret V1 formats in V2.
- Do not share attempt ownership, provider lanes, recovery hooks, or execution services.
- Never invoke V1 automatically when V2 fails.

Quiesce V1 writers before treating its historical evidence as read-only. A read-only retrieval connection alone does not prevent another process from writing.

## 16. Decommission path

1. Record the V1 implementation checkpoint and evidence inventory.
2. Explicitly quiesce V1 execution and preserve historical evidence read-only.
3. Build V2 alongside V1.
4. Complete provider-free local qualification.
5. Qualify the deployed MCP invocation lifetime.
6. If lifetime qualification passes, retain synchronous ownership. If it fails, stop for architecture review.
7. Promote V2 registration with paid egress disabled and validate the conversational approval procedure.
8. Obtain separate authorization for one bounded live canary.
9. Send that canary once. Failure or ambiguity ends the canary; no automatic repair resend.
10. Review identity binding, credential-exclusion evidence, response durability, parse receipt, final outcome, and available billing evidence.
11. With explicit acceptance, route future new reviews to V2.
12. Retain V1 retrieval.
13. Remove the V1 execution surface later through a separately approved change.

Rollback means disabling V2 execution. It does not automatically reactivate V1.

## 17. Acceptance criteria

Local automated qualification blocks non-loopback networking. Use a controllable loopback HTTP server for transport behavior and forced process termination for crash boundaries.

The deployed MCP lifetime test is separate and provider-free; it exercises the actual host path.

| AreaRequired evidence |                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| PREPARE               | Zero provider requests; succeeds without provider credentials                                                 |
| Scope                 | Exact commits, deterministic inventory, no working-tree dependence, unsupported and oversized inputs rejected |
| Identity              | Material manifest or body mutation prevents dispatch                                                          |
| Frozen bytes          | Captured HTTP body exactly matches the stored approved bytes                                                  |
| Credential exclusion  | Exact configured SEND credential absent from frozen body and manifest; exact-match sentinel is refused before claim |
| Public SEND           | Accepts only `review_id` and `prepared_sha256`; rejects scope and execution overrides                         |
| Approval procedure    | Nolan’s exact-identity approval precedes Byte’s SEND invocation; attempt stores asserted mode/time without claiming host attestation |
| Public output         | Ordinary status/diagnostics stay within 8 KiB; successful original SEND may return complete review content    |
| Single opportunity    | Concurrent threads/processes create at most one attempt and initiate at most one POST                         |
| Replay                | Repeated SEND during and after every outcome never initiates another request                                  |
| Commit uncertainty    | Uncertain claim commit causes zero transport invocations                                                      |
| Live ownership        | `TRANSMITTING` is process-local only, takes presentation precedence while owned, and is released in `finally` |
| Retries               | No application retry after connect, write, read, protocol, status, deadline, or cancellation failure          |
| Connect classification | Definitive connect-phase failure is `FAILED`/known-not-sent; ambiguous/write/read failures are conservative   |
| Redirect/fallback     | Redirects are not followed; no alternate endpoint, model, or provider request                                 |
| Provider selection    | Z.AI is the sole hard-allowlisted provider                                                                    |
| Environment isolation | `trust_env=False`; ambient proxy settings do not alter transport                                              |
| Durability            | Committed chunks survive process termination; success references a matching complete receipt                  |
| Chunk evidence        | Each committed response chunk has contiguous sequence, bytes, and `received_at`                               |
| Parse receipts        | `(review_id, parser_version)` is write-once; multiple versions allowed; result uses the closed enum            |
| Parser epistemics     | Recognized unsuccessful outcomes fail; unknown finish reason/unsupported semantics remain unknown             |
| Ordering              | Chunk commit precedes interpretation; parse receipt commit precedes final outcome; final outcome precedes reported completion |
| Partial response      | Missing terminator, truncated JSON, malformed framing, and midstream close never become success               |
| Bounds                | Oversized bodies/events produce bounded failure or unknown outcome without resend                             |
| Crash matrix          | Every Section 13 boundary yields the specified durable interpretation; parse receipt does not auto-finalize after restart |
| SQLite configuration  | Every connection sets and verifies DELETE/FULL/foreign_keys/busy_timeout; `user_version` is schema-only       |
| Storage failure       | Disk-full, busy-timeout expiry, commit failure, corruption, and pragma mismatch never reopen sending or report undurable success |
| Privacy               | Sensitive canaries in exceptions, headers, environment, bodies, paths, and parser diagnostics do not reach operational output |
| Restricted evidence   | Body and parse-receipt content remain inside their designated restricted boundary                             |
| Schema                | Unknown fields rejected; sizes bounded; validation errors do not echo sensitive inputs                        |
| V1 isolation          | V1 evidence unchanged; V2 imports no V1 execution services                                                    |
| Restart               | No provider request, claim release, reconciliation, automatic parsing, or automatic finalization              |
| MCP lifetime          | Actual deployed path survives at least the required maximum invocation duration without provider calls        |
| Lifetime failure      | Execution ownership is not frozen; work stops for architecture review without implementing a fallback         |
| Live canary           | One separately authorized request only after provider-free qualification passes                               |

Process-kill tests establish process-crash behavior. Stronger power-loss durability claims require filesystem-specific evidence and must not be inferred from those tests.

## 18. Intentionally omitted complexity

| Omitted mechanismReason                     |                                                                |
| ------------------------------------------- | -------------------------------------------------------------- |
| Approval daemon, keys, service, or ceremony | Conversational authorization is the accepted trust boundary    |
| Separate persistent approval workflow       | SEND binds the identity submitted under that trust model       |
| Separate public attempt ID                  | One attempt per review                                         |
| Retry/A002 workflow                         | Consumed reviews remain consumed                               |
| Continuation/revalidation                   | Stored immutable bytes are transmitted directly                |
| Provider lanes                              | Per-review uniqueness prevents replay                          |
| Background workers                          | Not introduced unless measured host constraints require review |
| Supervisor integration                      | Not part of the qualified synchronous design                   |
| Orphan recovery                             | Existing attempts are never executable after restart           |
| Leases/heartbeats                           | No takeover is permitted                                       |
| Restart reconciliation                      | Unfinished evidence remains unknown                            |
| Event sourcing                              | Four tables express the required facts                         |
| Summary/index artifacts                     | Direct retrieval is sufficient                                 |
| Provider abstraction framework              | One transport path                                             |
| Gateway retry compensation                  | Internal gateway behavior is outside Byte-MCP’s guarantee      |
| Remote attribution framework                | Remote root cause is not reliably knowable                     |
| V1 compatibility layer                      | Retrieval remains separate                                     |
| Automatic parse recovery/finalization       | Durable parse evidence is preserved but restart outcome stays unresolved |

### Explicit Milestone-A deferrals

Two reviewed ideas are deliberately not part of the Milestone-A architecture:

1. **`REQUEST_STARTED` / `ABORTED_BEFORE_SEND`:** no fourth durable transport-start fact is added. A crash after claim and before an observable connect result remains consumed and unresolved. This is recorded as a conscious precision tradeoff, not an oversight.
2. **Heartbeat lifetime probe:** the mandatory first qualification remains the strict silent 930-second Web UI → MCP → Byte-MCP probe. A heartbeat/keepalive experiment may be proposed only as a diagnostic after strict-probe failure during architecture review; it is not an automatic fallback and cannot convert that failure into a PASS.

## 19. Open qualification decisions

These decisions complete configuration or validate assumptions; they do not authorize new capabilities.

1. **MCP lifetime:** Does the deployed host path support the full required invocation duration? This controls whether synchronous ownership can be frozen.
2. **Model profile:** Confirm supported SSE completion rules and successful finish reasons for the fixed model/profile before Task 7 qualification.
3. **Preparation policy:** Confirm repository/subsystem allow-lists, context-selection rules, and artifact exclusions.
4. **Storage qualification:** Confirm the supported local filesystem. SQLite mode is pinned to `journal_mode=DELETE`, `synchronous=FULL`, `foreign_keys=ON`, finite `busy_timeout`, and readback verification on every connection.
5. **Snapshot semantics:** The approved exact commits remain the review target if branch tips move. SEND does not rebuild or revalidate repository content.
6. **Evidence retention:** Define operator-controlled archival/deletion separately while preserving consumed-attempt identity. V2 exposes neither operation.

Conversational approval is the initial accepted trust model, not an unresolved approval-infrastructure gate. Internal gateway retry behavior is an external property, not a requirement for additional local machinery.

## 20. Final simplification review

Each retained component has a direct requirement:

- Preparation establishes bounded immutable identity.
- The public tools constrain operations.
- SQLite prevents duplicate local claims and preserves evidence.
- Transport performs the sole request.
- Response validation produces immutable versioned parse receipts from canonical durable bytes.

The design retains no separate approval service, attempt lifecycle framework, retry system, background job, recovery process, or provider abstraction.

`TRANSMITTING` remains only a process-local optional live observation. Durable correctness depends on prepared evidence, attempt existence, response bytes, optional versioned parse receipts, and an optional immutable final outcome.

The two central limits remain explicit:

- Human authorization depends on Byte honoring Nolan’s conversational approval; stored authorization fields are assertions, not independent proof.
- At-most-once initiation applies to Byte-MCP’s Gateway HTTP request, not internal Vercel or Z.AI execution.

**Final architecture:** freeze one request, obtain explicit conversational approval, exclude the exact SEND credential from the frozen payload, consume one durable send opportunity, make at most one Gateway request, preserve streamed bytes, version the interpretation, and never resend.