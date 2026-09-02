# Q03H Durable Background OX Transmission Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every provider-bearing OX operation into one runtime-session-owned background lane with durable attempt ownership, truthful launch receipts, bounded transport evidence, explicit retry approval, and provider-free recovery.

**Architecture:** The OX runtime creates one in-process job manager and a unique bounded runtime session ID. Each provider-bearing service operation reserves the shared lane, durably claims one attempt with that runtime owner, persists its exact history, and submits an immutable descriptor; a worker then records the provider boundary, performs exactly one natural-text request, terminalizes evidence, and releases the lane independently of MCP cancellation. Append-only evidence remains authoritative across restart, while historical ownerless Q03G evidence remains readable and subject to the existing stale-recovery fallback.

**Tech Stack:** Python 3.12.10, pytest 9.1.1, Ruff 0.16.1, FastMCP/MCP, HTTPX 0.28.x, standard-library threading and UUID primitives, append-only canonical JSON/JSONL evidence, PowerShell 7.6.4, and Pester launcher checks.

**Spec:** `docs/superpowers/specs/2026-09-02-ox-durable-background-transmission-ownership-design.md`

## Global Constraints

- Work only in `C:\Users\nolan\AIProjects\Byte-MCP-q03h` on `fix/ox-runtime-q03h-durable-background-ownership` based on `e953b1eb3bb4893a98b6cf6fdfe9961873c708b7`.
- Before each task, require the expected branch, preserve all prior task commits, and require no unexplained working-tree changes.
- Use PowerShell. Set `PYTHONPATH` to `C:\Users\nolan\AIProjects\Byte-MCP-q03h\src` and run Python through `C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe`.
- Never create an ad-hoc environment or alter machine-wide configuration.
- Use deterministic fake clients, `threading.Event`, barriers, and bounded joins. Never use a real API key, real provider transport, or a sleep-only assertion as the proof of ownership.
- Every natural initial, retry, continuation, and revalidation request remains `json_mode=False`.
- The raw provider response is canonical and precedes natural assistant thread persistence and terminal completion.
- Byte-derived findings remain a separate local immutable operation; absent findings remain distinct from an explicitly recorded empty set.
- One runtime owns one provider lane across all seven provider-bearing operations. There is no queue and no lane per operation type.
- A different active operation is rejected before attempt claim, transmission intent, or provider contact.
- Same-operation active replay makes no attempt, worker, or provider call and returns bounded local launch evidence.
- No automatic retry exists. Initial and revalidation retry require explicit retry mode plus renewed human approval; continuation retry additionally requires the exact latest failed attempt ID.
- Provider ambiguity is never downgraded to `NOT_SENT`; `AttemptOutcome` remains authoritative.
- Historical `OX-000007-A001`, `OX-000008-A001`, `OX-000009-A001`, and `OX-000010-A001` remain immutable and are never retried.
- No source implementation task mutates historical evidence, Wolfram code, deployment scripts, the deployed runtime repository, daemon state, or the Windows Scheduled Task.
- No task authorizes merge, push, promotion, deployment, daemon restart, live OX canary, or live Wolfram request.
- Shared service, evidence, runtime, and job-manager interfaces are changed sequentially. Tasks 4 through 7 must not run in parallel.
- Each behavioral task completes a focused RED/GREEN cycle, related regression, lint or syntax check, self-review, local commit, and fresh independent review before the next shared-interface task starts.
- If a frozen requirement conflicts with live code or immutable evidence, stop and report the exact file/line conflict and smallest Nolan decision required.

---

## Canonical command prelude

Run this at the start of every implementation and verification shell:

```powershell
Set-Location -LiteralPath 'C:\Users\nolan\AIProjects\Byte-MCP-q03h'
$env:PYTHONPATH = 'C:\Users\nolan\AIProjects\Byte-MCP-q03h\src'
$Python = 'C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe'
& $Python --version
```

Expected version: `Python 3.12.10`.

The Q03H worktree has no `.venv` at the frozen base. `scripts\Check.ps1` hard-codes `<worktree>\.venv\Scripts\python.exe`, so the plan does not create a junction or replacement environment. Task 8 executes that script's provider-free gates equivalently with `$Python` and then runs `scripts\Check-Launcher.ps1` directly.

Before Task 1, verify that the Q03H-00 bootstrap commit contains only this plan
and its frozen design spec, has the exact subject
`docs: lock q03h durable ox transmission ownership`, and leaves the worktree
clean. Its independent review must compare both documents to the complete
execution directive and confirm that it authorizes no source, provider,
runtime, deployment, merge, or push action.

## Repository map at the frozen base

### New files

- `src/byte_mcp/ox/jobs.py`
  - Owns the runtime session identifier, single provider lane, reservation state, active launch record, thread submission, crash containment, and exact-once lane release.
- `tests/ox/test_background_job_manager.py`
  - Uses deterministic events and barriers to prove reservation, busy, replay, submission failure, crash release, and no-queue behavior without any provider.

### Modified production files

- `src/byte_mcp/errors.py`
  - Adds the fixed safe OX transport-failure classification and bounded timing fields while preserving blank public exception text and authoritative `attempt_outcome`.
- `src/byte_mcp/ox/client.py`
  - Maps each concrete `TimeoutError`/HTTPX exception branch to a fixed diagnostic kind and authoritative outcome; still performs one request and never retries.
- `src/byte_mcp/ox/evidence.py`
  - Persists runtime owner in intent, enforces one provider-start event, records bounded terminal transport metadata, reconstructs optional Q03H fields, and recovers foreign-runtime transmissions before the 1,800-second legacy fallback.
- `src/byte_mcp/ox/service.py`
  - Splits all base claim paths from worker execution, carries immutable launch descriptors, preserves continuation history and retry authorization, and adapts retrieval.
- `src/byte_mcp/ox/natural_service.py`
  - Preserves natural initial and revalidation authority while running already-claimed descriptors and maintaining Byte-derived findings provenance.
- `src/byte_mcp/ox/runtime.py`
  - Creates one job manager before recovery, passes its runtime session ID to recovery, and injects the manager into the single OX service.
- `src/byte_mcp/server.py`
  - Keeps all four public OX signatures unchanged and returns service launch receipts directly instead of awaiting provider completion through `asyncio.to_thread(...)`.

### Modified tests

- `tests/test_errors.py`
  - Locks the bounded OX transport error contract and blank exception arguments.
- `tests/ox/test_client.py`
  - Owns the transport outcome/kind matrix and bounded diagnostic timing.
- `tests/ox/test_evidence.py`
  - Locks runtime ownership, provider-start uniqueness, metadata reconstruction, current-attempt validation, and historical optional fields.
- `tests/ox/test_orphaned_transmission_recovery.py`
  - Locks immediate cross-runtime recovery, current-runtime exclusion, legacy stale fallback, idempotency, and zero retry.
- `tests/ox/test_long_provider_mcp_safety.py`
  - Locks prompt initial/retry receipts, cancellation independence, replay, and single provider ownership.
- `tests/ox/test_continue_provider_mcp_safety.py`
  - Locks background continuation and continuation-retry behavior while local modes remain inline.
- `tests/ox/test_revalidate_provider_mcp_safety.py`
  - Locks prompt blind, retry, and targeted launches while preparation remains inline.
