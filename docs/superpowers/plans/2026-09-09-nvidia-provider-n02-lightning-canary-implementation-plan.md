# NVIDIA-02 Governed Nemotron Lightning Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and offline-qualify one governed NVIDIA Nemotron Lightning canary lifecycle that persists exact prepared request identity, binds explicit human approval to that identity, records durable provider-start evidence, permits exactly one NVIDIA inference transmission, and terminalizes without retry or fallback.

**Architecture:** Reuse the NVIDIA-01 `PreparedProviderRequest`, `ProviderTransmissionContext`, `execute_once()`, and `execute_prepared_nvidia_chat()` contracts unchanged. Add a narrow NVIDIA-specific evidence store and canary orchestrator plus a script operator surface; keep OX, Wolfram, the MCP server, catalog, registry, dependencies, and provider-neutral transport frozen unless a focused RED proves a predecessor defect and the plan is amended before mutation.

**Tech Stack:** Python 3.12+, stdlib filesystem/JSON/hash/argparse/asyncio primitives, existing `httpx>=0.28.1,<1`, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md`

## Global Constraints

- Qualified NVIDIA-01 predecessor is exactly `29daea6ef68ebb3d46031ce302b0108617bd1221`.
- NVIDIA-02 design commit is exactly `3c381944bc117373366b647a92f02d52a9e8adb3` before the implementation-plan commits.
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
- Exact persisted `request-body.bin` bytes are the bytes used to reconstruct the request supplied to NVIDIA-01; never rebuild the prompt/body after approval.
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
- Treat `src/byte_mcp/providers/requests.py`, `src/byte_mcp/providers/transport.py`, and `src/byte_mcp/nvidia/chat.py` as qualified predecessor contracts. Modify them only after a focused RED proves a predecessor defect and this plan is amended with the exact repair.
- Use strict TDD for production behavior: RED test first, verify the expected failure, smallest GREEN, focused verification, then commit.
- Do not run the full repository test suite after every task. Use focused tests per task, then full gates in Task 8.
- Before execution, use `superpowers:using-git-worktrees`; implementation is recommended via `superpowers:subagent-driven-development`.
- Every committed task surface must contain complete working behavior for its advertised interfaces; do not commit placeholder methods or placeholder branches.

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

### Task 1: Evidence Contracts and Root Resolution

**Files:**
- Create: `src/byte_mcp/nvidia/canary_evidence.py`
- Create: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: stdlib `Path`, `os`, `re`, `datetime`; `ByteMCPError`.
- Produces these exact public contracts:

```python
NVIDIA_CANARY_SCHEMA = "byte-mcp-nvidia-canary-v1"
NVIDIA_CANARY_ID_PATTERN = re.compile(r"NVC-[0-9]{6}\\Z")

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

@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanarySnapshot:
    manifest: NvidiaCanaryManifest
    request_body: bytes = field(repr=False)
    events: tuple[dict[str, object], ...]
    authorized_at: str | None
    provider_started_at: str | None
    terminal_event: dict[str, object] | None

class NvidiaCanaryEvidenceError(ByteMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(message)

class NvidiaCanaryLockError(ByteMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(message)

class NvidiaCanaryEvidenceStore:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise ValueError("root is invalid")
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        platform_name: str | None = None,
        home: Path | None = None,
    ) -> "NvidiaCanaryEvidenceStore":
        environment = os.environ if environ is None else environ
        explicit = environment.get("BYTE_MCP_NVIDIA_EVIDENCE_DIR", "").strip()
        if explicit:
            return cls(Path(explicit).expanduser().resolve(strict=False))
        platform_value = sys.platform if platform_name is None else platform_name
        home_value = Path.home() if home is None else home
        if platform_value == "win32":
            local_app_data = environment.get("LOCALAPPDATA", "").strip()
            base = Path(local_app_data) if local_app_data else home_value / "AppData" / "Local"
            return cls(base / "Byte-MCP" / "nvidia")
        xdg_data_home = environment.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg_data_home) if xdg_data_home else home_value / ".local" / "share"
        return cls(base / "byte-mcp" / "nvidia")
