# NVIDIA-02 Governed Nemotron Lightning Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and offline-qualify one governed NVIDIA Nemotron Lightning canary lifecycle that persists exact prepared request identity, binds explicit human approval to that identity, records durable provider-start evidence, permits exactly one NVIDIA inference transmission, and terminalizes without retry or fallback.

**Architecture:** Reuse the qualified NVIDIA-01 request, transport, and hosted-chat contracts. Add only an NVIDIA canary evidence store, canary orchestrator, and narrow operator script. OX, Wolfram, the MCP server, catalog, registry, dependencies, and provider-neutral NVIDIA-01 code remain frozen unless a focused RED proves a predecessor defect and this plan is amended before mutation.

**Tech Stack:** Python 3.12+, stdlib filesystem/JSON/hash/argparse/asyncio, existing `httpx>=0.28.1,<1`, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md`

## Global Constraints

- Qualified NVIDIA-01 predecessor: `29daea6ef68ebb3d46031ce302b0108617bd1221`.
- Approved NVIDIA-02 design commit: `3c381944bc117373366b647a92f02d52a9e8adb3`.
- Target branch: `feat/nvidia-provider-n02-lightning-canary`.
- No live NVIDIA catalog or inference request during Tasks 1-8.
- No OX, Wolfram, OpenAI, or other model/provider request during Tasks 1-8.
- No automatic retry, retry-in-place, backoff, redirect following, replay, model fallback, or provider fallback.
- Fixed model: `nvidia/nemotron-3.5-lightning-30b-a3b`.
- Fixed target: `POST https://integrate.api.nvidia.com/v1/chat/completions` through NVIDIA-01.
- Fixed prompt: `Reply with exactly: BYTE_NVIDIA_CANARY_OK`.
- Fixed generation parameters: `temperature=1.0`, `top_p=0.95`, `max_tokens=64`, generated `n=1`, generated `stream=false`.
- `NVIDIA_API_KEY` is never accepted as a CLI argument and is never persisted in Git, evidence, logs, hashes, reprs, or tests.
- `prepare` and `inspect` never call `NvidiaHostedSettings.load()` and never read `NVIDIA_API_KEY`.
- `transmit` may load `NvidiaHostedSettings` only before durable `PROVIDER_START`.
- Persisted `request-body.bin` bytes are the bytes reconstructed into `PreparedProviderRequest` for transmission; never rebuild the prompt/body after approval.
- `PROVIDER_START` is appended, flushed, and fsynced before the single adapter call.
- Between provider-start persistence and the adapter call: no filesystem read, settings/environment access, catalog/registry access, routing, prompt reconstruction, or other provider/model call.
- Durable provider-start consumes authorization regardless of final outcome or crash.
- Provider-start without terminal evidence blocks retransmission permanently in NVIDIA-02.
- No `/v1/models` preflight.
- No NVIDIA inference MCP registration.
- No runtime promotion/restart.
- No merge to `main`.
- No dependency change.
- Frozen paths: `src/byte_mcp/ox/**`, `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, `src/byte_mcp/nvidia/catalog.py`, `src/byte_mcp/nvidia/registry.py`, `pyproject.toml`.
- Qualified predecessor contracts are frozen: `src/byte_mcp/providers/requests.py`, `src/byte_mcp/providers/transport.py`, `src/byte_mcp/nvidia/chat.py`.
- Any needed frozen/predecessor change requires a focused RED plus an explicit amendment to this plan before mutation.
- TDD is mandatory for Tasks 1-6: RED test, verify expected failure, minimal GREEN, focused checks, commit.
- Every committed task surface must fully implement the interfaces advertised by that task.
- Use an isolated worktree at execution time.

---

## File Map

**Create**
- `src/byte_mcp/nvidia/canary_evidence.py` — evidence root, immutable identity files, append-only lifecycle, locks, integrity reconstruction.
- `src/byte_mcp/nvidia/canary.py` — fixed request, prepare/inspect, approval/start orchestration, terminalization.
- `scripts/nvidia_lightning_canary.py` — `prepare`, `inspect`, `transmit` operator commands.
- `tests/nvidia/test_canary_evidence.py`
- `tests/nvidia/test_canary.py`
- `tests/nvidia/test_canary_cli.py`
- `tests/nvidia/test_n02_security_invariants.py`

**Modify**
- `src/byte_mcp/nvidia/__init__.py` — export NVIDIA-02 public contracts only.

**Do not modify unless the plan is amended**
- `src/byte_mcp/nvidia/settings.py`
- all frozen/predecessor paths listed above.

---

### Task 1: Evidence Contracts and Root Resolution

**Files:**
- Create: `src/byte_mcp/nvidia/canary_evidence.py`
- Create: `tests/nvidia/test_canary_evidence.py`

**Produces exactly:**

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
```