- `tests/ox/test_runtime.py`
  - Locks one manager/session per initialized runtime and recovery before service exposure without network use.
- `tests/ox/test_natural_review_architecture.py`
  - Locks `json_mode=False`, natural authority, initial success ordering, active replay, and targeted Byte provenance.
- `tests/ox/test_review_service.py`
  - Updates shared fixtures for the job manager and locks claim/worker separation, submission failure, terminal evidence, and explicit initial retry.
- `tests/ox/test_review_followup.py`
  - Locks exact continuation history, retry identity, blind/targeted phase behavior, and no duplicate message persistence.
- `tests/ox/test_mcp_surface.py`
  - Locks unchanged public schemas, additive launch receipts, local-only modes, provider-free attempts retrieval, and no `to_thread` provider-completion ownership.
- `tests/ox/test_security_invariants.py`
  - Locks credential rejection before claim/provider work and explicit retry authority under the new manager.
- `tests/ox/test_security_defense_in_depth.py`
  - Locks secret-free retrieval and persisted-context rejection after the new metadata fields.
- `tests/ox/test_natural_review_security.py`
  - Preserves local Byte-findings security after asynchronous initial completion.
- `tests/ox/test_byte_coding_audit.py`
  - Locks bounded audit data and prevents runtime/transport metadata from becoming secret-bearing.

### Inspected and intentionally unchanged

- `src/byte_mcp/ox/models.py` retains `AttemptOutcome`, `ReviewState`, provider results, and finding models; Q03H job-only value objects remain private to `jobs.py` and transport failure kinds remain with the error boundary.
- `src/byte_mcp/ox/protocol.py`, repository/bundle/settings modules, and all core file-service modules retain their existing contracts.
- `src/byte_mcp/wolfram/**`, `tests/wolfram/**`, Wolfram schemas, and launcher/runtime scripts receive no Q03H production edit.
- `scripts/Accept-OX-Q03G-HistoricalEvidence.ps1` remains unchanged and read-only in use.

## Locked internal interfaces

### Safe transport diagnostic

`src/byte_mcp/errors.py` adds:

```python
class OXTransportFailureKind(StrEnum):
    ABSOLUTE_DEADLINE = "ABSOLUTE_DEADLINE"
    READ_TIMEOUT = "READ_TIMEOUT"
    READ_ERROR = "READ_ERROR"
    WRITE_TIMEOUT = "WRITE_TIMEOUT"
    WRITE_ERROR = "WRITE_ERROR"
    REMOTE_PROTOCOL_ERROR = "REMOTE_PROTOCOL_ERROR"
    HTTP_TRANSPORT_ERROR = "HTTP_TRANSPORT_ERROR"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    CONNECT_ERROR = "CONNECT_ERROR"
    POOL_TIMEOUT = "POOL_TIMEOUT"


class OXTransportError(_ProviderCallError):
    transport_failure_kind: OXTransportFailureKind | None
    provider_started_at: str | None
    provider_finished_at: str | None
    elapsed_ms: int | None
```

`OXTransportError` continues to have empty `args`, no copied exception message, and an approved `attempt_outcome`. Real `OXClient` transport failures always populate the four safe diagnostic fields; `None` is accepted only for legacy synthetic error fixtures and non-transport provider errors never invent a transport kind.

### Durable evidence calls

Final Q03H production claim call sites supply `runtime_session_id` to the existing claim methods. The store permits a missing owner only when reconstructing or deliberately constructing legacy-format test evidence.

```python
EvidenceStore.claim_initial_transmission(
    review_id: str,
    manifest_sha256: str,
    *,
    runtime_session_id: str | None = None,
) -> dict[str, str]

EvidenceStore.claim_retry_transmission(
    review_id: str,
    manifest_sha256: str,
    *,
    renewed_approval: bool,
    runtime_session_id: str | None = None,
) -> dict[str, str]

EvidenceStore.claim_continuation_transmission(
    review_id: str,
    manifest_sha256: str,
    *,
    runtime_session_id: str | None = None,
) -> dict[str, str]

EvidenceStore.claim_continuation_retry(
    review_id: str,
    manifest_sha256: str,
    previous_attempt_id: str,
    *,
    renewed_approval: bool,
    runtime_session_id: str | None = None,
) -> dict[str, str]

EvidenceStore.claim_revalidation_transmission(
    revalidation_id: str,
    *,
    phase: str,
    runtime_session_id: str | None = None,
) -> dict[str, str]

EvidenceStore.claim_revalidation_retry(
    revalidation_id: str,
    previous_attempt_id: str,
    *,
    renewed_approval: bool,
    runtime_session_id: str | None = None,
) -> dict[str, str]
```

The owner is written in the same JSONL intent append as the attempt allocation. Separate initial/continuation and revalidation methods validate and append boundary/metadata events:

```python
EvidenceStore.record_provider_request_started(
    review_id: str,
    attempt_id: str,
    *,
    runtime_session_id: str,
    phase: str,
) -> None

EvidenceStore.record_revalidation_provider_request_started(
    revalidation_id: str,
    attempt_id: str,
    *,
    runtime_session_id: str,
    phase: str,
) -> None

EvidenceStore.record_provider_transport_metadata(
    review_id: str,
    attempt_id: str,
    *,
    runtime_session_id: str,
    provider_finished_at: str,
    elapsed_ms: int,
    transport_failure_kind: str | None,
) -> None

EvidenceStore.record_revalidation_provider_transport_metadata(
    revalidation_id: str,
    attempt_id: str,
    *,
    runtime_session_id: str,
    provider_finished_at: str,
    elapsed_ms: int,
    transport_failure_kind: str | None,
) -> None

EvidenceStore.recover_stale_transmissions(
    *,
    stale_after: timedelta,
    runtime_session_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, ...]
```

With `runtime_session_id` supplied, foreign Q03H owners recover immediately; the current owner is preserved; ownerless legacy evidence uses the existing timestamp and stale horizon.

### Job manager calls

`src/byte_mcp/ox/jobs.py` defines private, frozen, bounded values:

```python
@dataclass(frozen=True, slots=True)
class OXOperationKey:
    operation: str
    subject_id: str
    input_sha256: str


@dataclass(frozen=True, slots=True)
class OXLaunchDescriptor:
    operation_key: OXOperationKey
    review_id: str
    attempt_id: str
    manifest_sha256: str
    phase: str
    revalidation_id: str | None
    messages: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class OXActiveLaunch:
    descriptor: OXLaunchDescriptor
    receipt: Mapping[str, object]
```

Message mappings and receipts are defensively copied into immutable views before submission. Manager state stores bounded IDs, enum-like operation/phase strings, digests, and the active receipt; it never stores credentials, provider responses, or exception text.

The concrete call surface is:

- `runtime_session_id` is a read-only `str` property.
- `reserve(operation_key: OXOperationKey) -> OXLaneLease | OXActiveLaunch`
  reserves an empty lane or returns the already-accepted launch for the same
  operation key.
- `submit(lease: OXLaneLease, descriptor: OXLaunchDescriptor, receipt:
  Mapping[str, object], worker: Callable[[OXLaunchDescriptor], None],
  on_submission_failure: Callable[[OXLaunchDescriptor], None],
  on_worker_crash: Callable[[OXLaunchDescriptor], None]) -> None` accepts the
  durably claimed launch and starts its worker.
