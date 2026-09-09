# NVIDIA-02 Governed Nemotron Lightning Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and offline-qualify one governed NVIDIA Nemotron Lightning canary lifecycle that persists exact prepared request identity, binds explicit human approval to that identity, records durable provider-start evidence, permits exactly one NVIDIA inference transmission, and terminalizes without retry or fallback.

**Architecture:** Reuse the NVIDIA-01 `PreparedProviderRequest`, `ProviderTransmissionContext`, `execute_once()`, and `execute_prepared_nvidia_chat()` contracts unchanged. Add a narrow NVIDIA-specific evidence store and canary orchestrator plus a script operator surface; keep OX, Wolfram, the MCP server, catalog, registry, dependencies, and provider-neutral transport frozen unless a focused RED proves a predecessor defect.

**Tech Stack:** Python 3.12+, stdlib filesystem/JSON/hash/argparse/asyncio primitives, existing `httpx>=0.28.1,<1`, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md`

## Global Constraints

- Qualified NVIDIA-01 predecessor is exactly `29daea6ef68ebb3d46031ce302b0108617bd1221`.
- NVIDIA-02 design commit is exactly `3c381944bc117373366b647a92f02d52a9e8adb3` before this plan commit.
- Work only on `feat/nvidia-provider-n02-lightning-canary` or an isolated worktree linked to it.
- No live NVIDIA catalog request during implementation or offline qualification.
- No live NVIDIA inference request during implementation or offline qualification.
- No OX provider request, Wolfram provider request, or other external model/provider request.
- No automatic retry, manual retry-in-place, backoff, redirect following, request replay, model fallback, or provider fallback.
- The live canary model is fixed to `nvidia/nemotron-3.5-lightning-30b-a3b`.
- The live canary endpoint is fixed to `POST https://integrate.api.nvidia.com/v1/chat/completions` through the qualified NVIDIA-01 adapter.
- The probe is fixed to `Reply with exactly: BYTE_NVIDIA_CANARY_OK`.
- Request generation is fixed to `temperature=1.0`, `top_p=0.95`, `max_tokens=64`, `n=1`, `stream=false`.
- `NVIDIA_API_KEY` is never accepted as a CLI argument and is never persisted in Git, evidence, logs, hashes, reprs, or tests.
- `prepare` and `inspect` must not call `NvidiaHostedSettings.load()` and must not access `NVIDIA_API_KEY`.
- `transmit` may load `NvidiaHostedSettings` only before durable `PROVIDER_START`.
- Exact persisted `request-body.bin` bytes are the bytes used to reconstruct the request supplied to NVIDIA-01; do not rebuild the request from prompt parameters after approval.
- `PROVIDER_START` must be appended, flushed, and fsynced before the single call to `execute_prepared_nvidia_chat()`.
- After `PROVIDER_START` and before the adapter call, perform no filesystem read, credential lookup, catalog operation, routing decision, prompt reconstruction, or provider/model call.
- Once `PROVIDER_START` is durable, the one authorization is consumed regardless of `COMPLETED`, `REJECTED`, `NOT_SENT`, `OUTCOME_UNKNOWN`, protocol failure, crash, or terminal-evidence failure.
- A started canary with no terminal event is ambiguous and must never retransmit in NVIDIA-02.
- No `/v1/models` preflight.
- No NVIDIA inference MCP registration.
- No runtime promotion/restart.
- No merge to `main`.
- No new dependency without amending the approved design first.
- Frozen paths: `src/byte_mcp/ox/**`, `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, `src/byte_mcp/nvidia/catalog.py`, `src/byte_mcp/nvidia/registry.py`, `pyproject.toml`.
- Treat `src/byte_mcp/providers/requests.py`, `src/byte_mcp/providers/transport.py`, and `src/byte_mcp/nvidia/chat.py` as qualified predecessor contracts. Modify them only if a focused RED proves a predecessor defect and record the scope exception explicitly.
- Use strict TDD for production behavior: RED test first, verify the expected failure, smallest GREEN, focused verification, then commit.
- Do not run the full repository test suite after every task. Use focused tests per task, then full gates in Task 8.
- Before execution, use `superpowers:using-git-worktrees`; implementation is recommended via `superpowers:subagent-driven-development`.

---

## File Map

### New production files

- `src/byte_mcp/nvidia/canary_evidence.py` — local evidence-root resolution, immutable manifest/body persistence, append-only lifecycle events, lifecycle reconstruction, lock files, and integrity validation.
- `src/byte_mcp/nvidia/canary.py` — fixed Lightning canary request preparation, inspection, authorization/transmit orchestration, provider-start adjacency, and terminalization.
- `scripts/nvidia_lightning_canary.py` — narrow `prepare`, `inspect`, and `transmit` operator commands; no credential argument.

### Modified production file

- `src/byte_mcp/nvidia/__init__.py` — exports only the public NVIDIA-02 canary contracts needed by tests/operator code.

### New tests

- `tests/nvidia/test_canary_evidence.py` — persistence, integrity, event ordering, locking, crash-state reconstruction.
- `tests/nvidia/test_canary.py` — fixed request, prepare/inspect, transmit preflight, provider-start ordering, one-call terminalization.
- `tests/nvidia/test_n02_security_invariants.py` — no secrets, no retries/fallbacks, no OX/Wolfram/server/catalog/registry coupling, exact-byte and zero-call invariants.
- `tests/nvidia/test_canary_cli.py` — CLI shape, safe output, and credential-blind prepare/inspect behavior.

### Documentation

- Existing approved spec: `docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md`.
- This plan: `docs/superpowers/plans/2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md`.

---

### Task 1: Durable Canary Evidence Contracts and Root Resolution

**Files:**
- Create: `src/byte_mcp/nvidia/canary_evidence.py`
- Create: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: stdlib `Path`, `os`, `json`, `hashlib`, `re`, `datetime`; `PreparedProviderRequest` from `byte_mcp.providers`.
- Produces:

```python
NVIDIA_CANARY_SCHEMA = "byte-mcp-nvidia-canary-v1"
NVIDIA_CANARY_ID_PATTERN = r"NVC-[0-9]{6}"