```

Task 1 does not advertise persistence methods. Those are added only in Task 2 after their RED tests exist.

- [ ] **Step 1: Write RED tests for root resolution and safe contracts**

Add tests for exact explicit/Windows/XDG/fallback roots, valid and invalid canary IDs, timezone-aware manifest timestamps, lowercase 64-hex hashes, nonnegative bounded body byte count, and safe snapshot repr.

Representative tests:

```python
def test_store_uses_explicit_evidence_root(tmp_path):
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"BYTE_MCP_NVIDIA_EVIDENCE_DIR": str(tmp_path / "evidence")},
        platform_name="win32",
        home=tmp_path / "home",
    )
    assert store.root == (tmp_path / "evidence").resolve(strict=False)


def test_store_uses_windows_default(tmp_path):
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"LOCALAPPDATA": str(tmp_path / "local")},
        platform_name="win32",
        home=tmp_path / "home",
    )
    assert store.root == tmp_path / "local" / "Byte-MCP" / "nvidia"


def test_manifest_rejects_invalid_canary_id(valid_manifest_kwargs):
    with pytest.raises(ValueError):
        NvidiaCanaryManifest(**{**valid_manifest_kwargs, "canary_id": "NVC-1"})
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: collection/import failure because `byte_mcp.nvidia.canary_evidence` does not exist.

- [ ] **Step 3: Implement only the Task 1 contracts**

Implement the concrete contracts above plus validation helpers:
- canary ID must full-match `NVC-[0-9]{6}`;
- `schema` must equal `byte-mcp-nvidia-canary-v1`;
- `payload_sha256`, `request_sha256`, and `qualified_predecessor_sha` must be lowercase 64-hex;
- `body_bytes` must be a non-bool integer from `0` through `4_000_000`;
- `prepared_at` must parse as timezone-aware ISO-8601;
- `request_body` is excluded from repr.

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

### Task 2: Immutable Persistence, Reconstruction, Events, and Locks

**Files:**
- Modify: `src/byte_mcp/nvidia/canary_evidence.py`
- Modify: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: Task 1 contracts; `PreparedProviderRequest` and `validate_prepared_provider_request_integrity()`.
- Adds these exact methods:

```text
prepare(self, prepared_request: PreparedProviderRequest, *, probe_expected_text: str, qualified_predecessor_sha: str, prepared_at: str) -> NvidiaCanaryManifest
load(self, canary_id: str) -> NvidiaCanarySnapshot
append_authorized(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None
append_provider_start(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None
append_terminal(self, canary_id: str, event: Mapping[str, object]) -> None
transmit_lock(self, canary_id: str) -> AbstractContextManager[None]
```

Evidence layout:

```text
<root>/canaries/NVC-000001/
  manifest.json
  request-body.bin
  events.jsonl
```

Private immutable write helper:

```python
def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
```

Private append helper:

```python
def _append_fsynced_jsonl(path: Path, event: Mapping[str, object]) -> None:
    payload = _canonical_json(event) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(payload)
        os.fsync(handle.fileno())
```

Canonical JSON is exactly:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

Locking:
- preparation uses `<root>/.prepare.lock` acquired with `os.O_WRONLY | os.O_CREAT | os.O_EXCL`;
- transmission uses `<canary-dir>/.transmit.lock` with the same exclusive-create rule;
- lock contention raises `NvidiaCanaryLockError`;
- normal context exit removes the lock;
- a crash-stale lock is never auto-recovered in NVIDIA-02.

Preparation allocation while holding `.prepare.lock`: scan `NVC-000001` upward and claim the first absent canary directory via `mkdir(parents=False, exist_ok=False)`. In a fresh real evidence root the first canary is exactly `NVC-000001`.

Lifecycle records before Task 5:

```json
{"event_type":"CANARY_PREPARED","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
{"event_type":"CANARY_AUTHORIZED","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
{"event_type":"PROVIDER_START","canary_id":"NVC-000001","request_sha256":"<sha>","recorded_at":"<aware-iso>"}
```

`load()` validates these event keys exactly, allows at most one authorization and one provider-start, requires prepared first, and rejects contradictory ordering. Task 5 extends it with the fixed terminal record.

- [ ] **Step 1: Write RED tests**

Cover exact body persistence; canonical manifest; create-once identity files; deterministic first identity; preparation lock contention; transmit lock contention; body/hash tampering; request-metadata tampering; malformed JSONL; duplicate/ordered events; provider-start without terminal reconstructing as consumed/ambiguous.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: new persistence/lifecycle tests fail because Task 2 methods do not exist.

- [ ] **Step 3: Implement persistence and integrity reconstruction**

`load()` must reconstruct exactly:

```python
prepared = PreparedProviderRequest(
    provider_id=manifest.provider_id,
    method=manifest.method,
    target_origin=manifest.target_origin,
    endpoint_path=manifest.endpoint_path,
    model_id=manifest.model_id,
    body_bytes=request_body,
    payload_sha256=manifest.payload_sha256,
    request_sha256=manifest.request_sha256,
)
validate_prepared_provider_request_integrity(prepared)
```

The stored manifest contains no credential or Authorization field. `events.jsonl` never contains request body or provider response body.

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

### Task 3: Fixed Lightning Prepare and Read-Only Inspect

**Files:**
- Create: `src/byte_mcp/nvidia/canary.py`
- Create: `tests/nvidia/test_canary.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `prepare_nvidia_chat_request()` and `NvidiaCanaryEvidenceStore`.
- Produces:

```python
NVIDIA_LIGHTNING_CANARY_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_LIGHTNING_CANARY_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
NVIDIA_01_QUALIFIED_SHA = "29daea6ef68ebb3d46031ce302b0108617bd1221"


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
```

Exact function signatures:

```text
prepare_lightning_canary(store: NvidiaCanaryEvidenceStore, *, now: Callable[[], datetime] = _utc_now) -> NvidiaCanaryPrepareReceipt
inspect_lightning_canary(store: NvidiaCanaryEvidenceStore, canary_id: str) -> NvidiaCanaryInspection
```

Fixed request construction:

```python
prepared = prepare_nvidia_chat_request(
    model_id=NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    messages=[{"role": "user", "content": NVIDIA_LIGHTNING_CANARY_PROMPT}],
    temperature=1.0,
    top_p=0.95,
    max_tokens=64,
)
```

- [ ] **Step 1: Write RED tests**

Prove exact model/prompt/temperature/top_p/max_tokens; generated `n=1` and `stream=false`; prepare succeeds with key absent; prepare makes zero HTTP calls and never invokes `NvidiaHostedSettings.load()`; inspect is read-only, calls `store.load()` integrity validation, and does not access credentials.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

Expected: import/attribute failure for the new canary API.

- [ ] **Step 3: Implement prepare/inspect**

Convert injected time to UTC:

```python
prepared_at = now().astimezone(UTC).isoformat()
```

Call `store.prepare()` with the exact expected semantic text and `NVIDIA_01_QUALIFIED_SHA`. `inspect_lightning_canary()` maps a verified snapshot to bounded metadata only. Do not import the catalog client, OX, Wolfram, or call `NvidiaHostedSettings.load()`.

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
- Adds:

```python
@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanaryTransmissionResult:
    canary_id: str
    request_sha256: str
    attempt_outcome: ProviderAttemptOutcome
    model_id: str
    semantic_probe_match: bool | None
    response_content: str | None = field(default=None, repr=False)
```

Exact transmit signature:

```text
transmit_lightning_canary(store: NvidiaCanaryEvidenceStore, *, canary_id: str, expected_request_sha256: str, approve: bool, settings_loader: Callable[[], NvidiaHostedSettings] = NvidiaHostedSettings.load, executor: Callable[[PreparedProviderRequest, ProviderTransmissionContext, NvidiaHostedSettings], Awaitable[NvidiaChatResult]] = execute_prepared_nvidia_chat, now: Callable[[], datetime] = _utc_now) -> Awaitable[NvidiaCanaryTransmissionResult]
```

Pre-provider ordering while holding `store.transmit_lock(canary_id)`:

```text
1. load and revalidate snapshot
2. require approve is exactly True
3. require expected request hash equals manifest request hash
4. require no prior provider-start
5. require no terminal event
6. load NvidiaHostedSettings
7. require api_key configured and timeout policy valid
8. reconstruct exact PreparedProviderRequest from persisted manifest/body
9. validate prepared request integrity
10. append+fsync CANARY_AUTHORIZED if absent; if present it must bind the same hash
11. choose provider_started_at in memory
12. append+fsync PROVIDER_START using that exact timestamp/hash
13. construct ProviderTransmissionContext in memory
14. call executor exactly once
```

- [ ] **Step 1: Write RED preflight and ordering tests**

Zero-executor-call cases: `approve=False`, wrong request hash, missing canary, tampered evidence, wrong provider/model/origin/path, missing API key, invalid timeout configuration, prior provider-start, prior terminal event, and transmit-lock contention.

Ordering test: inject an executor that observes already-written lifecycle evidence when called and verifies the final event is `PROVIDER_START`; verify the context timestamp and expected request hash equal the persisted start record and manifest.

Concurrency test: two local transmit calls for one canary yield at most one executor call and one provider-start.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

Expected: transmit tests fail because transmit orchestration is absent.

- [ ] **Step 3: Implement preflight and exact start adjacency**

Before provider-start, reconstruct and validate the persisted request and load settings. After the fsynced `PROVIDER_START`, the only allowed preparation is:

```python
context = ProviderTransmissionContext(
    provider_started_at=provider_started_at,
    expected_request_sha256=snapshot.manifest.request_sha256,
)
result = await executor(prepared_request, context, settings)
```

Do not access `store`, `Path`, environment, catalog, registry, routing state, or prompt-building code between the provider-start append and executor call.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
```