- `abandon(lease: OXLaneLease) -> None` releases an unsubmitted reservation.
- `snapshot() -> OXActiveLaunch | None` returns the immutable active launch or
  no launch.

`OXProviderJobManager()` creates `uuid.uuid4().hex`, yielding a bounded 32-character non-secret runtime ID. `reserve` returns the existing `OXActiveLaunch` only for the exact same operation key after accepted submission; it raises a local bounded busy error for a different key or a same-key reservation not yet durably accepted. `submit` catches thread-start failure synchronously, invokes `on_submission_failure`, and releases once. Its wrapper invokes `on_worker_crash` for any escaping exception, releases only after terminalization, and enters a fail-closed fault state if terminal evidence cannot be written. No submitted job can wait behind another job.

Operation keys use the existing durable subject ID plus a SHA-256 of exact immutable inputs:

- initial approval: review ID, `initial`, and prepared payload/manifest digest;
- initial retry: review ID, `initial-retry`, prior attempt ID, and history digest;
- continuation: review ID, `continuation`, and candidate history digest including the one new message;
- continuation retry: review ID, `continuation-retry`, prior attempt ID, and persisted history digest;
- blind revalidation: revalidation ID, `blind`, and prepared history digest;
- revalidation retry: revalidation ID, prior attempt ID and phase, and persisted history digest;
- targeted revalidation: revalidation ID, `targeted`, selected Byte finding IDs/provenance, and generated history digest.

### Service worker calls

The public service methods retain their current signatures. They delegate accepted descriptors only to private run methods that cannot claim:

```python
OXReviewService._run_claimed_initial_attempt(descriptor: OXLaunchDescriptor) -> None
OXReviewService._run_claimed_continuation_attempt(descriptor: OXLaunchDescriptor) -> None
OXReviewService._run_claimed_revalidation_attempt(descriptor: OXLaunchDescriptor) -> None
```

Each run method writes `PROVIDER_REQUEST_STARTED` on the immediately preceding statement before `self._client.complete(..., json_mode=False, attempt_id=...)`. Expected provider errors are terminalized inside the worker and do not escape as unowned work. A submission failure records `NOT_SENT`; an escaping crash is conservatively `OUTCOME_UNKNOWN`. Terminal metadata is appended after the authoritative outcome and before exact-once lane release.

---

### Task 1: Classify OX Transport Failures Safely

**Files:**
- Modify: `src/byte_mcp/errors.py`
- Modify: `src/byte_mcp/ox/client.py`
- Modify: `tests/test_errors.py`
- Modify: `tests/ox/test_client.py`

**Interfaces:**
- Produces `OXTransportFailureKind` and safe timing fields on `OXTransportError`.
- Preserves current one-request behavior, empty public error messages, HTTP status mappings, and `AttemptOutcome` values.

- [ ] **Step 1: Add the two primary transport RED tests**

Add these exact node IDs:

Create
`test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed` to raise a
sentinel-bearing `httpx.ReadError` from `MockTransport`. Assert
`OUTCOME_UNKNOWN`, `READ_ERROR`, bounded UTC start/end timestamps,
non-negative `elapsed_ms`, empty `args`/cause/context, and absence of the
sentinel from `repr`.

Create the parameterized
`test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind` with
these exact rows:

| Exception | Outcome | Kind |
| --- | --- | --- |
| Python `TimeoutError` | `OUTCOME_UNKNOWN` | `ABSOLUTE_DEADLINE` |
| `httpx.ConnectTimeout` | `NOT_SENT` | `CONNECT_TIMEOUT` |
| `httpx.ConnectError` | `NOT_SENT` | `CONNECT_ERROR` |
| `httpx.PoolTimeout` | `NOT_SENT` | `POOL_TIMEOUT` |
| `httpx.ReadTimeout` | `OUTCOME_UNKNOWN` | `READ_TIMEOUT` |
| `httpx.ReadError` | `OUTCOME_UNKNOWN` | `READ_ERROR` |
| `httpx.WriteTimeout` | `OUTCOME_UNKNOWN` | `WRITE_TIMEOUT` |
| `httpx.WriteError` | `OUTCOME_UNKNOWN` | `WRITE_ERROR` |
| `httpx.RemoteProtocolError` | `OUTCOME_UNKNOWN` | `REMOTE_PROTOCOL_ERROR` |
| `httpx.HTTPError` | `OUTCOME_UNKNOWN` | `HTTP_TRANSPORT_ERROR` |

Drive the applicable deadline or `MockTransport` branch once per row. Assert
the exact outcome/kind and that no arbitrary exception message is retained.

Use request-bound HTTPX instances for exception classes that require a request. Patch `_post_with_total_deadline` only for the Python `TimeoutError` and generic `HTTPError` cases; assert exactly one boundary invocation and no retry.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_client.py::test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed' `
  'tests/ox/test_client.py::test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind' `
  -vv
```

Expected RED: missing fixed diagnostic kind/timing, not import, fixture, or network failure.

- [ ] **Step 3: Implement the fixed typed mapping**

Capture UTC start/finish plus `time.monotonic_ns()` elapsed around the single `_post_with_total_deadline` call. Assign kinds by exception type branches, never by parsing `str(exc)`. Construct a new safe `OXTransportError` and raise it only after the original exception has left the active `except` block so cause/context remain suppressed.

- [ ] **Step 4: Run focused GREEN and current client regressions**

```powershell
& $Python -m pytest `
  'tests/ox/test_client.py::test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed' `
  'tests/ox/test_client.py::test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind' `
  'tests/ox/test_client.py::test_complete_maps_provider_status_to_safe_domain_error' `
  'tests/ox/test_client.py::test_complete_maps_transport_failure_without_retry' `
  'tests/ox/test_provider_total_deadline.py' `
  -vv
```

Expected: all selected tests pass, with one fake transport call per case.

- [ ] **Step 5: Validate and self-review Task 1**

```powershell
& $Python -m ruff check src/byte_mcp/errors.py src/byte_mcp/ox/client.py tests/test_errors.py tests/ox/test_client.py
& $Python -m compileall -q src/byte_mcp/errors.py src/byte_mcp/ox/client.py tests/test_errors.py tests/ox/test_client.py
git diff --check
git status --short
git diff -- src/byte_mcp/errors.py src/byte_mcp/ox/client.py tests/test_errors.py tests/ox/test_client.py
```

Confirm no exception text, credential, response body, or new retry path is retained.

- [ ] **Step 6: Commit and review Task 1**

```powershell
git add src/byte_mcp/errors.py src/byte_mcp/ox/client.py tests/test_errors.py tests/ox/test_client.py
git commit -m "feat: classify ox transport failures safely"
git show --check --stat --oneline HEAD
```

Fresh review checks exception hierarchy, outcome preservation, branch ordering, false-positive tests, and secret suppression. Repair findings with a new focused RED/GREEN cycle before Task 2.

---

### Task 2: Persist Runtime Ownership, Provider Boundary, Metadata, and Recovery

**Files:**
- Modify: `src/byte_mcp/ox/evidence.py`
- Modify: `tests/ox/test_evidence.py`
- Modify: `tests/ox/test_orphaned_transmission_recovery.py`

