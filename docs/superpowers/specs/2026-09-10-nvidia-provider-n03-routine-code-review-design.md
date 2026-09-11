# NVIDIA-03 Routine Code Review Design

Date: 2026-09-10

## Status

Approved design for the NVIDIA-03 routine code-review capability.

NVIDIA-02 live-qualified predecessor:

`8ce92056cdfe8412cd9856eca32fb2ddacf52147`

NVIDIA-03 branch:

`feat/nvidia-provider-n03-routine-code-review`

## Goal

Add a bounded, evidence-backed NVIDIA routine code-review capability to Byte-MCP using the live-qualified hosted NVIDIA transport while preserving strict provider isolation, immutable request identity, exactly-once transmission, and explicit human authorization.

## Scope

NVIDIA-03 adds a new NVIDIA-specific external review path. It does not refactor OX into a shared review kernel, does not import OX service/bundle modules into NVIDIA, does not add automatic NVIDIA-to-OX fallback, and does not add autonomous provider routing.

The first enabled model remains fixed to:

`nvidia/nemotron-3.5-lightning-30b-a3b`

The model is used in the thinking-disabled mode proven by the successful NVIDIA-02 canary.

## Architecture

NVIDIA-03 consists of four bounded components:

1. An NVIDIA-owned deterministic Git review packet builder with no OX dependency.
2. A durable NVIDIA review evidence store with immutable prepared identity and append-only attempt lifecycle.
3. A narrow NVIDIA review service that prepares, transmits, parses, and reads one review without retries or fallback.
4. Two MCP tools: `nvidia_review` for prepare/approve and `nvidia_get_review` for bounded read-only inspection.

The existing generic NVIDIA chat transport remains the only network execution path. NVIDIA-03 does not introduce a second HTTP client or alternate endpoint implementation.

## Frozen bounds

The following limits are part of the NVIDIA-03 contract:

- objective: 4,096 UTF-8 bytes maximum;
- verification records: 32 maximum;
- verification `stdout`: 16,384 characters maximum per record;
- verification `stderr`: 16,384 characters maximum per record;
- changed target files: 200 maximum;
- individual changed text file: 524,288 bytes maximum;
- serialized review packet: 3,145,728 bytes maximum;
- review findings: 50 maximum;
- result summary: 4,000 characters maximum;
- finding path: 512 characters maximum;
- finding title: 200 characters maximum;
- finding explanation: 4,000 characters maximum;
- finding recommendation: 4,000 characters maximum;
- finding line: `null` or integer from 1 through 2,147,483,647;
- NVIDIA review completion budget: 4,096 tokens maximum.

The existing provider-runtime request and response byte limits remain authoritative outer bounds. NVIDIA-03 must fail before provider start if its stricter review bounds are exceeded.

## Review lifecycle

The lifecycle is:

```text
PREPARE
  -> validate repository/subsystem/commit identities
  -> construct deterministic review packet
  -> construct exact NVIDIA chat request bytes
  -> compute payload_sha256 and request_sha256
  -> allocate NVR-XXXXXX
  -> persist prepared evidence
  -> STOP

HUMAN REVIEW
  -> inspect NVR identity and exact request_sha256
  -> explicit authorization bound to both values
  -> persist PROVIDER_START
  -> exactly one execute_prepared_nvidia_chat()
  -> parse bounded structured review result
  -> persist terminal evidence
  -> STOP
```

No retry, fallback, catalog call, model substitution, or second provider request is automatic.

## MCP surface

### `nvidia_review`

Prepare mode arguments:

- `repository: str`
- `subsystem: str`
- `target_commit: str`
- `base_commit: str`
- `objective: str`
- `verification: list[dict[str, object]]`

Prepare mode returns bounded identity metadata only, including:

- `review_id`
- `provider_id`
- `model_id`
- `target_commit`
- `base_commit`
- `payload_sha256`
- `request_sha256`
- `prepared_at`
- `evidence_root`