Expected: all pass using injected executors only; provider activity remains zero.

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
git commit -m "feat: govern NVIDIA canary provider start"
```

---

### Task 5: Bounded Terminalization and Crash Semantics

**Files:**
- Modify: `src/byte_mcp/nvidia/canary.py`
- Modify: `src/byte_mcp/nvidia/canary_evidence.py`
- Modify: `tests/nvidia/test_canary.py`
- Modify: `tests/nvidia/test_canary_evidence.py`

**Interfaces:**
- Consumes: `NvidiaChatResult`, `NvidiaChatError`, `ProviderTransportError`, `ProviderAttemptOutcome`.
- Extends `load()` and `append_terminal()` for this exact terminal-key set:

```text
event_type
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

`event_type` is exactly `CANARY_TERMINAL`. Fields that do not apply are persisted as JSON null so the schema remains fixed.

Success semantics:

```python
semantic_probe_match = result.content == NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT
attempt_outcome = ProviderAttemptOutcome.COMPLETED
```

Known failure handling:
- `NvidiaChatError`: persist its bounded NVIDIA failure kind, attempt outcome, and observation; then re-raise the same safe error.
- `ProviderTransportError`: persist its bounded transport failure kind, attempt outcome, and observation; then re-raise the same safe error.
- Do not catch arbitrary exceptions after provider-start. An unexpected exception intentionally leaves provider-start without terminal evidence and therefore blocks retransmission.

- [ ] **Step 1: Write RED terminalization tests**

Inject: parsed success with exact semantic match; parsed success with different content; NVIDIA HTTP rejection; NVIDIA protocol failure after complete 2xx; transport `NOT_SENT` after provider-start; transport `OUTCOME_UNKNOWN`; unexpected exception after provider-start. Assert one terminal event for known outcomes, zero retries, zero duplicate executor calls, no durable response content, and blocked retransmit after unexpected exception.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
```

Expected: new terminalization assertions fail until the fixed schema and known-error mapping are implemented.

- [ ] **Step 3: Implement terminal mapping and persistence**

Create private helpers that map `ProviderTransportObservation` plus result/error metadata into the exact terminal dictionary. Persist the terminal event once while the transmit lock remains held. Return `NvidiaCanaryTransmissionResult` only for parsed success.

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
- Produces exactly:

```text
python scripts/nvidia_lightning_canary.py prepare
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 <64-lowercase-hex> --approve
```

No credential, model, endpoint, prompt, retry, or fallback option is accepted.

Public script signature:

```text
main(argv: Sequence[str] | None = None) -> int
```

- [ ] **Step 1: Write RED CLI tests**

Test exact three subcommands; prepare/inspect with key absent; rejection of credential/model/endpoint/prompt switches; required transmit ID/hash/approval; no retry/fallback switches; bounded sorted-JSON output.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py -q
```

Expected: failure because the script does not exist.

- [ ] **Step 3: Implement argparse-only CLI**