**Interfaces:**
- Adds optional legacy-compatible owner input to all six durable claim methods.
- Produces the four provider-start/transport metadata methods and runtime-aware recovery signature defined above.
- Preserves canonical JSONL, per-review locks, immutable identity files, Q03G event meanings, and the 1,800-second ownerless fallback.

- [ ] **Step 1: Add ownership, event, metadata, and recovery RED tests**

Add four primary tests:

- `test_q03h_ac05_claimed_attempt_persists_runtime_session_id` exercises
  initial, initial retry, continuation, continuation retry, blind
  revalidation, revalidation retry, and targeted claims with one fixed owner;
  every intent and reconstructed attempt must carry that owner.
- `test_q03h_ac06_provider_started_event_is_unique_and_bound_to_current_attempt`
  records the event once and checks its exact fields; duplicate, stale-attempt,
  mismatched-owner, and wrong-phase writes must fail.
- `test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry`
  claims as runtime A and recovers as runtime B before the stale horizon; it
  requires one `OUTCOME_UNKNOWN`, no A002, no provider hook, and idempotent
  recovery.
- `test_q03h_ac19_legacy_q03g_evidence_reads_without_migration` constructs
  canonical pre-Q03H events without owner/start/metadata fields, then proves
  byte-identical files and successful reconstruction plus ownerless fallback.

Supporting tests cover one terminal metadata event, allow-listed failure kind, non-negative elapsed milliseconds, current-attempt enforcement, successful metadata after outcome, current-runtime non-recovery, ownerless fresh/stale behavior, and revalidation symmetry.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_evidence.py::test_q03h_ac05_claimed_attempt_persists_runtime_session_id' `
  'tests/ox/test_evidence.py::test_q03h_ac06_provider_started_event_is_unique_and_bound_to_current_attempt' `
  'tests/ox/test_orphaned_transmission_recovery.py::test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry' `
  'tests/ox/test_evidence.py::test_q03h_ac19_legacy_q03g_evidence_reads_without_migration' `
  -vv
```

Expected RED: missing owner/event/metadata/recovery support, not malformed fixtures.

- [ ] **Step 3: Extend canonical reconstruction and mutation guards**

Persist owner in each intent append. Recognize `PROVIDER_REQUEST_STARTED` and one bounded terminal transport metadata event without changing state. Attach optional fields to the matching reconstructed attempt. Reject duplicate events, mismatched phase/owner, non-current attempt, unknown failure kind, unsafe timestamp, negative elapsed value, or metadata preceding terminal outcome.

- [ ] **Step 4: Implement runtime-aware recovery precedence**

When a current unfinished attempt has a persisted owner different from the supplied startup owner, append `OUTCOME_UNKNOWN` immediately. Leave the supplied current owner unchanged. If no owner exists, execute the established timestamp and 1,800-second stale logic unchanged. Recovery never imports or calls client/service code.

- [ ] **Step 5: Run focused GREEN and evidence regressions**

```powershell
& $Python -m pytest `
  'tests/ox/test_evidence.py::test_q03h_ac05_claimed_attempt_persists_runtime_session_id' `
  'tests/ox/test_evidence.py::test_q03h_ac06_provider_started_event_is_unique_and_bound_to_current_attempt' `
  'tests/ox/test_orphaned_transmission_recovery.py::test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry' `
  'tests/ox/test_evidence.py::test_q03h_ac19_legacy_q03g_evidence_reads_without_migration' `
  tests/ox/test_evidence.py `
  tests/ox/test_orphaned_transmission_recovery.py `
  -q
```

- [ ] **Step 6: Validate, commit, and review Task 2**

```powershell
& $Python -m ruff check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py tests/ox/test_orphaned_transmission_recovery.py
& $Python -m compileall -q src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py tests/ox/test_orphaned_transmission_recovery.py
git diff --check
git status --short
git add src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py tests/ox/test_orphaned_transmission_recovery.py
git commit -m "feat: persist ox runtime transmission ownership"
git show --check --stat --oneline HEAD
```

Fresh review checks event ordering, duplicate rejection, current-attempt locking, recovery precedence, legacy readability, no historical migration, and zero provider dependency. Resolve all findings before Task 3.

---

### Task 3: Add the Single-Lane In-Process Job Manager

**Files:**
- Create: `src/byte_mcp/ox/jobs.py`
- Create: `tests/ox/test_background_job_manager.py`

**Interfaces:**
- Produces `OXOperationKey`, `OXLaunchDescriptor`, `OXActiveLaunch`, `OXLaneLease`, and `OXProviderJobManager` exactly as locked above.
- Does not import `OXClient`, allocate attempts, write evidence, queue work, or persist manager state.

- [ ] **Step 1: Add deterministic manager RED tests**

Add two primary tests:

- `test_q03h_ac03_different_operation_is_busy_before_claim` holds operation A
  with an event and attempts B through a claim spy; require local busy, zero
  claims for B, zero B workers, and no queued launch.
- `test_q03h_ac07_submission_failure_is_not_sent_without_provider_boundary`
  makes `Thread.start` raise; require exactly one submission-failure callback,
  zero boundary entries, zero worker calls, cleared active state, and a reusable
  lane.

Supporting tests prove a same accepted key returns its defensive active receipt, same attempt cannot submit twice, accepted work starts in the background without waiting, success/expected failure/unexpected crash release exactly once, and a terminalization-callback failure faults the manager closed.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_background_job_manager.py::test_q03h_ac03_different_operation_is_busy_before_claim' `
  'tests/ox/test_background_job_manager.py::test_q03h_ac07_submission_failure_is_not_sent_without_provider_boundary' `
  -vv
```

Expected RED: `byte_mcp.ox.jobs` or the locked manager behavior is missing.

- [ ] **Step 3: Implement the manager with one lock and no queue**

Use `threading.Lock`, `threading.Thread`, a monotonically local lease token, and `uuid.uuid4().hex`. Reserve before caller claim. Start exactly one background daemon thread per accepted descriptor; the shared lane prevents concurrent job threads and never queues a later job. Copy bounded receipt/key data. Release the matching lease exactly once after terminalization and reject a stale release. Never retain exception objects or text.

- [ ] **Step 4: Run focused GREEN and the whole manager module**

```powershell
& $Python -m pytest `
  'tests/ox/test_background_job_manager.py::test_q03h_ac03_different_operation_is_busy_before_claim' `
  'tests/ox/test_background_job_manager.py::test_q03h_ac07_submission_failure_is_not_sent_without_provider_boundary' `
  tests/ox/test_background_job_manager.py `
  -q
```

- [ ] **Step 5: Validate, commit, and review Task 3**

```powershell
& $Python -m ruff check src/byte_mcp/ox/jobs.py tests/ox/test_background_job_manager.py
& $Python -m compileall -q src/byte_mcp/ox/jobs.py tests/ox/test_background_job_manager.py
git diff --check
git status --short
git add src/byte_mcp/ox/jobs.py tests/ox/test_background_job_manager.py
git commit -m "feat: add single-lane ox background job manager"
git show --check --stat --oneline HEAD
```

