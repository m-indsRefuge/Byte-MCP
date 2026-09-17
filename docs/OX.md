# OX Clean-Room Operator Contract

This document is the current operator contract for the clean-room OX subsystem in Byte-MCP. It supersedes pre-clean-room OX execution guidance. Historical OX V1/V2 material remains available through Git history and the archival note at `archive/OX-ARCHIVE.md`.

## Status and authority boundary

The clean-room implementation is a synchronous, code-review-only capability. It has completed provider-free implementation qualification on the feature branch, but runtime promotion and the first real OX provider review are separate explicit authorization boundaries.

OX may inspect only repositories that are direct child directories beneath Byte-MCP's existing `projects` root. The caller supplies a repository alias/directory name, never an arbitrary absolute path. The runtime reuses the already configured `projects` root; it does not load a second repository-authority source.

`config/ox-repositories.example.json` is documentation-only. It illustrates valid direct-child repository names; the clean-room runtime does not read a separate OX repository registry.

## Public MCP surface

OX exposes exactly two MCP tools:

- `ox_review(repository, mode, objective, paths=None)` — one synchronous review lifecycle and at most one external provider request.
- `ox_get_review(review_id)` — local, read-only evidence projection with zero provider networking.

No clean-room OX tool exists for continuation, revalidation, retry, background jobs, recovery, provider polling, general chat, or provider tool use.

## Review modes

### `FULL_REPOSITORY`

`paths` must be omitted/empty. OX freezes all material that is eligible under the versioned snapshot policy in the selected repository.

### `BOUNDED`

`paths` must contain one or more existing normalized relative POSIX paths beneath the selected repository. Absolute paths, parent traversal, duplicate separators, Windows drive prefixes, backslash paths, control characters, and link/junction components are rejected. A bounded review never silently widens to the whole repository.

`objective` must be non-empty. It is included in the frozen review packet.

## Current-filesystem snapshot

Filesystem bytes at snapshot time are authoritative. Eligible material can include committed tracked files, staged changes, unstaged changes, and untracked text files. Editing a file after the snapshot is frozen does not alter the packet for that review.

Traversal is deterministic and does not follow symlinks or junctions. Nested repositories are not recursively entered. A directly selected link or junction fails closed.

The snapshot policy excludes sensitive and unsuitable material before packet construction, including environment-secret files, known credential/key files, `.git`, virtual environments, dependency directories, generated/build/cache/coverage output, databases, archives, binary/media files, nested repositories, invalid UTF-8/NUL-containing files, and Byte-MCP/OX evidence directories. Exclusions are recorded in `snapshot.json` by logical path and reason.

A file larger than `OX_MAX_ARTIFACT_BYTES` is currently classified as `artifact-too-large` and excluded from snapshot eligibility. Included eligible content then remains subject to the hard artifact-count, aggregate-content, packet, and shared prepared-request bounds. If an included review exceeds one of those hard bounds, the review fails locally with zero provider requests; OX does not truncate, summarize, split, or silently drop included eligible material to fit the provider budget.

Current bounds:

```text
OX_MAX_ARTIFACT_BYTES         = 1,000,000
OX_MAX_ARTIFACTS              = 5,000
OX_MAX_SNAPSHOT_CONTENT_BYTES = 3,250,000
OX_MAX_PACKET_BYTES           = 3,500,000
shared prepared-request max   = 4,000,000 bytes
shared response max           = 8,000,000 decoded bytes
```

Operators should inspect `snapshot.json` exclusions when the distinction between "all filesystem files" and "all eligible snapshot material" matters.

## Provider profile

The provider route is fixed:

```text
Byte-MCP
  -> https://ai-gateway.vercel.sh/v1/chat/completions
  -> provider allow-list: zai
  -> model: zai/glm-5.3-flash
```

The request is non-streaming, uses `reasoning.effort="medium"`, and sets `max_tokens=65536`. OX has no caller-controlled endpoint, provider, model, retry, fallback, or provider-tool authority.

The credential is read lazily from `AI_GATEWAY_API_KEY` only when an approved review reaches transmission preflight. It is not required for server startup or local `ox_get_review` retrieval.

## Approval and one-request lifecycle

One explicit authorization to invoke `ox_review` covers exactly that review's complete lifecycle. There is no PREPARE/second-approval/SEND sequence.

The lifecycle is:

```text
resolve scope
-> freeze current snapshot
-> build deterministic packet
-> prepare canonical provider request
-> allocate review ID and persist prepared evidence
-> load credential
-> validate request integrity and provider-bound safety
-> create irreversible send.claim
-> execute at most one provider request
-> persist exact raw response bytes
-> decode/extract one non-empty free-form assistant review
-> persist review text
-> finalize evidence
-> return safe projection
```