`main()` constructs `NvidiaCanaryEvidenceStore.from_environment()`. `prepare` and `inspect` call only their credential-blind functions. `transmit` calls `asyncio.run(transmit_lightning_canary(...))`. Output explicit dictionaries rather than object/environment dumps. Immediate successful transmit may print `response_content`; evidence policy remains unchanged.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
python -m ruff format --check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
```

Expected: all pass, provider activity zero.

- [ ] **Step 5: Commit**

```powershell
git add scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
git commit -m "feat: add NVIDIA Lightning canary CLI"
```

---

### Task 7: Security and Isolation Invariant Suite

**Files:**
- Create: `tests/nvidia/test_n02_security_invariants.py`
- No production modification is authorized by this task itself.

**Interfaces:**
- Consumes all NVIDIA-02 production surfaces.
- Produces only invariant tests.

- [ ] **Step 1: Add invariant tests**

Prove:
- `canary.py` and `canary_evidence.py` import neither OX nor Wolfram;
- `server.py` does not import/register NVIDIA canary/inference;
- transmit does not call catalog or registry;
- canary source contains no retry/backoff/sleep/fallback/request-replay implementation;
- CLI exposes no API-key/model/endpoint/prompt override;
- tracked NVIDIA-02 content contains no `nvapi-` secret sentinel;
- evidence never contains injected key/Authorization sentinel;
- prepare/inspect never call the settings loader;
- executor receives a prepared request whose `body_bytes` exactly equal persisted `request-body.bin`;
- wrong hash/provider/model/origin/path yields zero executor calls;
- duplicate transmit yields at most one provider-start and one executor call;
- provider-start without terminal blocks retransmission;
- no A002/retry path exists;
- no `/v1/models` operation exists in canary code;
- `NVIDIA_API_KEY` is accessed only by the existing `NvidiaHostedSettings.load()` path during transmit.

- [ ] **Step 2: Run invariants**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py -q
```

Expected: PASS if Tasks 1-6 satisfy the approved design.

- [ ] **Step 3: If any invariant fails, stop for an exact plan amendment**

Do not mutate production from a generic repair instruction. Record the failing test, root cause, affected file, smallest proposed change, and exact focused verification; amend this plan with that repair before implementation resumes.

- [ ] **Step 4: Run scoped regression once invariants pass**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py tests/nvidia/test_canary_cli.py -q
python -m ruff check src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py scripts/nvidia_lightning_canary.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py tests/nvidia/test_canary_cli.py tests/nvidia/test_n02_security_invariants.py
```

Expected: all pass.

- [ ] **Step 5: Commit test-only invariant freeze**

```powershell
git add tests/nvidia/test_n02_security_invariants.py
git diff --cached --name-only
git commit -m "test: freeze NVIDIA-02 canary security invariants"
```

The staged filename list must contain only `tests/nvidia/test_n02_security_invariants.py`.

---

### Task 8: Final Offline Qualification and Exact-Head CI

**Files:**
- No production changes expected.
- A formatting-only repair to NVIDIA-02 changed files is allowed only when the baseline-aware format check proves new NVIDIA-02 formatting debt; commit it separately.

**Interfaces:**
- Consumes the complete NVIDIA-02 branch.
- Produces an offline-qualified branch eligible to prepare `NVC-000001`; it does not authorize live transmission.

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

Any other changed path is a STOP unless already covered by an approved plan amendment.

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

- [ ] **Step 4: Compare repository-wide format debt to NVIDIA-01 exactly once**

Candidate:

```powershell
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n02-final-format.txt"
$FINAL_FORMAT_EXIT = $LASTEXITCODE
```

NVIDIA-01 baseline:

```powershell
$BASE_WT = Join-Path $env:TEMP "Byte-MCP-N01-format-baseline"
git worktree add --detach $BASE_WT 29daea6ef68ebb3d46031ce302b0108617bd1221
Push-Location $BASE_WT
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n01-format-baseline.txt"
$BASE_FORMAT_EXIT = $LASTEXITCODE
Pop-Location
Compare-Object (Get-Content "$env:TEMP\n01-format-baseline.txt") (Get-Content "$env:TEMP\n02-final-format.txt")
```

Acceptance: the changed-scope format check is zero and repository-wide output introduces no new NVIDIA-02 file relative to the N01 baseline. Do not format unrelated historical debt.

- [ ] **Step 5: Prove provider activity is still zero**

Report exactly:

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

- [ ] **Step 6: Perform whole-branch review**

Review `29daea6...HEAD` against the approved spec and verify exact-byte persistence, hash-bound approval, pre-start credential validation, start-before-executor ordering, no post-start local I/O before executor, one-start/one-executor maximum, ambiguous crash blocking, bounded secret-free terminal evidence, semantic/transport separation, and absence of `/v1/models`, retry, or fallback. Any material finding requires an exact plan amendment before repair.

- [ ] **Step 7: Push normally and verify remote identity**

```powershell
git status --short --branch
git push origin HEAD:refs/heads/feat/nvidia-provider-n02-lightning-canary
$LOCAL = git rev-parse HEAD
$REMOTE = (git ls-remote origin refs/heads/feat/nvidia-provider-n02-lightning-canary).Split("`t")[0]
"LOCAL : $LOCAL"
"REMOTE: $REMOTE"
```

Require local and remote SHA equality. Never force-push.

- [ ] **Step 8: Require fresh GitHub Actions on exact remote HEAD**

All existing jobs must pass on the exact final SHA:

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
- Consumes the exact offline-qualified NVIDIA-02 branch and the `prepare`/`inspect` CLI.
- Produces the exact prepared identity that may later be authorized.

**Authorization boundary:** Task 9 mutates only local evidence and performs no provider request. Execute it only after Byte verifies the exact offline-qualified branch/CI and the operator approves preparation. It does not authorize transmission.

- [ ] **Step 1: Verify exact qualified code and remove any session key**

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
```