`NvidiaCanaryEvidenceStore` Task-1 surface:

```text
__init__(self, root: Path) -> None
root -> Path
from_environment(cls, environ: Mapping[str, str] | None = None, *, platform_name: str | None = None, home: Path | None = None) -> NvidiaCanaryEvidenceStore
```

Root resolution is exact:
- non-empty `BYTE_MCP_NVIDIA_EVIDENCE_DIR` -> `Path(value).expanduser().resolve(strict=False)`;
- Windows -> `%LOCALAPPDATA%/Byte-MCP/nvidia`, falling back to `<home>/AppData/Local/Byte-MCP/nvidia`;
- Unix with `XDG_DATA_HOME` -> `$XDG_DATA_HOME/byte-mcp/nvidia`;
- Unix fallback -> `<home>/.local/share/byte-mcp/nvidia`.

Validation is exact:
- schema equals `byte-mcp-nvidia-canary-v1`;
- canary ID full-matches `NVC-[0-9]{6}`;
- all SHA fields are lowercase 64-hex;
- `body_bytes` is a non-bool integer in `0..4_000_000`;
- `prepared_at` is timezone-aware ISO-8601;
- snapshot repr excludes `request_body`.

- [ ] **Step 1: Write RED tests** for explicit root, Windows default, XDG default, Unix fallback, manifest validation, and secret/body-safe repr.

Representative tests:

```python
def test_store_uses_explicit_evidence_root(tmp_path):
    store = NvidiaCanaryEvidenceStore.from_environment(
        {"BYTE_MCP_NVIDIA_EVIDENCE_DIR": str(tmp_path / "evidence")},
        platform_name="win32",
        home=tmp_path / "home",
    )
    assert store.root == (tmp_path / "evidence").resolve(strict=False)


def test_manifest_rejects_invalid_canary_id(valid_manifest_kwargs):
    with pytest.raises(ValueError):
        NvidiaCanaryManifest(**{**valid_manifest_kwargs, "canary_id": "NVC-1"})
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: import failure because `byte_mcp.nvidia.canary_evidence` does not exist.

- [ ] **Step 3: Implement only Task-1 contracts and validation.** Do not add persistence methods yet.

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
```

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

**Adds exactly:**

```text
prepare(self, prepared_request: PreparedProviderRequest, *, probe_expected_text: str, qualified_predecessor_sha: str, prepared_at: str) -> NvidiaCanaryManifest
load(self, canary_id: str) -> NvidiaCanarySnapshot
append_authorized(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None
append_provider_start(self, canary_id: str, *, request_sha256: str, recorded_at: str) -> None
transmit_lock(self, canary_id: str) -> AbstractContextManager[None]
```

Evidence layout:

```text
<root>/canaries/NVC-000001/
  manifest.json
  request-body.bin
  events.jsonl
```

Canonical JSON:

```python
json.dumps(
    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
).encode("utf-8")
```

Immutable-write primitive:

```python
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as handle:
    handle.write(payload)
    handle.flush()
    os.fsync(handle.fileno())
```

Append primitive writes canonical JSON + newline, flushes, then `os.fsync()`.

Lock rules:
- prepare lock: `<root>/.prepare.lock` via `O_CREAT|O_EXCL`;
- transmit lock: `<canary-dir>/.transmit.lock` via `O_CREAT|O_EXCL`;
- contention -> `NvidiaCanaryLockError`;
- normal exit removes lock;
- stale crash lock is never automatically recovered.

Allocation while prepare lock is held: scan `NVC-000001` upward and atomically create the first absent directory. Fresh production evidence therefore starts at `NVC-000001`.

Allowed lifecycle records at Task 2:

```json
{"event_type":"CANARY_PREPARED","canary_id":"NVC-000001","request_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","recorded_at":"2026-09-09T12:00:00+00:00"}
{"event_type":"CANARY_AUTHORIZED","canary_id":"NVC-000001","request_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","recorded_at":"2026-09-09T12:01:00+00:00"}
{"event_type":"PROVIDER_START","canary_id":"NVC-000001","request_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","recorded_at":"2026-09-09T12:02:00+00:00"}
```

Task-2 `load()` rejects unknown event types, duplicate authorization/start, start before prepared, hash mismatch, malformed JSONL, manifest/body tampering, or contradictory identity.

- [ ] **Step 1: Write RED tests** for exact body persistence, canonical manifest, create-once files, deterministic first ID, prepare/transmit lock contention, body/manifest tampering, malformed JSONL, duplicate/ordered events, and provider-start-without-terminal state.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
```

Expected: new tests fail because Task-2 methods do not exist.

- [ ] **Step 3: Implement Task-2 persistence.** `load()` reconstructs `PreparedProviderRequest` from persisted manifest/body and calls `validate_prepared_provider_request_integrity()` before returning.

Exact reconstruction:

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

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary_evidence.py
```

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

**Produces constants:**

```python
NVIDIA_LIGHTNING_CANARY_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_LIGHTNING_CANARY_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
NVIDIA_01_QUALIFIED_SHA = "29daea6ef68ebb3d46031ce302b0108617bd1221"
```

**Produces dataclasses:**

```python
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

**Adds exact functions:**

```text
prepare_lightning_canary(store: NvidiaCanaryEvidenceStore, *, now: Callable[[], datetime] = _utc_now) -> NvidiaCanaryPrepareReceipt
inspect_lightning_canary(store: NvidiaCanaryEvidenceStore, canary_id: str) -> NvidiaCanaryInspection
```

Fixed request call:

```python
prepared = prepare_nvidia_chat_request(
    model_id=NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    messages=[{"role": "user", "content": NVIDIA_LIGHTNING_CANARY_PROMPT}],
    temperature=1.0,
    top_p=0.95,
    max_tokens=64,
)
```

- [ ] **Step 1: Write RED tests** proving exact model/prompt/parameters, generated `n=1`/`stream=false`, prepare works without key, prepare makes zero HTTP/settings-loader calls, inspect is read-only and credential-blind.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

Expected: new canary API missing.

- [ ] **Step 3: Implement prepare/inspect.** Use timezone-aware UTC `now().astimezone(UTC).isoformat()`. Pass `NVIDIA_01_QUALIFIED_SHA` and expected semantic text into `store.prepare()`.

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_canary.py
git commit -m "feat: prepare and inspect NVIDIA Lightning canary"
```

---

### Task 4: Approval Preflight, Duplicate-Send Lock, and Provider-Start Adjacency

**Files:**
- Modify: `src/byte_mcp/nvidia/canary.py`
- Modify: `tests/nvidia/test_canary.py`

**Adds dataclass:**

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

**Adds async function:**

```text
async transmit_lightning_canary(store: NvidiaCanaryEvidenceStore, *, canary_id: str, expected_request_sha256: str, approve: bool, settings_loader: Callable[[], NvidiaHostedSettings] = NvidiaHostedSettings.load, executor: Callable[[PreparedProviderRequest, ProviderTransmissionContext, NvidiaHostedSettings], Awaitable[NvidiaChatResult]] = execute_prepared_nvidia_chat, now: Callable[[], datetime] = _utc_now) -> NvidiaCanaryTransmissionResult
```

Pre-provider order inside `store.transmit_lock(canary_id)` is frozen:
1. `store.load()` and integrity validation;
2. require `approve is True`;
3. exact expected-hash match;
4. reject prior provider-start;
5. load `NvidiaHostedSettings`;
6. require key configured and timeout policy constructed;
7. reconstruct exact prepared request from persisted manifest/body;
8. validate exact provider/model/method/origin/path and request integrity;
9. append+fsync `CANARY_AUTHORIZED` if absent; existing authorization must bind the same hash;
10. select UTC `provider_started_at` in memory;
11. append+fsync `PROVIDER_START` using that exact timestamp/hash;
12. construct `ProviderTransmissionContext` in memory;
13. call injected executor exactly once.

After step 11 and before step 13, no store/path/settings/environment/catalog/registry/routing/prompt access is allowed.