Fresh review attempts races around reserve/submit/release, duplicate submission, thread-start failure, callback failure, and same/different operation identity. No service integration begins until findings are resolved.

---

### Task 4: Background Initial Review and Explicit Initial Retry

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/ox/natural_service.py`
- Modify: `src/byte_mcp/ox/runtime.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/ox/test_long_provider_mcp_safety.py`
- Modify: `tests/ox/test_natural_review_architecture.py`
- Modify: `tests/ox/test_review_service.py`
- Modify: `tests/ox/test_mcp_surface.py`
- Modify: `tests/ox/test_runtime.py`
- Modify: `tests/ox/test_security_invariants.py`

**Interfaces:**
- `OXRuntime.initialize` creates the manager, calls owner-aware recovery, then constructs `OXReviewService(settings, evidence, client, audit, jobs)`.
- `transmit_review` and `retry_review` reserve, claim with `jobs.runtime_session_id`, persist identity/history, submit `_run_claimed_initial_attempt`, and return truthful launch receipts.
- Ordinary `TRANSMITTING` and `REVIEWED` replay remains local; retry still requires `approve=true, retry=true` at MCP and `renewed_approval=True` in service.

- [ ] **Step 1: Add initial ownership RED tests**

Add these primary node IDs:

- `test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider`
- `test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker`
- `test_q03h_ac04_same_active_operation_replays_without_duplicate_work`
- `test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence`
- `test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once`

AC01 and AC02 use a blocking fake provider with `entered`/`release` events. Assert the MCP result is available while blocked, cancellation after accepted launch does not affect the worker, one A001 exists, one worker enters, and provider count remains one after a replay. AC04 asserts the active receipt fields and exact zero deltas. AC11 records method/event order and requires `PROVIDER_REQUEST_STARTED`, one `json_mode=False` call, raw response, assistant thread, `COMPLETED`, metadata/audit, then lane release. AC12 tests denial without both controls and one A002 only after renewed approval.

Add a supporting AC08 integration test that raises a sentinel-bearing `OXTransportError` and proves the reconstructed attempt persists only `OUTCOME_UNKNOWN`, fixed kind, and safe timing.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider' `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac04_same_active_operation_replays_without_duplicate_work' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence' `
  'tests/ox/test_review_service.py::test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once' `
  -vv
```

Expected RED: the existing MCP call still waits for provider completion and runtime has no manager-owned launch contract.

- [ ] **Step 3: Inject one manager and refactor initial claim from execution**

Create the manager before startup recovery. Pass the owner into every initial claim and attempt identity. Build the receipt before thread start with `state="TRANSMITTING"`, `launch_accepted=True`, `replayed=False`, and `provider_request_performed=False`. On active replay return `launch_accepted=False`, `replayed=True`, and no provider result. Remove initial/retry `await asyncio.to_thread(...)` from `server.ox_review`; keep its public signature and mode validation unchanged.

- [ ] **Step 4: Implement the already-claimed natural worker**

The worker never calls `transmit_review` or `retry_review`. Write `PROVIDER_REQUEST_STARTED` immediately before one `complete(..., json_mode=False, ...)`. Persist raw response before content validation, assistant thread before completion, outcome before terminal metadata/audit, and release after terminalization. Submission failure is `NOT_SENT`; an escaping or ambiguous worker failure is `OUTCOME_UNKNOWN`.

- [ ] **Step 5: Run focused GREEN and initial regressions**

```powershell
& $Python -m pytest `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider' `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac04_same_active_operation_replays_without_duplicate_work' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence' `
  'tests/ox/test_review_service.py::test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once' `
  tests/ox/test_long_provider_mcp_safety.py `
  tests/ox/test_natural_review_architecture.py `
  tests/ox/test_review_service.py `
  tests/ox/test_runtime.py `
  tests/ox/test_mcp_surface.py `
  -q
```

- [ ] **Step 6: Validate, commit, and review Task 4**

```powershell
& $Python -m ruff check src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py src/byte_mcp/ox/runtime.py src/byte_mcp/server.py tests/ox/test_long_provider_mcp_safety.py tests/ox/test_natural_review_architecture.py tests/ox/test_review_service.py tests/ox/test_mcp_surface.py tests/ox/test_runtime.py tests/ox/test_security_invariants.py
& $Python -m compileall -q src/byte_mcp/ox src/byte_mcp/server.py tests/ox
git diff --check
git status --short
git add src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py src/byte_mcp/ox/runtime.py src/byte_mcp/server.py tests/ox/test_long_provider_mcp_safety.py tests/ox/test_natural_review_architecture.py tests/ox/test_review_service.py tests/ox/test_mcp_surface.py tests/ox/test_runtime.py tests/ox/test_security_invariants.py
git commit -m "feat: background initial ox review transmission"
git show --check --stat --oneline HEAD
```

Fresh review checks cancellation ownership, receipt truthfulness, claim-before-submit ordering, provider-start adjacency, exactly-once call, raw-response ordering, ambiguity handling, replay, retry approval, and absence of public-method re-entry. Resolve findings before continuation work.

---

### Task 5: Background Continuation and Explicit Continuation Retry

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/ox/test_continue_provider_mcp_safety.py`
- Modify: `tests/ox/test_review_followup.py`
- Modify: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- `continue_message` and `retry_continuation` use the same manager and `_run_claimed_continuation_attempt`.
- The immutable descriptor carries the exact claimed history digest; one new user message is persisted before accepted launch and never appended again by the worker.
- `record_findings` and `adjudicate` remain direct local operations.

- [ ] **Step 1: Add continuation RED tests**

Add two primary tests:

- `test_q03h_ac13_continuation_launch_preserves_history_and_natural_response`
  completes an initial fixture, blocks the continuation worker, and checks the
  prompt receipt; then require the exact history digest, one user message, one
  `json_mode=False` request, raw response before assistant message/outcome, and
  no duplicate on replay.
- `test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval`
  produces one failed continuation, rejects absent approval and stale identity,
  renews approval for the exact latest ID, and requires one new launch, attempt,
  and provider call.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_review_followup.py::test_q03h_ac13_continuation_launch_preserves_history_and_natural_response' `
  'tests/ox/test_review_followup.py::test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval' `
  -vv
```

Expected RED: continuation still runs provider work inline inside the service call and lacks launch receipts.

- [ ] **Step 3: Refactor continuation claim and worker paths**

Reserve by candidate/persisted history digest before claim. Persist the user turn exactly once in the claim stage. The worker receives the already-claimed descriptor, records the boundary, performs one natural request, writes raw response and assistant turn, terminalizes, and releases. Retry reconstructs the exact failed history and cannot accept replacement text.

- [ ] **Step 4: Run focused GREEN and continuation regressions**

```powershell
& $Python -m pytest `
  'tests/ox/test_review_followup.py::test_q03h_ac13_continuation_launch_preserves_history_and_natural_response' `
  'tests/ox/test_review_followup.py::test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval' `
  tests/ox/test_continue_provider_mcp_safety.py `
  tests/ox/test_review_followup.py `
  tests/ox/test_mcp_surface.py `
  tests/ox/test_natural_review_security.py `
  -q