@dataclass(frozen=True, slots=True)
class NvidiaCanaryManifest:
    schema: str
    canary_id: str
    provider_id: str
    model_id: str
    method: str
    target_origin: str
    endpoint_path: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    probe_expected_text: str
    qualified_predecessor_sha: str

@dataclass(frozen=True, slots=True)
class NvidiaCanarySnapshot:
    manifest: NvidiaCanaryManifest
    request_body: bytes
    events: tuple[dict[str, object], ...]
    authorized_at: str | None
    provider_started_at: str | None
    terminal_event: dict[str, object] | None

class NvidiaCanaryEvidenceError(ByteMCPError):
    pass

class NvidiaCanaryLockError(ByteMCPError):
    pass

class NvidiaCanaryEvidenceStore:
    def __init__(self, root: Path) -> None: ...
    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "NvidiaCanaryEvidenceStore": ...
    def prepare(self, prepared_request: PreparedProviderRequest, *, probe_expected_text: str, qualified_predecessor_sha: str, prepared_at: str) -> NvidiaCanaryManifest: ...
    def load(self, canary_id: str) -> NvidiaCanarySnapshot: ...
    def append_authorized(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None: ...
    def append_provider_start(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None: ...
    def append_terminal(self, canary_id: str, event: Mapping[str, object]) -> None: ...
    def transmit_lock(self, canary_id: str) -> ContextManager[None]: ...
```

Evidence layout:

```text
<root>/canaries/NVC-000001/
  manifest.json
  request-body.bin
  events.jsonl
```

Environment resolution:

```text
BYTE_MCP_NVIDIA_EVIDENCE_DIR set -> Path(value)
Windows default -> %LOCALAPPDATA%/Byte-MCP/nvidia
Unix with XDG_DATA_HOME -> $XDG_DATA_HOME/byte-mcp/nvidia
Unix fallback -> ~/.local/share/byte-mcp/nvidia
```

- [ ] **Step 1: Write RED tests for root resolution and safe contracts**

Add tests that monkeypatch environment/platform helpers and assert exact roots, reject empty/relative-invalid state only where the implementation contract requires it, validate `NVC-[0-9]{6}`, require timezone-aware ISO timestamps, and ensure manifest/snapshot reprs contain no request body or credential field.

Representative test shape:

```python
def test_store_uses_explicit_evidence_root(monkeypatch, tmp_path):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    store = NvidiaCanaryEvidenceStore.from_environment()
    assert store.root == tmp_path / "evidence"


def test_manifest_rejects_invalid_canary_id():
    with pytest.raises(ValueError):
        NvidiaCanaryManifest(
            schema=NVIDIA_CANARY_SCHEMA,
            canary_id="NVC-1",
            provider_id="nvidia-api-catalog",
            model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
            method="POST",
            target_origin="https://integrate.api.nvidia.com",
            endpoint_path="/v1/chat/completions",
            payload_sha256="a" * 64,
            request_sha256="b" * 64,
            body_bytes=1,
            prepared_at="2026-09-09T12:00:00+00:00",
            probe_expected_text="BYTE_NVIDIA_CANARY_OK",
            qualified_predecessor_sha="29daea6ef68ebb3d46031ce302b0108617bd1221",
        )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: collection/import failure because `byte_mcp.nvidia.canary_evidence` does not exist.

- [ ] **Step 3: Implement the minimal contracts and environment resolver**

Implement constants, dataclasses, bounded validation, safe errors, and `NvidiaCanaryEvidenceStore.root`. Do not implement persistence methods beyond raising `NotImplementedError` only if they are not exercised by Task 1 tests; before Task 1 commit, remove any such placeholder by either implementing the method in the task where it is first tested or omitting the method until that task. The committed Task 1 surface must contain no `TODO`, `TBD`, `pass`, or `NotImplementedError`.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
git commit -m "feat: add NVIDIA canary evidence contracts"
```

---

### Task 2: Immutable Preparation, Integrity Reconstruction, and Local Locks

**Files:**
- Modify: `src/byte_mcp/nvidia/canary_evidence.py`
- Modify: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: Task 1 contracts and `validate_prepared_provider_request_integrity()`.
- Produces fully working methods:

```python
NvidiaCanaryEvidenceStore.prepare(...)
NvidiaCanaryEvidenceStore.load(canary_id)
NvidiaCanaryEvidenceStore.append_authorized(...)
NvidiaCanaryEvidenceStore.append_provider_start(...)
NvidiaCanaryEvidenceStore.append_terminal(...)
NvidiaCanaryEvidenceStore.transmit_lock(canary_id)
```

Private helpers must use create-once / append-only semantics:

```python
def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _append_fsynced_jsonl(path: Path, event: Mapping[str, object]) -> None:
    payload = canonical_json(event) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(payload)
        os.fsync(handle.fileno())
```

Use a root-level exclusive lock file for allocation/preparation and a per-canary exclusive lock file for transmit. Acquire with `os.O_CREAT | os.O_EXCL`; if a lock already exists, raise `NvidiaCanaryLockError`. Remove the lock on normal context-manager exit. A crash-stale lock is not auto-recovered in NVIDIA-02.

Preparation allocation is deterministic: scan `NVC-000001` upward, choose the first absent canary directory while holding the prepare lock, create the directory once, then write immutable evidence. In a fresh production evidence root the first identity is therefore exactly `NVC-000001`.

Lifecycle event schemas:

```json
{"event_type":"CANARY_PREPARED","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
{"event_type":"CANARY_AUTHORIZED","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
{"event_type":"PROVIDER_START","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
```

`CANARY_TERMINAL` accepts the fixed bounded terminal schema defined in Task 5 and must reject arbitrary extra keys.

- [ ] **Step 1: Write RED tests for immutable persistence and lifecycle validation**

Cover:
- exact `request-body.bin` bytes equal `PreparedProviderRequest.body_bytes`;
- manifest byte count/hash/request metadata match the prepared request;
- manifest and body cannot be overwritten;
- concurrent/duplicate prepare cannot claim the same NVC directory;
- `load()` recomputes payload SHA-256 and reconstructs `PreparedProviderRequest`, then calls `validate_prepared_provider_request_integrity()`;
- tampered body or manifest fails closed;
- malformed JSONL or invalid event order fails closed;
- at most one authorization, provider-start, and terminal event;
- terminal before provider-start rejected;
- provider-start without terminal reconstructs as consumed/ambiguous;
- lock contention raises locally.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: new persistence/lifecycle tests fail because methods are absent or incomplete.

- [ ] **Step 3: Implement canonical immutable persistence and reconstruction**

Use canonical JSON:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
```

`load()` must construct:

```python
PreparedProviderRequest(
    provider_id=manifest.provider_id,
    method=manifest.method,
    target_origin=manifest.target_origin,
    endpoint_path=manifest.endpoint_path,
    model_id=manifest.model_id,
    body_bytes=request_body,
    payload_sha256=manifest.payload_sha256,
    request_sha256=manifest.request_sha256,
)
```

and validate it before returning a snapshot.

Do not persist response body, API key, authorization header, environment dump, or raw exception strings.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
git commit -m "feat: persist immutable NVIDIA canary evidence"
```

---

### Task 3: Fixed Lightning Prepare and Read-Only Inspect Orchestration

**Files:**
- Create: `src/byte_mcp/nvidia/canary.py`
- Create: `tests/nvidia/test_canary.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `prepare_nvidia_chat_request()`, `NvidiaCanaryEvidenceStore`.
- Produces:

```python
NVIDIA_LIGHTNING_CANARY_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_LIGHTNING_CANARY_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
NVIDIA_01_QUALIFIED_SHA = "29daea6ef68ebb3d46031ce302b0108617bd1221"

@dataclass(frozen=True, slots=True)
class NvidiaCanaryPrepareReceipt:
    canary_id: str
    provider_id: str
    model_id: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    evidence_root: str

@dataclass(frozen=True, slots=True)
class NvidiaCanaryInspection:
    canary_id: str
    provider_id: str
    model_id: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    probe_text: str
    provider_started_at: str | None
    has_terminal_event: bool


def prepare_lightning_canary(store: NvidiaCanaryEvidenceStore, *, now: Callable[[], datetime] = ...) -> NvidiaCanaryPrepareReceipt: ...
def inspect_lightning_canary(store: NvidiaCanaryEvidenceStore, canary_id: str) -> NvidiaCanaryInspection: ...
```

Fixed preparation call:

```python
prepare_nvidia_chat_request(
    model_id=NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    messages=[{"role": "user", "content": NVIDIA_LIGHTNING_CANARY_PROMPT}],
    temperature=1.0,
    top_p=0.95,
    max_tokens=64,
)
```

- [ ] **Step 1: Write RED tests**

Prove:
- exact model/prompt/temperature/top_p/max_tokens;
- body contains generated `n=1` and `stream=false` from NVIDIA-01;
- `prepare_lightning_canary()` succeeds with `NVIDIA_API_KEY` absent;
- prepare performs zero HTTP calls and never invokes `NvidiaHostedSettings.load()`;
- inspection is read-only, revalidates evidence via `store.load()`, and never loads credentials;
- inspection reports provider-start/terminal state without exposing body bytes or secrets.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

Expected: import/attribute failure for the new canary API.

- [ ] **Step 3: Implement minimal prepare/inspect orchestration**

Use timezone-aware UTC timestamps only:

```python
prepared_at = now().astimezone(UTC).isoformat()
```

Pass `NVIDIA_01_QUALIFIED_SHA` into evidence preparation. Do not import or call the catalog client, OX, Wolfram, or `NvidiaHostedSettings.load()` in prepare/inspect.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
git commit -m "feat: prepare and inspect NVIDIA Lightning canary"
```

---

### Task 4: Authorization Preflight, Duplicate-Send Lock, and Provider-Start Adjacency

**Files:**
- Modify: `src/byte_mcp/nvidia/canary.py`
- Modify: `tests/nvidia/test_canary.py`

**Interfaces:**
- Consumes: `NvidiaHostedSettings.load()`, `ProviderTransmissionContext`, `execute_prepared_nvidia_chat()`.
- Produces:

```python
@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanaryTransmissionResult:
    canary_id: str
    request_sha256: str
    attempt_outcome: ProviderAttemptOutcome
    model_id: str
    semantic_probe_match: bool | None
    response_content: str | None = field(default=None, repr=False)

async def transmit_lightning_canary(
    store: NvidiaCanaryEvidenceStore,
    *,
    canary_id: str,
    expected_request_sha256: str,
    approve: bool,
    settings_loader: Callable[[], NvidiaHostedSettings] = NvidiaHostedSettings.load,
    executor: Callable[..., Awaitable[NvidiaChatResult]] = execute_prepared_nvidia_chat,
    now: Callable[[], datetime] = ...,
) -> NvidiaCanaryTransmissionResult: ...
```

Pre-provider ordering inside `store.transmit_lock(canary_id)`:

```text
load/revalidate snapshot
validate approve == True
validate expected request hash
validate no prior provider-start
validate no terminal event
load NvidiaHostedSettings
validate api_key configured and timeouts constructed
reconstruct exact PreparedProviderRequest from persisted body/manifest
perform all deterministic local checks
append CANARY_AUTHORIZED if absent; if already present it must match the same hash
choose provider_started_at in memory
append + fsync PROVIDER_START with exactly that timestamp/hash
construct ProviderTransmissionContext in memory
call executor exactly once
```

After `PROVIDER_START`, there must be no store read, path read, settings load, catalog lookup, route selection, or prompt reconstruction before `executor(...)`.

- [ ] **Step 1: Write RED preflight and ordering tests**

Cover zero-call cases:
- `approve=False`;
- wrong expected request hash;
- missing canary;
- tampered body/manifest;
- wrong provider/model/origin/path;
- missing API key;
- invalid timeout configuration;
- existing provider-start;
- existing terminal event;
- transmit lock contention.

Ordering test: inject an executor that inspects the already-persisted `events.jsonl` when invoked and asserts the final event is `PROVIDER_START`, and that `ProviderTransmissionContext.provider_started_at` equals that event's `recorded_at` and expected hash equals manifest hash.

Duplicate invocation test: two concurrent local transmit calls against one prepared canary must produce at most one executor invocation and one `PROVIDER_START`.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

Expected: new transmit tests fail because transmit orchestration is absent.

- [ ] **Step 3: Implement preflight and exact provider-start adjacency**

Use the persisted `request_body` and manifest fields to reconstruct `PreparedProviderRequest`; call `validate_prepared_provider_request_integrity()` before provider-start. Instantiate `NvidiaHostedSettings` before provider-start and require `settings.api_key is not None`.

After fsync of `PROVIDER_START`, perform only:

```python
context = ProviderTransmissionContext(
    provider_started_at=provider_started_at,
    expected_request_sha256=snapshot.manifest.request_sha256,
)
result = await executor(prepared_request, context, settings)
```

No filesystem access may be introduced between those statements and the provider-start append except the append/fsync itself.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
```

Expected: all preflight/order tests pass using injected executors only; provider calls remain zero.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
git commit -m "feat: govern NVIDIA canary provider start"
```

---

### Task 5: Bounded Terminalization and Crash/Outcome Semantics

**Files:**
- Modify: `src/byte_mcp/nvidia/canary.py`
- Modify: `src/byte_mcp/nvidia/canary_evidence.py`
- Modify: `tests/nvidia/test_canary.py`
- Modify: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: `NvidiaChatResult`, `NvidiaChatError`, `ProviderTransportError`, `ProviderAttemptOutcome`.
- Produces a fixed terminal event schema containing only:

```text
event_type = CANARY_TERMINAL
canary_id
request_sha256
provider_id
model_id
provider_started_at
provider_finished_at
attempt_outcome
nvidia_failure_kind
transport_failure_kind
http_status_code
response_headers_received
response_body_started
decoded_body_bytes_received
elapsed_ms
finish_reason
response_id
prompt_tokens
completion_tokens
total_tokens
semantic_probe_match
recorded_at
```

No raw response content is durable.

Success semantics:

```python
semantic_probe_match = result.content == NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT
attempt_outcome = ProviderAttemptOutcome.COMPLETED
```

Known failure terminalization:
- `NvidiaChatError`: use its `attempt_outcome`, bounded `kind.value`, and transport observation.
- `ProviderTransportError`: use its `attempt_outcome`, bounded transport failure kind and observation.
- Do not catch arbitrary `Exception` after provider-start. An unexpected crash/exception intentionally leaves `PROVIDER_START` without terminal evidence, which blocks retransmission as ambiguous.

- [ ] **Step 1: Write RED terminalization tests**

Inject executor outcomes for:
- successful exact semantic match;
- successful nonmatching content;
- HTTP `REJECTED` represented by `NvidiaChatError`;
- protocol failure after complete 2xx represented by `NvidiaChatError` with `COMPLETED`;
- `NOT_SENT` transport error after provider-start;
- `OUTCOME_UNKNOWN` transport error;
- unexpected exception after provider-start leaves no terminal event and future transmit is blocked.

Assert exactly one terminal event, no retry, no second executor call, and no response body/credential in `events.jsonl`.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
```

Expected: terminalization tests fail until fixed schema and exception mapping exist.

- [ ] **Step 3: Implement minimal bounded terminalization**

Create one helper in `canary.py` that maps `NvidiaChatResult`, `NvidiaChatError`, or `ProviderTransportError` into the fixed terminal event dictionary. Persist once through `store.append_terminal()` while the transmit lock remains held. Re-raise bounded NVIDIA/transport errors after terminal persistence so the operator sees the existing safe error contract; return `NvidiaCanaryTransmissionResult` only on parsed success.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
git commit -m "feat: terminalize NVIDIA canary outcomes"
```

---

### Task 6: Narrow CLI Operator Surface

**Files:**
- Create: `scripts/nvidia_lightning_canary.py`
- Create: `tests/nvidia/test_canary_cli.py`

**Interfaces:**
- Consumes: `NvidiaCanaryEvidenceStore.from_environment()`, `prepare_lightning_canary()`, `inspect_lightning_canary()`, `transmit_lightning_canary()`.
- Produces commands:

```text
python scripts/nvidia_lightning_canary.py prepare
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 <64-lowercase-hex> --approve
```

No `--api-key`, `--token`, `--credential`, model override, endpoint override, prompt override, retry flag, or fallback flag exists.

Output is canonical/sorted JSON metadata. `prepare` and `inspect` never output request body bytes. `inspect` may output the fixed probe text. Successful `transmit` may output immediate `response_content`, but that content must not be written into durable evidence.

- [ ] **Step 1: Write RED CLI tests**

Use subprocess or direct `main(argv)` injection with temporary `BYTE_MCP_NVIDIA_EVIDENCE_DIR`. Prove:
- exact three subcommands;
- `prepare` works with `NVIDIA_API_KEY` absent;
- `inspect` works with key absent;
- parser rejects `--api-key` and unknown model/endpoint options;
- transmit requires all three: canary ID, expected request hash, and `--approve`;
- no command contains retry/fallback switches;
- JSON output contains only bounded expected keys.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py -q
```

Expected: failure because the script does not exist.

- [ ] **Step 3: Implement the CLI**

Use `argparse` only. `main(argv: Sequence[str] | None = None) -> int` dispatches commands. `transmit` uses `asyncio.run(transmit_lightning_canary(...))`. Convert bounded dataclasses to explicit dictionaries; do not dump `__dict__`, environment, exception objects, or settings.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
python -m ruff format --check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
```

Expected: all pass, provider calls zero.

- [ ] **Step 5: Commit**

```powershell
git add scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
git commit -m "feat: add NVIDIA Lightning canary CLI"
```

---

### Task 7: Security, Isolation, and Exactly-One Invariant Suite

**Files:**
- Create: `tests/nvidia/test_n02_security_invariants.py`
- Modify production files only if a new RED proves a real NVIDIA-02 defect.

**Interfaces:**
- Consumes all NVIDIA-02 production surfaces.
- Produces regression invariants, no new public production API expected.

- [ ] **Step 1: Write adversarial RED/invariant tests**

Prove:
- `canary.py` / `canary_evidence.py` import neither `byte_mcp.ox` nor `byte_mcp.wolfram`;
- `server.py` does not import/register NVIDIA canary/inference;
- `catalog.py` and `registry.py` are not used by transmit;
- source contains no retry/backoff/sleep/fallback/request replay implementation;
- CLI exposes no API-key/model/endpoint/prompt override;
- tracked NVIDIA-02 files contain no strings matching `nvapi-` test secrets;
- evidence files never contain injected secret sentinel or Authorization header;
- prepare/inspect never call settings loader;
- exact persisted body is the body inside reconstructed `PreparedProviderRequest` passed to the injected executor;
- stale/wrong request hash produces zero executor calls;
- wrong provider/model/origin/path produces zero executor calls;
- two transmit calls cannot produce two provider starts or two executor calls;
- provider-start without terminal blocks forever in NVIDIA-02;
- no A002/retry path exists;
- no `/v1/models` request exists anywhere in canary code;
- `NVIDIA_API_KEY` is read only through `NvidiaHostedSettings.load()` on transmit.

- [ ] **Step 2: Run invariants**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py -q
```

Expected: PASS if Tasks 1-6 satisfy the frozen design. If a test fails, treat it as RED evidence for a focused repair.

- [ ] **Step 3: Repair only proven defects**

For each failure, make the smallest production change addressing the exact invariant. Do not refactor unrelated code. If repair would require a frozen OX/Wolfram/server/catalog/registry/dependency change or a live provider call, STOP and amend the design instead.

- [ ] **Step 4: Re-run scoped regression**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py tests/nvidia/test_canary_cli.py -q
python -m ruff check src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/nvidia/test_n02_security_invariants.py src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia
git commit -m "test: freeze NVIDIA-02 canary security invariants"
```

Before committing, inspect `git diff --cached --name-only`; if unrelated/frozen files appear, unstage them and STOP to investigate.

---

### Task 8: Final Offline Qualification and Exact-Head CI

**Files:**
- No production changes expected.
- Formatting-only repair to NVIDIA-02 changed files is allowed if the baseline-aware Ruff format gate identifies new NVIDIA-02 formatting debt.

**Interfaces:**
- Consumes the complete NVIDIA-02 branch.
- Produces an offline-qualified branch eligible to prepare `NVC-000001`; it does **not** authorize live transmission.

- [ ] **Step 1: Verify branch lineage and scope**

```powershell
$N01 = "29daea6ef68ebb3d46031ce302b0108617bd1221"
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --name-only "$N01...HEAD"
git log --oneline "$N01..HEAD"
```

Allowed production paths:

```text
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/canary.py
src/byte_mcp/nvidia/canary_evidence.py
scripts/nvidia_lightning_canary.py
```

Allowed tests/docs:

```text
tests/nvidia/test_canary.py
tests/nvidia/test_canary_evidence.py
tests/nvidia/test_canary_cli.py
tests/nvidia/test_n02_security_invariants.py
docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md
docs/superpowers/plans/2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md
.superpowers/sdd/**
```

If `src/byte_mcp/nvidia/settings.py`, provider-neutral NVIDIA-01 code, any frozen path, workflow file, or dependency file changed, require explicit documented justification from a focused RED; otherwise STOP.

- [ ] **Step 2: Run focused NVIDIA gates**

```powershell
python -m pytest tests/nvidia -q
python -m compileall -q src/byte_mcp/providers src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py
python -m ruff check src/byte_mcp/providers src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/providers tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md docs/superpowers/plans/2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md
```

Expected: all pass.

- [ ] **Step 3: Run full repository gates**

```powershell
python -m pytest -q
python -m compileall -q src
python -m ruff check .
```

Expected: pass with only previously accepted warnings.

- [ ] **Step 4: Run repository-wide Ruff format baseline comparison exactly once**

Candidate:

```powershell
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n02-final-format.txt"
$FINAL_FORMAT_EXIT = $LASTEXITCODE
```

Qualified NVIDIA-01 baseline in a detached worktree:

```powershell
git worktree add --detach "$env:TEMP\Byte-MCP-N01-format-baseline" 29daea6ef68ebb3d46031ce302b0108617bd1221
Push-Location "$env:TEMP\Byte-MCP-N01-format-baseline"
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n01-format-baseline.txt"
$BASE_FORMAT_EXIT = $LASTEXITCODE
Pop-Location
Compare-Object (Get-Content "$env:TEMP\n01-format-baseline.txt") (Get-Content "$env:TEMP\n02-final-format.txt")
```

Acceptance: NVIDIA-02 changed-scope format gate is zero and repository-wide failures introduce no new NVIDIA-02 file relative to the N01 baseline. Do not format historical unrelated debt.

- [ ] **Step 5: Prove provider activity remains zero**

Report explicitly:

```text
NVIDIA catalog calls: 0
NVIDIA inference calls: 0
OX calls: 0
Wolfram calls: 0
other provider/model calls: 0
retries: 0
fallbacks: 0
runtime promotion: NO
NVIDIA inference MCP registration: NO
```

No test may require real `NVIDIA_API_KEY`.

- [ ] **Step 6: Final whole-branch review**

Review `29daea6...HEAD` against the approved spec. Confirm:
- exact request bytes are persisted/reused;
- approval binds canary ID + request hash;
- credential/config validation precedes provider-start;
- provider-start fsync precedes executor;
- no filesystem/credential/catalog/routing action between provider-start and executor;
- one start maximum;
- one executor call maximum;
- crash after start blocks retransmit;
- terminal evidence bounded and secret-free;
- transport success separated from semantic match;
- no `/v1/models`, retry, fallback, or second attempt.

Fix only substantiated findings, then rerun the affected focused tests plus full gates once after the final fix wave.

- [ ] **Step 7: Commit final qualification-only repair if needed and push normally**

```powershell
git status --short --branch
git push origin HEAD:refs/heads/feat/nvidia-provider-n02-lightning-canary
git ls-remote origin refs/heads/feat/nvidia-provider-n02-lightning-canary
```

No force push.

- [ ] **Step 8: Require fresh GitHub Actions on exact remote HEAD**

All existing CI jobs must pass on the exact final remote SHA:

```text
Python 3.12 on ubuntu-latest: compile/lint/test PASS
Python 3.12 on windows-latest: compile/lint/test PASS
Windows launcher: PASS
Windows launcher on Pester 6: PASS
```

Only then report:

```text
NVIDIA-02_IMPLEMENTATION_STATUS: OFFLINE_QUALIFIED
LIVE_PROVIDER_AUTHORIZATION: NOT_GRANTED
```

---

### Task 9: Provider-Free Preparation of NVC-000001 and Hard Stop

**Files:**
- No Git-tracked file changes.
- Creates local runtime evidence under the configured NVIDIA evidence root only.

**Interfaces:**
- Consumes the exact offline-qualified NVIDIA-02 branch and `scripts/nvidia_lightning_canary.py prepare/inspect`.
- Produces the exact prepared identity that the user may later authorize.

**Authorization boundary:** Task 9 is provider-free but mutates local runtime evidence. Execute it only after Byte verifies the exact offline-qualified branch/CI and the operator authorizes preparation. It does **not** authorize transmission.

- [ ] **Step 1: Verify exact qualified code and credential blindness**

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
```

Require exact final qualified SHA from Task 8 and a clean working tree.

- [ ] **Step 2: Prepare one canary**

```powershell
python scripts/nvidia_lightning_canary.py prepare
```

Expected fresh evidence identity:

```text
NVC-000001
```

If another NVC already exists in the actual evidence root, STOP and inspect; do not silently treat a later identity as the first live canary.

- [ ] **Step 3: Inspect read-only**

```powershell
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
```

Capture and report exactly:

```text
canary_id
provider_id
model_id
payload_sha256
request_sha256
body_bytes
prepared_at
probe_text
provider_started_at
has_terminal_event
```

Require:

```text
provider_id = nvidia-api-catalog
model_id = nvidia/nemotron-3.5-lightning-30b-a3b
probe_text = Reply with exactly: BYTE_NVIDIA_CANARY_OK
provider_started_at = null
has_terminal_event = false
```

- [ ] **Step 4: Stop before credential setup or transmission**

Do not set `NVIDIA_API_KEY`. Do not run `transmit`. Do not call `/v1/models`. Do not call any provider.

Report:

```text
NVIDIA catalog calls: 0
NVIDIA inference calls: 0
OX calls: 0
Wolfram calls: 0
other provider/model calls: 0
NVC-000001: PREPARED
LIVE_PROVIDER_AUTHORIZATION: REQUIRED
```

The user must then explicitly approve the exact pair:

```text
canary_id = NVC-000001
request_sha256 = <exact prepared hash>
```

Only after that separate approval may the operator configure the session-only API key and execute the single live transmit command.

---

## Live Transmission — Explicitly Outside This Implementation Authorization

After Task 9, Byte will present the exact prepared identity to the user. The live request is a separate consequential action.

If and only if the user explicitly authorizes the exact `NVC-000001` + `request_sha256` pair, the operator may configure the key without echo:

```powershell
$env:NVIDIA_API_KEY = Read-Host "NVIDIA API key" -MaskInput
```

and invoke exactly one command:

```powershell
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 <EXACT_APPROVED_SHA256> --approve
```

The live operation permits exactly one NVIDIA inference provider request and zero other provider requests. Any result or ambiguity stops the operation; no retry is authorized.

---

## Stop Conditions During Implementation

Stop without live provider contact if any of the following becomes necessary:

1. modify OX, Wolfram, `server.py`, catalog, registry, or dependencies;
2. change the NVIDIA-01 request/transport/chat contracts without a focused predecessor-defect RED;
3. perform a live request to make tests pass;
4. call `/v1/models`;
5. add retry/replay/fallback behavior;
6. persist or print the API key/Authorization header;
7. reconstruct prompt/body after approval rather than using persisted exact bytes;
8. perform filesystem/settings/catalog/routing work between provider-start and executor call;
9. permit a second provider-start or second executor call for one canary;
10. auto-recover a crash after provider-start by retransmitting;
11. automatically repair contradictory evidence;
12. create an inference MCP tool or promote runtime;
13. merge/rebase/force-push shared history.

Preserve all completed reviewed commits and report the exact blocker and next safe action.

---

## Plan Execution Discipline

Recommended execution is `superpowers:subagent-driven-development` with one implementation agent at a time.

- Tasks 1-3: standard-capability implementer/reviewer; evidence integrity deserves careful review but is bounded stdlib work.
- Task 4: strongest available implementer and reviewer because provider-start adjacency and double-send prevention are the highest-risk part of NVIDIA-02.
- Task 5: strong implementer/reviewer for outcome/crash semantics.
- Task 6: lighter implementer, standard reviewer.
- Task 7: independent security reviewer; production edits only when an invariant proves a defect.
- Task 8: strongest available whole-branch reviewer.
- Task 9: controller/operator only; no subagent/provider call needed.

Do not dispatch multiple implementation agents in parallel. Use the task's pre-implementation HEAD as the review BASE. After every completed task: review, commit, fast-forward push to `feat/nvidia-provider-n02-lightning-canary`, verify remote SHA, then continue. No force push.

## Self-Review Checklist

Before execution begins, confirm:

- every spec section 1-35 maps to Task 1-9 or Global Constraints;
- no `TODO`, `TBD`, `implement later`, unspecified validation, or unnamed error handling remains;
- all public function/type names used by later tasks are defined in earlier task interfaces;
- Task 4 is the only place that introduces live-path authorization/provider-start orchestration;
- Task 5 terminalizes only known bounded outcomes and intentionally leaves unexpected post-start crashes ambiguous;
- Task 9 stops before API-key setup and transmission;
- the live command remains outside implementation authorization.