- [ ] **Step 1: Write RED tests** for zero-call cases: approval false, wrong hash, missing canary, tampered evidence, wrong provider/model/origin/path, missing key, invalid timeout config, prior provider-start, and transmit-lock contention. Add an ordering test whose injected executor verifies the persisted provider-start event already exists and exactly matches the passed context. Add concurrent duplicate transmit test: at most one executor call and one provider-start.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py -q
```

- [ ] **Step 3: Implement preflight/start.** Immediately after fsynced start, execute only:

```python
context = ProviderTransmissionContext(
    provider_started_at=provider_started_at,
    expected_request_sha256=snapshot.manifest.request_sha256,
)
result = await executor(prepared_request, context, settings)
```

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py tests/nvidia/test_canary.py
git commit -m "feat: govern NVIDIA canary provider start"
```

---

### Task 5: Fixed Terminal Evidence and Crash Semantics

**Files:**
- Modify: `src/byte_mcp/nvidia/canary.py`
- Modify: `src/byte_mcp/nvidia/canary_evidence.py`
- Modify: `tests/nvidia/test_canary.py`
- Modify: `tests/nvidia/test_canary_evidence.py`

**Adds evidence-store method:**

```text
append_terminal(self, canary_id: str, event: Mapping[str, object]) -> None
```

**Terminal event has exactly these keys:**

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

`event_type` is `CANARY_TERMINAL`; inapplicable fields are JSON null. `load()` now accepts exactly one terminal after provider-start and rejects terminal-before-start, duplicate terminal, or any event after terminal.

Success:

```python
semantic_probe_match = result.content == NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT
```

Known errors:
- `NvidiaChatError`: terminalize bounded NVIDIA kind/outcome/observation, then re-raise same safe error.
- `ProviderTransportError`: terminalize bounded transport kind/outcome/observation, then re-raise same safe error.
- Do not catch arbitrary exceptions after provider-start; they leave start-without-terminal ambiguous and block retransmission.

- [ ] **Step 1: Write RED tests** for exact semantic match true, semantic mismatch false, HTTP rejection, protocol failure after complete 2xx, transport `NOT_SENT`, transport `OUTCOME_UNKNOWN`, prior terminal zero-call, and unexpected post-start exception causing permanent retransmission block. Assert no durable response body/key/header.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
```

- [ ] **Step 3: Implement fixed terminal schema, validation, and known-outcome mapping.** Keep the transmit lock held through terminal append. Return `NvidiaCanaryTransmissionResult` only on parsed success.

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py
git commit -m "feat: terminalize NVIDIA canary outcomes"
```

---

### Task 6: Narrow CLI

**Files:**
- Create: `scripts/nvidia_lightning_canary.py`
- Create: `tests/nvidia/test_canary_cli.py`

**Public script signature:**

```text
main(argv: Sequence[str] | None = None) -> int
```

**Only accepted commands:**

```powershell
python scripts/nvidia_lightning_canary.py prepare
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
$EXPECTED_REQUEST_SHA256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 $EXPECTED_REQUEST_SHA256 --approve
```

No key/token/credential/model/endpoint/prompt/retry/fallback option exists.

- [ ] **Step 1: Write RED tests** for exact subcommands, credential-blind prepare/inspect, rejected secret/model/endpoint/prompt flags, required transmit ID/hash/approval, no retry/fallback flags, and bounded sorted-JSON output.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py -q
```

Expected: script missing.

- [ ] **Step 3: Implement argparse-only CLI.** `prepare`/`inspect` call only credential-blind functions; `transmit` uses `asyncio.run(transmit_lightning_canary(...))`; output explicit bounded dictionaries rather than object/environment dumps.

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/nvidia/test_canary_cli.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py -q
python -m ruff check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
python -m ruff format --check scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
```

- [ ] **Step 5: Commit**

```powershell
git add scripts/nvidia_lightning_canary.py tests/nvidia/test_canary_cli.py
git commit -m "feat: add NVIDIA Lightning canary CLI"
```

---

### Task 7: Security and Isolation Invariants

**Files:**
- Create: `tests/nvidia/test_n02_security_invariants.py`
- No production modification is authorized by Task 7 itself.