Approval mode arguments:

- `review_id: str`
- `expected_request_sha256: str`
- `approve: bool = True`

Approval mode rejects all scoped prepare arguments. It may transmit only when the exact persisted request hash equals `expected_request_sha256`, the review has no provider-start event, and the review has no terminal event.

There is no `retry` flag in NVIDIA-03.

### `nvidia_get_review`

Arguments:

- `review_id: str`
- `view: str = "summary"`

Allowed views:

- `summary`
- `findings`
- `attempt`
- `manifest`

This tool is read-only and performs zero provider calls.

## Repository allow-list and review packet

NVIDIA-03 reviews only repositories declared in an NVIDIA-review local repository registry. The registry is configured independently from OX settings and maps a safe repository alias to one absolute existing Git repository plus named subsystem definitions. Repository registry loading and validation perform zero provider calls.

Each subsystem defines source roots, test roots, boundary files, and context files using safe logical Git paths. NVIDIA-03 accepts only exact 40-hex base and target commit SHAs resolved from the allow-listed repository.

The deterministic packet contains:

- repository alias
- subsystem identifier
- exact base commit
- exact target commit
- objective
- base-to-target Git diff
- changed target-file contents for regular UTF-8 text files
- bounded verification evidence
- per-artifact SHA-256 values
- packet manifest and manifest SHA-256

The packet includes only target-side contents of files changed between base and target that are within the configured subsystem scope. Deleted paths may appear in the diff but have no target-file content artifact. Provider findings may reference only target-side changed-file artifacts included in the prepared manifest.

Unsafe Git entries, unresolved commits, binary files in mandatory review scope, non-UTF-8 mandatory text, excessive changed-file counts, excessive artifact sizes, or packets exceeding the frozen maximum are rejected before provider start.

The packet builder must not depend on OX Python modules. NVIDIA-03 implements the minimal isolated equivalent needed for this review path; OX remains unchanged.

## Prompt and request contract

The NVIDIA review prompt is deterministic and versioned.

The model receives the review objective plus the immutable review packet and is instructed to return JSON only.

The fixed request parameters are:

- model: `nvidia/nemotron-3.5-lightning-30b-a3b`
- endpoint: `POST /v1/chat/completions`
- `temperature=0.2`
- `top_p=0.95`
- `max_tokens=4096`
- `n=1`
- `stream=false`
- `chat_template_kwargs.enable_thinking=false`
- no reasoning budget

Required top-level schema:

```json
{
  "decision": "PASS|FINDINGS",
  "summary": "string",
  "findings": []
}
```

Each finding must contain:

```json
{
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "path": "logical/repository/path",
  "line": 1,
  "title": "string",
  "explanation": "string",
  "recommendation": "string"
}
```

`line` may be `null` when no defensible line can be identified.

`decision=PASS` requires an empty findings list. `decision=FINDINGS` requires at least one finding.

The parser rejects unknown top-level or finding fields, invalid severities, unsafe or unprepared paths, excessive counts or lengths, inconsistent decision/findings combinations, and malformed JSON.

Malformed or schema-invalid provider output does not cause a retry. The provider request remains terminally recorded as completed transport with an invalid-review-result classification.

## Evidence

NVIDIA review evidence is stored outside Git under the NVIDIA evidence root in a review-specific namespace distinct from canary evidence. Review IDs are monotonically allocated as `NVR-000001`, `NVR-000002`, and so on within the selected evidence root.

Each review persists enough bounded evidence to reconstruct and audit the exact prepared identity without storing credentials:

- immutable review manifest
- exact prepared request bytes
- request and payload SHA-256 values
- preparation timestamp
- provider-start timestamp if consumed
- terminal outcome and transport metadata
- bounded parsed findings or invalid-result classification

Credentials, bearer headers, raw environment variables, and API-key values are never persisted or included in hashes, reprs, logs, MCP return payloads, or Git-tracked artifacts.

## Exactly-once and authorization rules