```

- [ ] **Step 5: Validate, commit, and review Task 5**

```powershell
& $Python -m ruff check src/byte_mcp/ox/service.py src/byte_mcp/server.py tests/ox/test_continue_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py
& $Python -m compileall -q src/byte_mcp/ox/service.py src/byte_mcp/server.py tests/ox/test_continue_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py
git diff --check
git status --short
git add src/byte_mcp/ox/service.py src/byte_mcp/server.py tests/ox/test_continue_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py
git commit -m "feat: background ox continuation transmission"
git show --check --stat --oneline HEAD
```

Fresh review specifically checks duplicate user/assistant thread persistence, exact failed-history replay, stale retry identity, same-operation keying, cancellation, and no automatic retry. Resolve findings before Task 6.

---

### Task 6: Route All Revalidation Paths Through the Shared Lane

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/ox/natural_service.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/ox/test_revalidate_provider_mcp_safety.py`
- Modify: `tests/ox/test_review_followup.py`
- Modify: `tests/ox/test_natural_review_architecture.py`
- Modify: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- `transmit_blind_revalidation`, `retry_revalidation`, and
  `run_targeted_revalidation` submit `_run_claimed_revalidation_attempt`
  descriptors for blind approval, explicit retry of its exact prior
  blind/targeted phase, and targeted revalidation respectively.
- Preparation stays local. Targeted descriptors retain exact Byte-derived finding and adjudication provenance.
- The same manager rejects cross-type contention with initial or continuation work.

- [ ] **Step 1: Add revalidation RED tests**

- `test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode`
- `test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries`
- `test_q03h_ac17_targeted_revalidation_preserves_byte_provenance_and_launches_once`

AC15 blocks the fake provider and proves a prompt bounded receipt, one blind attempt, and `json_mode=False`. AC16 rejects ordinary replay/absent approval and launches exactly one explicit retry of the same phase. AC17 checks the descriptor/history contains only approved revalidation packet plus Byte-derived provenance and selected adjudications, then proves one natural call. Add a supporting cross-type test that holds initial work and rejects continuation, blind, and targeted launches before claim.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_revalidate_provider_mcp_safety.py::test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode' `
  'tests/ox/test_review_followup.py::test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac17_targeted_revalidation_preserves_byte_provenance_and_launches_once' `
  -vv
```

Expected RED: current revalidation methods still wait for `_perform_revalidation_attempt` and lack shared-lane receipts.

- [ ] **Step 3: Refactor blind, retry, and targeted claim paths**

Reserve the one global lane before revalidation claim. Persist owner, exact phase, history, and required thread once. Submit an already-claimed descriptor. The natural worker writes one provider-start event immediately before one `json_mode=False` call, then raw response, usable natural assistant response, terminal outcome, metadata/audit, and release. It never calls a public revalidation entry point.

- [ ] **Step 4: Run focused GREEN and all revalidation regressions**

```powershell
& $Python -m pytest `
  'tests/ox/test_revalidate_provider_mcp_safety.py::test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode' `
  'tests/ox/test_review_followup.py::test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac17_targeted_revalidation_preserves_byte_provenance_and_launches_once' `
  tests/ox/test_revalidate_provider_mcp_safety.py `
  tests/ox/test_review_followup.py `
  tests/ox/test_natural_review_architecture.py `
  tests/ox/test_mcp_surface.py `
  -q
```

- [ ] **Step 5: Validate, commit, and review Task 6**

```powershell
& $Python -m ruff check src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py src/byte_mcp/server.py tests/ox/test_revalidate_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_natural_review_architecture.py tests/ox/test_mcp_surface.py
& $Python -m compileall -q src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py src/byte_mcp/server.py tests/ox/test_revalidate_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_natural_review_architecture.py tests/ox/test_mcp_surface.py
git diff --check
git status --short
git add src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py src/byte_mcp/server.py tests/ox/test_revalidate_provider_mcp_safety.py tests/ox/test_review_followup.py tests/ox/test_natural_review_architecture.py tests/ox/test_mcp_surface.py
git commit -m "feat: background ox revalidation transmission"
git show --check --stat --oneline HEAD
```

Fresh review checks one lane rather than per-phase lanes, phase/retry binding, Byte provenance, natural mode, duplicate thread writes, receipt truthfulness, and zero implicit retry. Resolve findings before retrieval hardening.

---

### Task 7: Harden Retrieval, Security, and Historical Compatibility

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_mcp_surface.py`
- Modify: `tests/ox/test_security_invariants.py`
- Modify: `tests/ox/test_security_defense_in_depth.py`
- Modify: `tests/ox/test_natural_review_security.py`
- Modify: `tests/ox/test_byte_coding_audit.py`
- Verify unchanged: `scripts/Accept-OX-Q03G-HistoricalEvidence.ps1`

**Interfaces:**
- `get_review(review_id, view="attempts")` returns reconstructed bounded attempt metadata only.
- Historical attempts omit unavailable Q03H fields; no default value pretends the boundary was or was not crossed.
- Retrieval remains local and rejects configured credential material in any tampered evidence result.

- [ ] **Step 1: Add the attempts-view RED test**

Add `test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free`. Seed one
Q03H attempt and one legacy-shaped attempt under temporary evidence, make
`client.complete` fail if called, retrieve attempts, and assert only approved
fields. No credential, sentinel exception text, raw body, header, cookie, stack
text, or provider invocation may appear.

Keep AC19's single primary owner in `test_evidence.py`; here add supporting security and actual historical-script gates without assigning a second primary owner.

- [ ] **Step 2: Run focused RED**

```powershell
& $Python -m pytest `
  'tests/ox/test_mcp_surface.py::test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free' `
  -vv
```

Expected RED: attempts view lacks the bounded Q03H projection or leaks unfiltered reconstructed fields.

- [ ] **Step 3: Implement the explicit attempts projection**

Project only `attempt_id`, `manifest_sha256`, `phase` where existing, `outcome`, `runtime_session_id`, `provider_request_started`, `provider_started_at`, `provider_finished_at`, `elapsed_ms`, and `transport_failure_kind`. Omit missing historical fields. Apply the existing configured-credential rejection to the final result. Do not read provider response bodies to construct this view.

- [ ] **Step 4: Run focused GREEN, security, and historical acceptance**

```powershell
& $Python -m pytest `
  'tests/ox/test_mcp_surface.py::test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free' `
  tests/ox/test_security_invariants.py `
  tests/ox/test_security_defense_in_depth.py `
  tests/ox/test_natural_review_security.py `
  tests/ox/test_byte_coding_audit.py `
  tests/ox/test_evidence.py `
  -q

pwsh -NoProfile -ExecutionPolicy Bypass `
  -File '.\scripts\Accept-OX-Q03G-HistoricalEvidence.ps1' `
  -RepoRoot 'C:\Users\nolan\AIProjects\Byte-MCP-q03h' `
  -PythonPath 'C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe'
```

Expected historical result: `OX_Q03G_HISTORICAL_EVIDENCE_ACCEPTANCE: PASS`; the script must not change any fingerprint or create A002.

- [ ] **Step 5: Validate, commit, and review Task 7**