- [ ] **Step 1: Add invariant tests** proving all of the following:
  - canary modules import neither OX nor Wolfram;
  - `server.py` has no NVIDIA canary/inference registration;
  - transmit does not call catalog/registry;
  - canary source contains no retry/backoff/sleep/fallback/replay mechanism;
  - CLI has no credential/model/endpoint/prompt override;
  - tracked NVIDIA-02 files contain no `nvapi-` sentinel;
  - evidence contains no injected secret or Authorization value;
  - prepare/inspect never call the settings loader;
  - executor receives body bytes exactly equal to persisted `request-body.bin`;
  - wrong hash/provider/model/origin/path produces zero executor calls;
  - duplicate transmit produces at most one start and one executor call;
  - provider-start without terminal blocks retransmission;
  - no A002/retry path exists;
  - no `/v1/models` operation exists in canary code;
  - `NVIDIA_API_KEY` is accessed only by existing `NvidiaHostedSettings.load()` during transmit.

- [ ] **Step 2: Run invariants**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py -q
```

Expected: PASS if Tasks 1-6 match the approved design.

- [ ] **Step 3: If an invariant fails, STOP.** Record failing assertion, root cause, exact affected file, proposed minimal repair, and focused verification; amend this plan before production mutation.

- [ ] **Step 4: Once invariants pass, run scoped regression**

```powershell
python -m pytest tests/nvidia/test_n02_security_invariants.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py tests/nvidia/test_canary_cli.py -q
python -m ruff check src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia/canary.py src/byte_mcp/nvidia/canary_evidence.py scripts/nvidia_lightning_canary.py tests/nvidia/test_canary.py tests/nvidia/test_canary_evidence.py tests/nvidia/test_canary_cli.py tests/nvidia/test_n02_security_invariants.py
```

- [ ] **Step 5: Commit test-only freeze**

```powershell
git add tests/nvidia/test_n02_security_invariants.py
git diff --cached --name-only
git commit -m "test: freeze NVIDIA-02 canary security invariants"
```

The staged list must contain only `tests/nvidia/test_n02_security_invariants.py`.

---

### Task 8: Final Offline Qualification

**Files:**
- No production changes expected.
- Formatting-only NVIDIA-02 repair is permitted only if baseline comparison proves new NVIDIA-02 format debt; commit it separately.

- [ ] **Step 1: Verify lineage/scope**

```powershell
$N01 = "29daea6ef68ebb3d46031ce302b0108617bd1221"
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --name-only "$N01...HEAD"
git log --oneline "$N01..HEAD"
```

Allowed production:

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

Any other path requires a previously approved plan amendment.

- [ ] **Step 2: Focused gates**

```powershell
python -m pytest tests/nvidia -q
python -m compileall -q src/byte_mcp/providers src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py
python -m ruff check src/byte_mcp/providers src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/providers tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia scripts/nvidia_lightning_canary.py tests/nvidia docs/superpowers/specs/2026-09-09-nvidia-provider-n02-lightning-canary-design.md docs/superpowers/plans/2026-09-09-nvidia-provider-n02-lightning-canary-implementation-plan.md
```

Expected: all pass.

- [ ] **Step 3: Full gates**

```powershell
python -m pytest -q
python -m compileall -q src
python -m ruff check .
```

- [ ] **Step 4: Compare repo-wide Ruff-format debt once against N01**

```powershell
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n02-final-format.txt"
$BASE_WT = Join-Path $env:TEMP "Byte-MCP-N01-format-baseline"
git worktree add --detach $BASE_WT 29daea6ef68ebb3d46031ce302b0108617bd1221
Push-Location $BASE_WT
python -m ruff format --check . 2>&1 | Tee-Object "$env:TEMP\n01-format-baseline.txt"
Pop-Location
Compare-Object (Get-Content "$env:TEMP\n01-format-baseline.txt") (Get-Content "$env:TEMP\n02-final-format.txt")
```

Acceptance: changed-scope format is clean and repo-wide output adds no NVIDIA-02 file relative to N01. Never format unrelated historical debt.

- [ ] **Step 5: Provider-activity receipt**

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

- [ ] **Step 6: Whole-branch review** of `29daea6...HEAD` against the approved spec. Any material finding requires an exact plan amendment before repair.

- [ ] **Step 7: Push and verify identity**

```powershell
git status --short --branch
git push origin HEAD:refs/heads/feat/nvidia-provider-n02-lightning-canary
$LOCAL = git rev-parse HEAD
$REMOTE = (git ls-remote origin refs/heads/feat/nvidia-provider-n02-lightning-canary).Split("`t")[0]
"LOCAL : $LOCAL"
"REMOTE: $REMOTE"
```

Require equality; never force-push.

- [ ] **Step 8: Require fresh GitHub Actions on exact remote SHA**

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
- No Git-tracked changes.
- Local evidence only.

**Authorization boundary:** Execute Task 9 only after Byte verifies the exact offline-qualified branch/CI and the operator approves local preparation. Task 9 never loads the API key and never transmits.

- [ ] **Step 1: Verify exact qualified code and remove any session key**

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Prepare**

```powershell
python scripts/nvidia_lightning_canary.py prepare
```

In a fresh real evidence root require `NVC-000001`. If any real NVC identity already exists, STOP and inspect it.

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

- [ ] **Step 4: Hard stop**

Do not set `NVIDIA_API_KEY`. Do not run `transmit`. Do not call `/v1/models` or any provider.

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

The user must separately approve the exact `canary_id=NVC-000001` and exact `request_sha256` before live transmission.

---

## Live Transmission — Explicitly Outside Implementation Authorization

Only after the exact prepared identity is separately approved may the operator set a session-only key:

```powershell
$env:NVIDIA_API_KEY = Read-Host "NVIDIA API key" -MaskInput
```

Then, with the approved hash assigned locally:

```powershell
$APPROVED_REQUEST_SHA256 = "the exact 64-character hash presented and approved in chat"
python scripts/nvidia_lightning_canary.py transmit --canary-id NVC-000001 --expected-request-sha256 $APPROVED_REQUEST_SHA256 --approve
```

That live operation permits exactly one NVIDIA inference request and zero other provider requests. Any result or ambiguity stops the operation; no retry is authorized.

---

## Stop Conditions

Stop without provider contact if work would require:
1. a frozen/predecessor-path change without a prior plan amendment;
2. a live request to make tests pass;
3. `/v1/models`;
4. retry/replay/fallback behavior;
5. persisting/printing credential or Authorization data;
6. reconstructing body after approval instead of persisted exact bytes;
7. local I/O/settings/catalog/routing work between provider-start and executor;
8. a second provider-start/executor call for one canary;
9. retransmission after durable provider-start without terminal;
10. automatic evidence repair;
11. an MCP inference tool or runtime promotion;
12. merge/rebase/force-push of shared history.

Preserve completed reviewed commits and report the exact blocker and next safe action.

---

## Execution Discipline

- Use `superpowers:subagent-driven-development` when a subagent-capable coding environment is available; otherwise execute inline task-by-task with identical TDD/review gates.
- Tasks 1-3: standard-capability implementation/review.
- Task 4: strongest available implementation/review; highest-risk concurrency/authorization boundary.
- Task 5: strong implementation/review for outcome/crash semantics.
- Task 6: lighter implementation, standard review.
- Task 7: independent security review; no generic production-repair authority.
- Task 8: strongest available whole-branch review.
- Task 9: controller/operator only; no provider call.
- Never run implementation tasks concurrently.
- Use each task's pre-implementation HEAD as review BASE.
- After every completed/reviewed task: commit, fast-forward push to `feat/nvidia-provider-n02-lightning-canary`, verify remote SHA, continue.
- Never force-push.

## Self-Review Result

- Spec coverage: Sections 1-35 are covered by Global Constraints, Tasks 1-9, or the explicit live-transmission boundary.
- Interface ordering: Task 1 defines evidence types/root only; Task 2 adds pre-terminal persistence; Task 3 adds prepare/inspect; Task 4 adds transmit/start; Task 5 adds terminal schema; Task 6 adds CLI; later tasks consume only earlier interfaces.
- Terminal sequencing conflict removed: `append_terminal()` is introduced only in Task 5.
- Security-repair ambiguity removed: Task 7 failures require an exact plan amendment before production repair.
- Credential boundary explicit: Tasks 1-3/6 prepare/inspect never load settings; Task 4 loads key only before provider-start; Task 9 removes any session key and stops before transmit.
- Live provider request remains outside implementation authorization.