A prepared NVIDIA review is unconsumed until durable `PROVIDER_START` exists.

Once `PROVIDER_START` is persisted, authorization is consumed regardless of provider outcome. The same review ID may never transmit again.

A terminal review may never accept another event.

There is no NVIDIA-03 automatic retry, manual retry flag, fallback, replay, continuation, revalidation, model substitution, or `/v1/models` pre-call.

A future retry or review-follow-up design, if needed, must allocate a new review identity and require fresh authorization.

## Provider isolation

NVIDIA review modules must not import OX or Wolfram modules.

OX and Wolfram must not call NVIDIA review modules.

No provider output may be interpreted as an instruction to call another provider.

NVIDIA-03 performs no automatic NVIDIA-to-OX escalation. Byte or the operator may choose OX separately for a consequential review, but that is a distinct operation with its own authorization and evidence.

## Model lifecycle

The successful `NVC-000002` canary qualifies the hosted Lightning transport/semantic path for the fixed model.

NVIDIA-03 may mark the Lightning model `QUALIFIED` for the tested hosted chat capability. It must not mark the routine-review capability `ENABLED` until:

1. NVIDIA-03 passes offline qualification;
2. a first immutable `NVR-000001` is prepared and explicitly approved;
3. exactly one live review completes with valid terminal evidence; and
4. the returned review result passes the bounded parser.

## Error handling

Pre-provider validation failures are `NOT_SENT` and create no provider-start event.

Transport outcomes retain the qualified provider-runtime semantics:

- connect/pool failures before transmission -> `NOT_SENT`
- complete non-2xx response -> `REJECTED`
- ambiguous post-start transport failure -> `OUTCOME_UNKNOWN`
- complete 2xx response -> `COMPLETED`

A complete 2xx response with invalid review JSON is `COMPLETED` at the transport layer and terminally classified as an invalid review result at the NVIDIA-review layer.

No outcome triggers automatic recovery.

## Security boundaries

The review packet is derived only from exact Git objects and supplied verification evidence. Working-tree state is not silently substituted for committed state.

All repository paths are logical Git paths and must reject traversal, absolute paths, drive prefixes, symlinks, submodules, and other unsafe entry modes in mandatory scope.

Provider response paths are validated against the prepared target-side changed-file manifest before being exposed as findings.

Provider text is data, never executable instruction.

## Testing and qualification

Implementation follows TDD.

Offline qualification must cover at minimum:

- deterministic packet and request hashing
- exact base/target binding
- allow-listed repository enforcement
- unsafe/binary/non-UTF-8 path rejection
- deleted-file handling
- changed-file, per-file, verification, objective, and packet limits
- verification evidence validation
- fixed model and thinking-disabled request
- credential blindness during prepare/read
- request-hash approval binding
- durable provider-start before executor call
- concurrent transmit exclusion
- no retransmission after provider-start
- no events after terminal state
- no retry/fallback/catalog/model substitution paths
- strict JSON result parsing and bounds
- decision/findings consistency
- response finding paths constrained to prepared changed files
- NVIDIA/OX/Wolfram import isolation
- MCP mode validation
- Linux and Windows full-suite regression

No live NVIDIA, OX, Wolfram, or other provider/model calls are allowed during implementation or offline qualification.

## Live qualification boundary

After offline qualification, preparation of the first real `NVR-000001` is provider-free and stops after exposing its exact request SHA-256.

The first NVIDIA-03 live review requires a separate explicit authorization bound to `NVR-000001` and that exact request SHA-256.

Exactly one NVIDIA provider request is permitted by that authorization. Any outcome hard-stops the operation.

## Out of scope

NVIDIA-03 does not include:

- automatic provider routing
- automatic OX escalation
- shared OX/NVIDIA review orchestration
- OX refactoring
- review continuation or conversational follow-up
- revalidation
- retry or backoff
- model discovery calls
- multi-model review
- release/deployment promotion
- autonomous merging or mutation of reviewed repositories