```powershell
& $Python -m ruff check src/byte_mcp/ox/service.py tests/ox/test_mcp_surface.py tests/ox/test_security_invariants.py tests/ox/test_security_defense_in_depth.py tests/ox/test_natural_review_security.py tests/ox/test_byte_coding_audit.py
& $Python -m compileall -q src/byte_mcp/ox/service.py tests/ox/test_mcp_surface.py tests/ox/test_security_invariants.py tests/ox/test_security_defense_in_depth.py tests/ox/test_natural_review_security.py tests/ox/test_byte_coding_audit.py
git diff --check
git status --short
git add src/byte_mcp/ox/service.py tests/ox/test_mcp_surface.py tests/ox/test_security_invariants.py tests/ox/test_security_defense_in_depth.py tests/ox/test_natural_review_security.py tests/ox/test_byte_coding_audit.py
git commit -m "test: harden q03h ox retrieval and history"
git show --check --stat --oneline HEAD
```

Fresh review checks allow-list projection, legacy omission semantics, provider-free retrieval, secret and exception-text suppression, actual historical fingerprints, and no mutation of the acceptance script.

---

### Task 8: Final Provider-Free Qualification

**Files:**
- Verify: all Q03H source, tests, documents, and unchanged qualification scripts
- Do not modify: `src/byte_mcp/wolfram/**`, `tests/wolfram/**`, `qualification/wolfram/**`, deployment/runtime evidence, or historical OX evidence

**Interfaces:**
- Owns no feature change.
- Q03H-AC20's primary owner is the existing `tests/wolfram/test_query_contract_v11.py::test_mcp_surface_exposes_only_bounded_assumption_authority`; the complete Wolfram suite is the required supporting gate.

- [ ] **Step 1: Run the focused Q03H primary-owner set**

```powershell
& $Python -m pytest `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider' `
  'tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker' `
  'tests/ox/test_background_job_manager.py::test_q03h_ac03_different_operation_is_busy_before_claim' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac04_same_active_operation_replays_without_duplicate_work' `
  'tests/ox/test_evidence.py::test_q03h_ac05_claimed_attempt_persists_runtime_session_id' `
  'tests/ox/test_evidence.py::test_q03h_ac06_provider_started_event_is_unique_and_bound_to_current_attempt' `
  'tests/ox/test_background_job_manager.py::test_q03h_ac07_submission_failure_is_not_sent_without_provider_boundary' `
  'tests/ox/test_client.py::test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed' `
  'tests/ox/test_client.py::test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind' `
  'tests/ox/test_orphaned_transmission_recovery.py::test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence' `
  'tests/ox/test_review_service.py::test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once' `
  'tests/ox/test_review_followup.py::test_q03h_ac13_continuation_launch_preserves_history_and_natural_response' `
  'tests/ox/test_review_followup.py::test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval' `
  'tests/ox/test_revalidate_provider_mcp_safety.py::test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode' `
  'tests/ox/test_review_followup.py::test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries' `
  'tests/ox/test_natural_review_architecture.py::test_q03h_ac17_targeted_revalidation_preserves_byte_provenance_and_launches_once' `
  'tests/ox/test_mcp_surface.py::test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free' `
  'tests/ox/test_evidence.py::test_q03h_ac19_legacy_q03g_evidence_reads_without_migration' `
  'tests/wolfram/test_query_contract_v11.py::test_mcp_surface_exposes_only_bounded_assumption_authority' `
  -vv
```

All twenty primary owners must pass in one fresh run.

- [ ] **Step 2: Run all OX tests**

```powershell
& $Python -m pytest tests\ox -q
```

- [ ] **Step 3: Run all Wolfram tests**

```powershell
& $Python -m pytest tests\wolfram -q
```

No Wolfram provider call is permitted.

- [ ] **Step 4: Run the full Python suite**

```powershell
& $Python -m pytest -q
```

- [ ] **Step 5: Run dependency, lint, and compile gates**

```powershell
& $Python -m pip check
& $Python -m ruff check .
& $Python -m compileall -q src tests scripts\mcp_smoke_test.py scripts\wolfram_qualification.py
```

These are the Python portions of `scripts\Check.ps1`, executed with the canonical dependency interpreter because the Q03H worktree intentionally has no local `.venv`.

- [ ] **Step 6: Run historical and launcher PowerShell gates**

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File '.\scripts\Accept-OX-Q03G-HistoricalEvidence.ps1' `
  -RepoRoot 'C:\Users\nolan\AIProjects\Byte-MCP-q03h' `
  -PythonPath 'C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe'