`send.claim` is the irreversible send-authority boundary. Once it exists it is never deleted, reset, or recreated to authorize another request. Duplicate/concurrent execution can therefore have only one transport winner for the same review identity.

There is no automatic retry, reconnect, continuation, resume, revalidation, queue, worker, or recovery daemon. A later provider review always requires a new explicit invocation and a new review identity.

## Free-form response contract

OX returns natural technical prose. The provider is not required to emit findings arrays, severity enums, pass/fail decisions, or a structured JSON review schema. Byte-MCP requires only a valid provider envelope containing exactly one non-empty assistant message.

The exact provider response bytes are persisted before the envelope is decoded or the assistant text is extracted.

## Review states

The public projection uses four states:

- `READY` — prepared evidence exists and no durable `send.claim` exists.
- `COMPLETED` — the one attempt completed, exact response bytes and extracted review text are durable, and completion evidence remains internally consistent.
- `FAILED` — the outcome is definite enough to classify as failure. Examples include definite `NOT_SENT` connect/pool failures, a complete non-2xx provider rejection, or a complete 2xx response whose envelope does not contain a valid non-empty assistant review.
- `OUTCOME_UNKNOWN` — send authority has been consumed but delivery/result/evidence cannot be established safely. Examples include write/read/deadline/remote-protocol ambiguity, response/review persistence uncertainty, a crash after claim without trustworthy terminal evidence, or later evidence corruption.

A local failure before `send.claim` performs zero provider requests. Depending on how far preparation progressed, it may leave no review directory or a `READY` review directory. A post-claim `OUTCOME_UNKNOWN` must never be treated as permission to replay the request.

## Evidence store

Default evidence roots are:

```text
Windows: %LOCALAPPDATA%\Byte-MCP\ox
POSIX:   ${XDG_DATA_HOME:-~/.local/share}/byte-mcp/ox
```

Override only with `BYTE_MCP_OX_EVIDENCE_DIR`.

Each review uses one directory:

```text
<evidence-root>/reviews/OX-000001/
    review.json
    snapshot.json
    packet.bin
    request.bin
    send.claim       # present only after send authority is consumed
    response.bin     # present when exact provider response was durably captured
    review.txt       # present when free-form assistant text was durably extracted
```

`review.json` is the safe mutable state projection and integrity metadata. `snapshot.json` contains logical inventory, hashes, byte counts, classifications, and exclusions, but not raw artifact content. `packet.bin` contains the exact provider review packet. `request.bin` contains the exact serialized provider request body. `response.bin` contains the exact provider response body. `review.txt` contains the extracted free-form review.

### Restricted forensic material

Treat `snapshot.json`, `packet.bin`, `request.bin`, and `response.bin` as restricted forensic evidence. They may reveal repository structure, source material, or raw provider material. Do not paste them into chat, tickets, routine logs, or public issue reports. Inspect them locally only when the failure map calls for it and only to the minimum extent required.

The API credential, authorization header, proxy/environment values, and absolute local repository path are not persisted in those provider-bound evidence files by design.

`ox_get_review` exposes only a safe projection: review identity/state, repository alias/mode, snapshot/request hashes, provider/model identity, provider timestamps/outcome, response byte count, and final review text when trustworthy.

## Failure handling and diagnostics

Use `docs/FAILURE_MAP.md` as the governing OX diagnostic map. In particular:

- distinguish pre-claim local failures from post-claim failures;
- distinguish definite `FAILED` from ambiguous `OUTCOME_UNKNOWN`;
- preserve evidence rather than rewriting it to make a review appear complete;
- never solve an OX failure by retrying the same review identity;
- never weaken scope, exclusion, credential, request-identity, size, or evidence-integrity controls to obtain a provider result.

## Runtime isolation

OX runtime construction is lazy and fail-isolated. Missing/invalid OX runtime configuration must not prevent the core filesystem tools, Wolfram, or NVIDIA tools from starting. The provider credential is not loaded at server import/runtime construction time.

OX and NVIDIA do not import one another. OX does not invoke Wolfram.

## Historical generations

The clean-room implementation has no runtime compatibility path for OX V1 or the abandoned OX V2 generation. `ox_get_review` reads only clean-room evidence. Historical source, evidence, specs, and qualification material remain forensic history through the archive branches and Git history; see `archive/OX-ARCHIVE.md`.

The old `docs/OX-VALIDATION.md` and pre-clean-room OX plans/specs are historical references, not current operating instructions.

## Promotion and first live review

Provider-free qualification does not authorize deployment or a real provider request.

Two later boundaries remain separate:

1. **Runtime promotion authorization** — explicitly authorize promotion of the qualified clean-room candidate into the live Byte-MCP runtime.
2. **First live OX review authorization** — after promotion and live surface verification, explicitly authorize one real OX provider review/canary.

Neither boundary is implied by completion of implementation, tests, documentation, or CI.