Require the exact final qualified SHA from Task 8 and a clean working tree.

- [ ] **Step 2: Prepare one canary**

```powershell
python scripts/nvidia_lightning_canary.py prepare
```

In a fresh real evidence root require `canary_id` exactly `NVC-000001`. If the actual evidence root already contains any NVC identity, STOP and inspect it rather than silently treating a later identity as the first live canary.

- [ ] **Step 3: Inspect read-only**

```powershell
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
```

Capture exactly:

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

- [ ] **Step 4: Hard stop before credential setup/transmission**

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

The user must separately approve the exact pair `canary_id=NVC-000001` and its exact `request_sha256` before live transmission can occur.

---

## Live Transmission — Outside This Implementation Authorization

After Task 9, Byte presents the exact prepared identity to the user. The live request is a separate consequential action.

Only after explicit authorization of the exact `NVC-000001` + `request_sha256` pair may the operator set the session-only credential:

```powershell
$env:NVIDIA_API_KEY = Read-Host "NVIDIA API key" -MaskInput
```

and invoke one command:

```powershell
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 <EXACT_APPROVED_SHA256> --approve
```

That operation permits exactly one NVIDIA inference request and zero other provider requests. Any result or ambiguity stops the operation. No retry is authorized.

---

## Stop Conditions During Implementation

Stop without provider contact if implementation would require any of the following:

1. modify OX, Wolfram, `server.py`, catalog, registry, or dependencies;
2. change NVIDIA-01 request/transport/chat contracts without an approved exact plan amendment;
3. perform a live provider request to make tests pass;
4. call `/v1/models`;
5. add retry/replay/fallback behavior;
6. persist or print the API key/Authorization header;
7. reconstruct prompt/body after approval rather than use persisted exact bytes;
8. perform filesystem/settings/catalog/routing work between provider-start and executor call;
9. permit a second provider-start or second executor call for one canary;
10. retransmit after a crash with durable provider-start;
11. auto-repair contradictory evidence;
12. create an inference MCP tool or promote runtime;
13. merge/rebase/force-push shared history.

Preserve completed reviewed commits and report the exact blocker and next safe action.

---

## Plan Execution Discipline

Recommended execution is `superpowers:subagent-driven-development` when a subagent-capable coding environment is available; otherwise execute inline task-by-task with the same TDD/review gates.

- Tasks 1-3: standard-capability implementation/review.
- Task 4: strongest available implementation/review because provider-start adjacency and double-send prevention are the highest-risk part.
- Task 5: strong implementation/review for outcome/crash semantics.
- Task 6: lighter implementation, standard review.
- Task 7: independent security review; no production mutation without a plan amendment.
- Task 8: strongest available whole-branch review.
- Task 9: controller/operator only; no provider call.

Do not run multiple implementation tasks concurrently. Use each task's pre-implementation HEAD as review BASE. After every completed task: review, commit, fast-forward push to `feat/nvidia-provider-n02-lightning-canary`, verify remote SHA, then continue. Never force-push.

## Self-Review Checklist

Before execution begins, confirm:

- every design requirement maps to Global Constraints or Tasks 1-9;
- all advertised interfaces use exact names/types and are introduced before later tasks consume them;
- Task 1 advertises only the contracts it fully implements;
- Task 4 is the only task adding authorization/provider-start orchestration;
- Task 5 terminalizes only known bounded outcomes and intentionally leaves unexpected post-start crashes ambiguous;
- Task 7 has no generic production-repair authority;
- Task 9 stops before API-key setup/transmission;
- the live transmit command remains outside implementation authorization.