pwsh -NoProfile -ExecutionPolicy Bypass -File '.\scripts\Check-Launcher.ps1'
```

`scripts\Check-Launcher.ps1` is provider-free Pester. Do not run any qualification script whose inspected implementation performs a live provider request.

- [ ] **Step 7: Prove source boundaries and Git integrity**

```powershell
git diff --check e953b1eb3bb4893a98b6cf6fdfe9961873c708b7..HEAD
git diff --name-only e953b1eb3bb4893a98b6cf6fdfe9961873c708b7..HEAD -- src/byte_mcp/wolfram tests/wolfram qualification/wolfram
git status --short
git log --oneline --decorate e953b1eb3bb4893a98b6cf6fdfe9961873c708b7..HEAD
```

Expected: diff check succeeds; the Wolfram name-only command prints nothing; all intended commits appear; the worktree is clean.

- [ ] **Step 8: Review qualification evidence**

Record every exact command, exit code, test count, warning, and skipped gate. Confirm all acceptance owners passed and classify any missing evidence as unverified. Review the entire base-to-HEAD diff for provider calls, duplicate allocation, public-worker re-entry, automatic retry, raw exception text, historical mutation, Wolfram changes, and deployment changes.

- [ ] **Step 9: Commit only qualification-required tracked normalization**

No commit is expected when qualification is clean. If a provider-free gate requires a narrow Q03H documentation or test normalization, rerun the affected gate and commit only that reviewed change with:

```powershell
git commit -m "test: qualify q03h durable ox ownership"
```

Do not manufacture an empty commit and do not introduce feature behavior during qualification. A Q03H defect found here returns to the task that owns it under systematic debugging and a new RED/GREEN cycle.

- [ ] **Step 10: Final status**

Report either `Q03H LOCAL QUALIFICATION PASS`, `Q03H LOCAL QUALIFICATION FAILED — <gate>`, or `Q03H STOPPED — <reason>`. Never claim deployed or live acceptance. If green, state exactly: `Q03H is locally qualified only. Runtime promotion and any live OX canary require fresh explicit Nolan authorization.`

## Acceptance ownership matrix

This table is the normative one-to-one primary-owner registry. Supporting tests may exercise the same invariant but must not claim primary ownership for the ID.

| Acceptance ID | Exactly one primary owning test | Production mutation the test must catch |
|---|---|---|
| Q03H-AC01 | `tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac01_initial_launch_receipt_returns_before_blocked_provider` | Awaiting provider completion before returning the launch receipt. |
| Q03H-AC02 | `tests/ox/test_long_provider_mcp_safety.py::test_q03h_ac02_cancelled_mcp_task_does_not_cancel_or_duplicate_worker` | Binding worker lifetime to MCP cancellation or launching a duplicate after cancellation. |
| Q03H-AC03 | `tests/ox/test_background_job_manager.py::test_q03h_ac03_different_operation_is_busy_before_claim` | Allowing another operation to claim, queue, or call the provider while the lane is occupied. |
| Q03H-AC04 | `tests/ox/test_natural_review_architecture.py::test_q03h_ac04_same_active_operation_replays_without_duplicate_work` | Allocating a new attempt, worker, or call instead of returning the active local receipt. |
| Q03H-AC05 | `tests/ox/test_evidence.py::test_q03h_ac05_claimed_attempt_persists_runtime_session_id` | Creating any new Q03H transmission intent without its runtime owner. |
| Q03H-AC06 | `tests/ox/test_evidence.py::test_q03h_ac06_provider_started_event_is_unique_and_bound_to_current_attempt` | Omitting, duplicating, misbinding, or reordering the provider-boundary event. |
| Q03H-AC07 | `tests/ox/test_background_job_manager.py::test_q03h_ac07_submission_failure_is_not_sent_without_provider_boundary` | Leaving a failed submission transmitting, crossing the boundary, or retaining the lane. |
| Q03H-AC08 | `tests/ox/test_client.py::test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed` | Losing `OUTCOME_UNKNOWN`, safe kind/timing, or retaining arbitrary exception text. |
| Q03H-AC09 | `tests/ox/test_client.py::test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind` | Collapsing HTTPX categories or changing their authoritative outcomes. |
| Q03H-AC10 | `tests/ox/test_orphaned_transmission_recovery.py::test_q03h_ac10_prior_runtime_transmission_recovers_unknown_without_retry` | Waiting for stale horizon, resuming, retrying, or allocating during cross-runtime recovery. |
| Q03H-AC11 | `tests/ox/test_natural_review_architecture.py::test_q03h_ac11_initial_worker_is_natural_exactly_once_and_orders_evidence` | JSON coercion, multiple provider calls, or raw-response/thread/outcome ordering regression. |
| Q03H-AC12 | `tests/ox/test_review_service.py::test_q03h_ac12_initial_retry_requires_renewed_approval_and_launches_once` | Implicit retry, missing renewed approval, or more than one retry launch. |
| Q03H-AC13 | `tests/ox/test_review_followup.py::test_q03h_ac13_continuation_launch_preserves_history_and_natural_response` | Lost history binding, duplicate user turn, JSON mode, or duplicate continuation call. |
| Q03H-AC14 | `tests/ox/test_review_followup.py::test_q03h_ac14_continuation_retry_requires_latest_attempt_and_approval` | Retrying stale/replaced history, absent approval, or launching twice. |
| Q03H-AC15 | `tests/ox/test_revalidate_provider_mcp_safety.py::test_q03h_ac15_blind_revalidation_launches_promptly_in_natural_mode` | Waiting for blind completion, JSON mode, or multiple blind launches. |
| Q03H-AC16 | `tests/ox/test_review_followup.py::test_q03h_ac16_revalidation_retry_requires_renewed_approval_and_never_auto_retries` | Revalidation resend without explicit renewed approval or automatic retry. |
| Q03H-AC17 | `tests/ox/test_natural_review_architecture.py::test_q03h_ac17_targeted_revalidation_preserves_byte_provenance_and_launches_once` | Dropping Byte provenance, treating OX prose as findings, JSON mode, or duplicate targeted call. |
| Q03H-AC18 | `tests/ox/test_mcp_surface.py::test_q03h_ac18_attempts_view_is_bounded_local_and_secret_free` | Provider contact or leakage of credentials, exception text, raw bodies, or unbounded fields. |
| Q03H-AC19 | `tests/ox/test_evidence.py::test_q03h_ac19_legacy_q03g_evidence_reads_without_migration` | Requiring new fields, rewriting legacy files, or breaking prior evidence semantics. |
| Q03H-AC20 | `tests/wolfram/test_query_contract_v11.py::test_mcp_surface_exposes_only_bounded_assumption_authority` | Changing the Wolfram V1.1 public schema while implementing Q03H. |

## Per-checkpoint review gate

After every task commit:

1. Verify `git status --short` is empty.
2. Review `git show --check --stat --oneline HEAD` and the complete commit diff.
3. Compare the commit to the spec and its acceptance owners.
4. Inspect tests for false positives, sleep-only timing, mocked-away ownership, or a fake call mislabeled as live provider evidence.
5. Inspect races, deadlocks, lane release, evidence order, replay, and attempt allocation.
6. Inspect every `NOT_SENT` decision for proof the provider boundary was not crossed.
7. Inspect approval and retry controls.
8. Search the diff for credential, header, cookie, exception message, stack, raw body, daemon, scheduler, deployment, Wolfram, merge, or push changes.
9. Report findings by severity with exact file/line references, or explicitly report no findings.
10. Repair within the owning task and re-run its RED/GREEN and regression gates before advancing.

## Stop and handoff rules

Stop without workaround if repository identity changes, unexplained dirty work appears, immutable evidence conflicts with the design, provider/runtime/deployment action is required, a real provider is needed, a secret would be exposed, an unauthorized retry becomes possible, concurrency proof cannot be deterministic, three distinct repairs fail on one architecture problem, shared-interface scope must broaden, or the protected verification reserve is reached.

The stop report includes task and step, repository/branch/HEAD, dirty state, exact failure evidence, safe completed work, smallest Nolan decision required, and confirmation that no provider, retry, runtime, deployment, merge, or push action occurred.

## Plan self-review

### Spec coverage

- Runtime-owned work and MCP cancellation independence: Tasks 3–6.
- One lane, no queue, cross-operation busy, same-operation replay: Tasks 3–6.
- Runtime owner persisted atomically with intent: Task 2; required at every production claim in Tasks 4–6.
- Provider boundary uniqueness and evidence ordering: Tasks 2 and 4–6.
- Fixed transport classification, outcomes, and bounded timing: Tasks 1–2 and initial integration in Task 4.
- Foreign-runtime recovery before legacy stale horizon: Task 2; runtime wiring in Task 4.
- Initial review and explicit retry: Task 4.
- Continuation and exact-attempt retry: Task 5.
- Blind, retry, and targeted revalidation: Task 6.
- Natural `json_mode=False` and Byte-derived provenance: Tasks 4–6.
- Provider-free attempts retrieval and security: Task 7.
- Historical Q03G readability and immutable fingerprints: Tasks 2, 7, and 8.
- Wolfram isolation and all broad provider-free gates: Task 8.
- Explicit approval and no automatic retry: global constraints plus Tasks 4–6.
- No runtime promotion, deployment, merge, push, daemon control, Scheduled Task change, or live canary: global constraints and Task 8 stop language.

### Placeholder scan

Every task names concrete files, interfaces, primary test node IDs, focused RED/GREEN commands, expected failure class, implementation boundary, regression gates, commit message, and review focus. No unresolved implementation marker remains.

### Type and naming consistency

The plan consistently uses `OXTransportFailureKind`, `OXOperationKey`, `OXLaunchDescriptor`, `OXActiveLaunch`, `OXLaneLease`, `OXProviderJobManager`, `runtime_session_id`, `PROVIDER_REQUEST_STARTED`, `transport_failure_kind`, `provider_started_at`, `provider_finished_at`, and `elapsed_ms`. Public OX tool and service entry-point names remain the live base names. All acceptance IDs have one and only one primary node in the ownership matrix.
