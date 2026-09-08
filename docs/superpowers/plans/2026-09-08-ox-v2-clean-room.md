# OX V2 Clean-room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean-room OX V2 in Byte-MCP that freezes one exact review request, consumes one durable send opportunity, initiates at most one Vercel AI Gateway HTTP request, persists streamed response bytes before interpretation, and never resends.

**Architecture:** V1 remains frozen in `src/byte_mcp/ox/`. V2 lives independently in `src/byte_mcp/ox_v2/`, uses a separate SQLite evidence root, and exposes only `ox_v2_prepare`, `ox_v2_send`, and `ox_v2_get`. Synchronous SEND ownership is not implemented until a provider-free 930-second deployed MCP lifetime probe passes; if that gate fails, stop for architecture review.

**Tech Stack:** Python 3.12, FastMCP 1.28.1, stdlib `sqlite3`, Dulwich 1.2.x, HTTPX 0.28.x, pytest, Ruff, Windows PowerShell/Pester launcher qualification.

**Spec:** `docs/superpowers/specs/2026-09-08-ox-v2-clean-room-design.md`

## Global Constraints

- Governing guarantee: **Byte-MCP initiates at most one Vercel AI Gateway HTTP request per prepared review.**
- Final V2 public tools are exactly `ox_v2_prepare`, `ox_v2_send`, and `ox_v2_get`.
- V1 production code under `src/byte_mcp/ox/` is frozen; V2 production modules must not import from `byte_mcp.ox`.
- V1 evidence remains separate and unchanged. V2 defaults to `%LOCALAPPDATA%\Byte-MCP\ox-v2\evidence.sqlite3` on Windows.
- One prepared review permits one durable send opportunity. There is no A002/retry workflow.
- No continuation, revalidation, provider lanes, leases, heartbeats, orphan recovery, restart reconciliation, background worker, provider abstraction framework, automatic parse recovery, or fallback to V1.
- `ox_v2_send` accepts only `review_id` and `prepared_sha256`; it cannot redefine scope, model, provider, payload, timeout, or other execution settings.
- PREPARE uses no provider credential and performs zero provider networking.
- Initial fixed provider profile: endpoint `https://ai-gateway.vercel.sh/v1/chat/completions`, model `zai/glm-5.3-flash`, provider allow-list `zai` only, `stream=true`, `max_tokens=65536`, reasoning effort `medium`.
- Transport: one POST, `follow_redirects=False`, `trust_env=False`, TLS verification enabled, no local retry/reconnect/resume/fallback, 900-second total deadline, 10-second connect cap, 30-second write cap.
- Canonical response evidence is the HTTP content-decoded body bytes yielded by HTTPX `aiter_bytes()` before UTF-8/SSE/JSON interpretation.
- Limits: 200 artifacts, 2 MiB request body, 16 MiB durable response body, 64 KiB response chunk target, 1 MiB SSE event, 8 KiB public status result.
- `base_ref` and `target_ref` may identify bounded local Git refs, but PREPARE resolves them once to exact 40-hex commit IDs without network access; only resolved IDs enter frozen evidence.
- Exact request bytes are persisted before approval and supplied to HTTPX without JSON reserialization.
- Received bytes are committed before parsing. Partial or incomplete streams never become `COMPLETED`.
- Any uncertain exception after transport invocation is `OUTCOME_UNKNOWN`; no automatic resend follows any outcome.
- Durable/public `TRANSMITTING` is intentionally omitted. An existing attempt without a final outcome projects as `OUTCOME_UNKNOWN`.
- Operational diagnostics contain only bounded numeric/timing/enumerated fields, never arbitrary exception strings, traceback, headers, body excerpts, proxy values, environment values, certificate paths, or repository content.
- All automated transport tests block non-loopback networking.
- This plan authorizes no live OX provider request. A live canary requires a separate Nolan approval after provider-free qualification and runtime-promotion gates pass.

## File Map

Production:

- `src/byte_mcp/ox_v2/__init__.py` — package marker only.
- `src/byte_mcp/ox_v2/store.py` — SQLite schema, immutable preparation, unique claim, chunks, receipt seal, finalization, GET projection.
- `src/byte_mcp/ox_v2/prepare.py` — clean-room repository policy, exact-commit artifact collection, deterministic manifest and request bytes.
- `src/byte_mcp/ox_v2/send.py` — preflight, unique claim, one HTTP request, incremental durable receipt, bounded transport failures.
- `src/byte_mcp/ox_v2/response.py` — pure SSE parsing and terminal response validation from durable bytes.
- `src/byte_mcp/ox_v2/tools.py` — paths/config, three bounded MCP functions, paid-egress gate, registration.
- `src/byte_mcp/server.py` — register V2 tools; V1 execution is quiesced before V2 work begins.
- `config/ox-v2-repositories.example.json` — independent V2 allow-list example.
- `tests/ox_v2/helpers.py` — isolated Git/SQLite/loopback fixtures.
- `tests/ox_v2/test_store.py`
- `tests/ox_v2/test_prepare.py`
- `tests/ox_v2/test_response.py`
- `tests/ox_v2/test_send.py`
- `tests/ox_v2/test_tools.py`
- `tests/ox_v2/test_crash_and_concurrency.py`
- `qualification/ox-v2/mcp-lifetime.json` — observed provider-free deployed lifetime result after PASS.
- `docs/OX-V2.md` — operator-facing contract.

Temporary qualification-only file:

- `src/byte_mcp/ox_v2/lifetime_probe.py` — removed after the deployed lifetime gate.

---

### Task 0: Close the last V1 canary and quiesce V1 execution

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/ox/test_mcp_surface.py`
- Modify: `tests/test_server.py`
- Create after observed terminalization: `qualification/ox-v1/final-evidence.json`

**Interfaces:**
- Consumes only provider-free evidence for existing `OX-000013-A001`.
- Produces a server with no V1 provider-bearing OX registration and no V1 runtime initialization. `src/byte_mcp/ox/` remains byte-unchanged.

- [ ] **Step 1: Verify `OX-000013-A001` is durably terminal before quiescing V1**

Use only:

```text
ox_get_review(review_id="OX-000013", view="summary")
ox_get_review(review_id="OX-000013", view="attempts")
```

Require a durable terminal outcome and `provider_finished_at`. If the attempt is still unfinalized, STOP. Do not call `ox_review`, `ox_continue`, `ox_revalidate`, Wolfram, or any provider.

- [ ] **Step 2: Record the final V1 evidence inventory**

Generate `qualification/ox-v1/final-evidence.json` from the local V1 evidence root. Every file entry contains only relative path, byte length, and SHA-256. Derive all values from disk; never hand-enter counts or hashes. The top-level record contains:

```python
record = {
    "protocol": "ox-v1-final-evidence-v1",
    "baseline_commit": "94ff28810a06b7af2207196ac98c1152cc65b4b1",
    "last_review_id": "OX-000013",
    "provider_requests_during_inventory": 0,
    "files": files,
}
```

- [ ] **Step 3: Write RED server tests for quiesced V1 execution**

Require:

```python
registered = server.mcp._tool_manager._tools
assert "ox_review" not in registered
assert "ox_continue" not in registered
assert "ox_revalidate" not in registered
assert "ox_get_review" not in registered
```

Update `tests/test_server.py` so `main()` initializes core service and binds MCP without initializing V1 OX. Wolfram remains lazy.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/test_server.py tests/ox/test_mcp_surface.py -q
```

Expected: FAIL because current server still exposes/initializes V1 OX.

- [ ] **Step 5: Remove V1 registration/startup from `server.py` only**

Remove V1 OX imports, runtime singleton/factory, helper dispatch, four V1 tool registrations, and the `ox_runtime()` call from `main()`. Do not modify or delete anything under `src/byte_mcp/ox/`. Do not add compatibility fallback.

- [ ] **Step 6: Verify V1 package and evidence byte identity**

Compare `src/byte_mcp/ox/` against commit `94ff28810a06b7af2207196ac98c1152cc65b4b1`, and compare live V1 evidence to the inventory. Both must match.

- [ ] **Step 7: Run provider-free regressions**

```bash
python -m pytest tests/test_server.py tests/ox/test_mcp_surface.py tests/wolfram/test_mcp_surface.py -q
python -m ruff check src/byte_mcp/server.py tests/test_server.py tests/ox/test_mcp_surface.py
```

Expected: PASS; zero OX/Wolfram provider requests.

- [ ] **Step 8: Commit**

```bash
git add src/byte_mcp/server.py tests/test_server.py tests/ox/test_mcp_surface.py qualification/ox-v1/final-evidence.json
git commit -m "chore: quiesce legacy OX execution"
```

- [ ] **Step 9: STOP for explicit provider-free runtime-promotion authorization**

Do not deploy the quiesce automatically.

---

### Task 1: V2-01 provider-free deployed MCP lifetime gate

**Files:**
- Create: `src/byte_mcp/ox_v2/__init__.py`
- Create temporarily: `src/byte_mcp/ox_v2/lifetime_probe.py`
- Modify temporarily: `src/byte_mcp/server.py`
- Create temporarily: `tests/ox_v2/test_lifetime_probe.py`
- Create after PASS: `qualification/ox-v2/mcp-lifetime.json`

**Interfaces:**
- Produces temporarily: `async def run_probe() -> dict[str, object]` and temporary MCP tool `ox_v2_lifetime_probe()` with no arguments.
- Gate PASS requires the actual Web UI → MCP → deployed Byte-MCP invocation to wait 930 seconds and return to the same caller.

- [ ] **Step 1: Write RED test**

```python
import asyncio
from byte_mcp.ox_v2 import lifetime_probe


def test_probe_waits_exact_duration(monkeypatch):
    waits: list[float] = []
    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    result = asyncio.run(lifetime_probe.run_probe())
    assert waits == [930.0]
    assert result["status"] == "PASS"
    assert result["requested_seconds"] == 930
```

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_lifetime_probe.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement temporary probe**

```python
import asyncio
from datetime import UTC, datetime

_PROBE_SECONDS = 930.0

async def run_probe() -> dict[str, object]:
    started_at = datetime.now(UTC).isoformat()
    await asyncio.sleep(_PROBE_SECONDS)
    return {
        "status": "PASS",
        "requested_seconds": 930,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
    }
```

Register a temporary read-only `ox_v2_lifetime_probe()` in `server.py`. It must load no OX credential, no OX runtime, no Wolfram service, no repository file, and no network client.

- [ ] **Step 4: Focused qualification**

```bash
python -m pytest tests/ox_v2/test_lifetime_probe.py tests/test_server.py tests/ox/test_mcp_surface.py -q
python -m ruff check src/byte_mcp/ox_v2/lifetime_probe.py tests/ox_v2/test_lifetime_probe.py src/byte_mcp/server.py
```

- [ ] **Step 5: Commit probe**

```bash
git add src/byte_mcp/ox_v2 src/byte_mcp/server.py tests/ox_v2/test_lifetime_probe.py tests/ox/test_mcp_surface.py
git commit -m "test: add temporary OX V2 MCP lifetime probe"
```

- [ ] **Step 6: STOP for explicit provider-free runtime-promotion authorization**

No provider request is permitted.

- [ ] **Step 7: After authorization, invoke the deployed probe exactly once from ChatGPT Web UI**

```text
ox_v2_lifetime_probe()
```

If the call disconnects, cancels, or fails before the 930-second receipt returns, record FAIL and STOP THE V2 IMPLEMENTATION FOR ARCHITECTURE REVIEW. Do not implement a background worker.

- [ ] **Step 8: Record PASS evidence using only observed values**

Persist protocol, probe seconds, PASS, source path, provider request count 0, Wolfram request count 0, exact deployed probe commit, and exact returned `started_at`/`finished_at` in `qualification/ox-v2/mcp-lifetime.json`.

- [ ] **Step 9: Remove probe and its test/registration**

Run server/MCP regressions and confirm no `ox_v2_lifetime_probe` is registered.

- [ ] **Step 10: Commit PASS evidence and removal**

```bash
git add -A
git commit -m "test: qualify synchronous OX V2 MCP lifetime"
```

---

### Task 2: V2-02 SQLite evidence contract

**Files:**
- Create: `src/byte_mcp/ox_v2/store.py`
- Create: `tests/ox_v2/test_store.py`
- Create: `tests/ox_v2/helpers.py`

**Interfaces:**
- `V2Store.prepare(...) -> PreparedRecord`
- `V2Store.get(review_id: str) -> dict[str, object]`
- `V2Store.claim(review_id: str, prepared_sha256: str) -> ClaimResult`
- `V2Store.append_chunk(review_id: str, sequence: int, chunk: bytes) -> None`
- `V2Store.seal_receipt(...) -> None`
- `V2Store.finalize(review_id: str, outcome: str) -> None`

- [ ] **Step 1: Write RED immutable/claim test**

```python
store = V2Store(tmp_path / "evidence.sqlite3")
prepared = store.prepare(
    review_id="OXV2-11111111111111111111111111111111",
    prepared_sha256="a" * 64,
    request_sha256="b" * 64,
    repository_id="byte-mcp",
    subsystem_id="ox-validation",
    base_commit="1" * 40,
    target_commit="2" * 40,
    artifact_count=3,
    request_body=b"{}",
    manifest=b"{}",
    model_id="zai/glm-5.3-flash",
)
first = store.claim(prepared.review_id, prepared.prepared_sha256)
second = store.claim(prepared.review_id, prepared.prepared_sha256)
assert first.claimed is True
assert second.claimed is False
```

Also assert prepared UPDATE/DELETE and attempt DELETE are rejected.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_store.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement exactly three application tables**

```sql
CREATE TABLE prepared_review (
    review_id TEXT PRIMARY KEY,
    prepared_sha256 TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    subsystem_id TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    target_commit TEXT NOT NULL,
    artifact_count INTEGER NOT NULL CHECK (artifact_count >= 0),
    request_byte_count INTEGER NOT NULL CHECK (request_byte_count >= 0),
    model_id TEXT NOT NULL,
    manifest BLOB NOT NULL,
    request_body BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE attempt (
    review_id TEXT PRIMARY KEY REFERENCES prepared_review(review_id),
    prepared_sha256 TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    http_complete INTEGER,
    body_sha256 TEXT,
    durable_body_bytes INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    headers_after_ms INTEGER,
    first_byte_after_ms INTEGER,
    last_byte_after_ms INTEGER,
    elapsed_ms INTEGER,
    error_category TEXT,
    final_outcome TEXT CHECK (final_outcome IN ('COMPLETED','FAILED','OUTCOME_UNKNOWN'))
);
CREATE TABLE response_chunk (
    review_id TEXT NOT NULL REFERENCES attempt(review_id),
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    body BLOB NOT NULL,
    PRIMARY KEY (review_id, sequence)
);
```

Set `PRAGMA user_version=1`, `foreign_keys=ON`, `journal_mode=DELETE`, `synchronous=FULL`, and finite `busy_timeout`. Add narrow triggers enforcing immutable prepared rows, immutable claim identity, append-only chunks, no chunk after seal, and write-once final outcome.

`claim()` uses `BEGIN IMMEDIATE`; only an INSERT whose COMMIT definitely succeeds returns `claimed=True`. Any claim/commit exception grants no send authority.

- [ ] **Step 4: Add append/seal/finalize tests**

Assert contiguous chunk sequence, no duplicates/gaps, no chunks after seal, final outcome write-once, and `COMPLETED` requires sealed complete response with matching durable digest/length.

- [ ] **Step 5: Run focused tests**

```bash
python -m pytest tests/ox_v2/test_store.py -q
python -m ruff check src/byte_mcp/ox_v2/store.py tests/ox_v2
```

- [ ] **Step 6: Commit**

```bash
git add src/byte_mcp/ox_v2/store.py tests/ox_v2
git commit -m "feat: add OX V2 transactional evidence store"
```

---

### Task 3: V2-03 deterministic clean-room PREPARE

**Files:**
- Create: `src/byte_mcp/ox_v2/prepare.py`
- Create: `config/ox-v2-repositories.example.json`
- Create: `tests/ox_v2/test_prepare.py`
- Modify: `tests/ox_v2/helpers.py`

**Interfaces:**
- `prepare_review(repository_id, subsystem_id, base_ref, target_ref, *, repositories_file, store) -> dict[str, object]`
- Fixed profile constants: `MODEL_ID`, `GATEWAY_URL`, `MAX_OUTPUT_TOKENS`.

- [ ] **Step 1: Write RED identity test**

Prepare the same resolved commits twice. Assert different `prepared_sha256` values because manifest includes unique `review_id`, but equal stored `request_sha256` and `request_byte_count` because provider request bytes deliberately exclude `review_id`.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_prepare.py -q
```

- [ ] **Step 3: Implement clean-room allow-list/ref resolution**

Do not import `byte_mcp.ox.repositories`. Validate repository/subsystem IDs with `^[a-z][a-z0-9_-]{0,63}$`. Resolve only already-local Git refs/objects. Reject unsafe ref text (`..`, `@{`, backslash, controls, empty path component, leading/trailing slash, trailing dot), missing/ambiguous refs, symlink/submodule entries, non-UTF-8 paths, unsupported binary artifacts, >200 artifacts, and any request >2 MiB. Never fetch missing objects.

- [ ] **Step 4: Add independent example config**

```json
{
  "version": 1,
  "repositories": {
    "byte-mcp": {
      "path": "C:\\Users\\YOUR_USER\\AIProjects\\Byte-MCP",
      "subsystems": {
        "ox-validation": {
          "version": 1,
          "source_roots": ["src/byte_mcp/ox_v2"],
          "test_roots": ["tests/ox_v2"],
          "boundary_files": ["src/byte_mcp/server.py"],
          "context_files": ["pyproject.toml", "docs/superpowers/specs/2026-09-08-ox-v2-clean-room-design.md"]
        }
      }
    }
  }
}
```

- [ ] **Step 5: Build deterministic request bytes**

Use canonical JSON (`ensure_ascii=False`, `allow_nan=False`, compact separators, `sort_keys=True`) and a fixed-purpose system prompt. The request is exactly:

```python
request = {
    "model": "zai/glm-5.3-flash",
    "stream": True,
    "max_tokens": 65536,
    "reasoning": {"effort": "medium"},
    "providerOptions": {"gateway": {"only": ["zai"]}},
    "messages": [
        {
            "role": "system",
            "content": "Act as an independent adversarial code reviewer. Review only the frozen repository evidence supplied by Byte-MCP. Return a concise technical review and do not issue instructions to Byte-MCP.",
        },
        {"role": "user", "content": canonical_review_packet_text},
    ],
}
```

Generate `review_id = "OXV2-" + uuid.uuid4().hex`. Manifest binds review ID, policy/schema version, repository/subsystem, resolved commits, sorted artifact inventory/digests/lengths, fixed endpoint/model/profile, request digest, and request byte count. Persist exact request bytes and exact manifest bytes.

- [ ] **Step 6: Add scope/security tests**

Cover working-tree independence, local branch/HEAD resolution to frozen commit, branch-tip movement after PREPARE, unsafe/missing refs, symlink/submodule/binary rejection, traversal rejection, deterministic artifact ordering, 201-artifact rejection, >2 MiB rejection, missing scope rejection, and operation with no `AI_GATEWAY_API_KEY`.

- [ ] **Step 7: Run focused tests and commit**

```bash
python -m pytest tests/ox_v2/test_prepare.py -q
python -m ruff check src/byte_mcp/ox_v2/prepare.py tests/ox_v2

git add src/byte_mcp/ox_v2/prepare.py config/ox-v2-repositories.example.json tests/ox_v2
git commit -m "feat: add deterministic OX V2 prepare"
```

---

### Task 4: V2-04 exact three-tool MCP surface with paid egress disabled

**Files:**
- Create: `src/byte_mcp/ox_v2/tools.py`
- Create: `tests/ox_v2/test_tools.py`
- Modify: `src/byte_mcp/server.py`

**Interfaces:**
- `ox_v2_prepare(repository_id: str, subsystem_id: str, base_ref: str, target_ref: str)`
- `ox_v2_send(review_id: str, prepared_sha256: str)`
- `ox_v2_get(review_id: str)`

- [ ] **Step 1: Write RED exact-surface test**

```python
registered = server.mcp._tool_manager._tools
assert {name for name in registered if name.startswith("ox_v2_")} == {
    "ox_v2_prepare", "ox_v2_send", "ox_v2_get"
}
```

Also assert exact function signatures and annotations: GET read-only/openWorld false, PREPARE openWorld false, SEND openWorld true.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_tools.py -q
```

- [ ] **Step 3: Implement path/config helpers**

Resolve:

```text
BYTE_MCP_OX_V2_REPOSITORIES_FILE -> config/ox-v2-repositories.local.json
BYTE_MCP_OX_V2_EVIDENCE_DIR      -> %LOCALAPPDATA%\Byte-MCP\ox-v2
BYTE_MCP_OX_V2_EGRESS_ENABLED     -> false unless exactly 1
```

Only SEND loads `AI_GATEWAY_API_KEY`. PREPARE/GET work without it. Do not add a runtime singleton, startup recovery, or startup provider check.

- [ ] **Step 4: Implement bounded GET**

Return identity, commits, artifact/request counts, model, state, and bounded attempt diagnostics only. Omit absent nullable fields. State projection: no attempt → PREPARED; final outcome → final; attempt without final → OUTCOME_UNKNOWN.

- [ ] **Step 5: Prove egress disabled is provider-free**

With `BYTE_MCP_OX_V2_EGRESS_ENABLED` unset, SEND returns bounded `POLICY_DENIED`, creates no attempt, and never invokes sender/networking.

- [ ] **Step 6: Regress MCP schemas**

```bash
python -m pytest tests/ox_v2/test_tools.py tests/test_server.py tests/wolfram/test_mcp_surface.py -q
python -m ruff check src/byte_mcp/server.py src/byte_mcp/ox_v2/tools.py tests/ox_v2/test_tools.py
```

- [ ] **Step 7: Commit**

```bash
git add src/byte_mcp/server.py src/byte_mcp/ox_v2/tools.py tests/ox_v2/test_tools.py
git commit -m "feat: expose bounded OX V2 tools"
```

---

### Task 5: V2-05 at-most-once SEND claim and replay semantics

**Files:**
- Create: `src/byte_mcp/ox_v2/send.py`
- Create: `tests/ox_v2/test_send.py`
- Modify: `src/byte_mcp/ox_v2/tools.py`

**Interfaces:**
- `async def send_review(review_id, prepared_sha256, *, store, api_key, transport=None) -> dict[str, object]`

- [ ] **Step 1: Write RED replay test with counting fake transport**

Prepare one review, call SEND twice, assert fake transport call count is exactly one and the second call returns existing evidence.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_send.py -q
```

- [ ] **Step 3: Implement preflight before claim**

Before `store.claim`: verify exact identity, stored manifest/request digests, current policy still permits repository ID/fixed endpoint, fixed profile matches manifest, and API key is present. Failures before claim leave PREPARED.

After `claim()` succeeds, no path may delete/release/reset the attempt. `claimed=False` returns existing evidence without transport.

- [ ] **Step 4: Add uncertain-claim-commit test**

Inject a store whose claim raises `sqlite3.OperationalError` after an ambiguous local commit simulation. Assert transport count remains zero; sender must not reread the row and assume ownership.

- [ ] **Step 5: Run/commit**

```bash
python -m pytest tests/ox_v2/test_send.py tests/ox_v2/test_store.py -q
python -m ruff check src/byte_mcp/ox_v2/send.py tests/ox_v2

git add src/byte_mcp/ox_v2/send.py src/byte_mcp/ox_v2/tools.py tests/ox_v2
git commit -m "feat: enforce single OX V2 send opportunity"
```

---

### Task 6: V2-06 one streaming HTTP request with durable chunk receipt

**Files:**
- Modify: `src/byte_mcp/ox_v2/send.py`
- Modify: `tests/ox_v2/test_send.py`
- Create: `tests/ox_v2/test_transport_loopback.py`

**Interfaces:**
- Production transport receives exact stored body bytes and appends each content-decoded chunk to `V2Store` before any parser sees it.

- [ ] **Step 1: Write RED loopback exact-body/one-request test**

Use `asyncio.start_server` to capture the request and emit fragmented SSE. Assert captured request body equals stored approved bytes, durable response equals emitted SSE bytes, and request count is one. Set ambient proxy variables to a dead proxy and prove the test still works through `trust_env=False`.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_transport_loopback.py -q
```

- [ ] **Step 3: Implement exactly one HTTPX stream**

```python
_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
_TOTAL_DEADLINE_SECONDS = 900.0

async with httpx.AsyncClient(
    timeout=_TIMEOUT,
    follow_redirects=False,
    trust_env=False,
) as client:
    async with asyncio.timeout(_TOTAL_DEADLINE_SECONDS):
        async with client.stream(
            "POST",
            GATEWAY_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=stored_request_body,
        ) as response:
            async for chunk in response.aiter_bytes(chunk_size=65536):
                ...
```

Do not use `json=...`. Do not add retry, redirect, fallback, reconnect, authentication resend, or stream resume.

For every non-empty chunk: enforce 16 MiB projected limit, commit chunk, then update in-memory timing counters. Do not parse during receipt.

- [ ] **Step 4: Implement bounded diagnostics/failure categories**

Persist only claimed time, header/first/last byte elapsed ms, elapsed ms, numeric HTTP status, durable byte count, and fixed `error_category`. Map remote protocol before generic read error. Never persist exception text.

- [ ] **Step 5: Add no-retry cases**

Cover redirect 307, 429, mid-body close, close before body, response over 16 MiB, absolute deadline, and cancellation. Every claimed case observes at most one POST. Truncation/close/deadline/cancellation after invocation are OUTCOME_UNKNOWN.

- [ ] **Step 6: Run/commit**

```bash
python -m pytest tests/ox_v2/test_send.py tests/ox_v2/test_transport_loopback.py -q
python -m ruff check src/byte_mcp/ox_v2/send.py tests/ox_v2

git add src/byte_mcp/ox_v2/send.py tests/ox_v2
git commit -m "feat: stream OX V2 response into durable evidence"
```

---

### Task 7: V2-07 pure SSE completion validation and final outcome

**Files:**
- Create: `src/byte_mcp/ox_v2/response.py`
- Create: `tests/ox_v2/test_response.py`
- Modify: `src/byte_mcp/ox_v2/send.py`

**Interfaces:**
- `parse_complete_response(body: bytes, http_status: int) -> ParsedReview`
- `ResponseFailure(category: str, definitive: bool)`

- [ ] **Step 1: Write RED success/incomplete tests**

```python
body = (
    b'data: {"choices":[{"delta":{"content":"review"},"finish_reason":null}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: [DONE]\n\n'
)
parsed = parse_complete_response(body, 200)
assert parsed.content == "review"
```

Also assert missing `[DONE]` raises non-definitive `STREAM_INCOMPLETE`.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest tests/ox_v2/test_response.py -q
```

- [ ] **Step 3: Implement bounded SSE parser over durable bytes only**

Parse UTF-8 only after receipt is sealed. Support `data:` fields and comments; reject unsupported non-empty fields. Enforce 1 MiB per event. JSON events must be objects. Require exactly one relevant choice. Concatenate string `delta.content`; accept only `finish_reason="stop"`; require `[DONE]`. `length`, `content_filter`, `tool_calls`, refusal, unknown finish reason, or empty final content are definitive unsuccessful results. Malformed/truncated JSON or missing DONE is non-definitive and OUTCOME_UNKNOWN.

- [ ] **Step 4: Wire finalization ordering**

On clean HTTP completion: seal receipt → read durable body back from store → parse durable body → finalize outcome → only then return MCP result. Never parse an in-memory network buffer as authority.

- [ ] **Step 5: Add response matrix**

Cover valid success, non-success HTTP, explicit SSE error, length/tool-call termination, malformed JSON, missing DONE, DONE without stop, transport failure after apparent terminal event, and empty content.

- [ ] **Step 6: Run/commit**

```bash
python -m pytest tests/ox_v2/test_response.py tests/ox_v2/test_send.py tests/ox_v2/test_transport_loopback.py -q
python -m ruff check src/byte_mcp/ox_v2 tests/ox_v2

git add src/byte_mcp/ox_v2 tests/ox_v2
git commit -m "feat: validate complete OX V2 SSE responses"
```

---

### Task 8: V2-08 process concurrency, crash, restart, storage-failure, and privacy qualification

**Files:**
- Create: `tests/ox_v2/test_crash_and_concurrency.py`
- Modify: `tests/ox_v2/helpers.py`
- Modify production only when a RED test identifies a contract defect.

**Interfaces:**
- Verifies existing interfaces; adds no capability.

- [ ] **Step 1: Multiprocess single-claim test**

Two processes claim the same prepared review against the same SQLite DB. Require exactly one `claimed=True` and exactly one attempt row.

- [ ] **Step 2: Multiprocess full-SEND test**

Two processes SEND the same identity against one loopback server. Require at most one POST and one durable attempt.

- [ ] **Step 3: Forced termination matrix**

Kill child process at: before claim commit; after claim before transport; after headers; after first durable chunk; after full chunks before seal; after seal before finalization; after final outcome before MCP return. Reopen store in a fresh process and assert: before claim → PREPARED; every post-claim boundary → existing attempt/no new send authority; final committed → exact final returned on replay. Startup performs zero networking.

- [ ] **Step 4: Storage-failure tests**

Inject chunk-commit, seal, and finalization failures. Never report undurable success. Once claim exists, replay never transports again.

- [ ] **Step 5: Privacy sentinel test**

Seed sentinel values in fake credential, exception string, ambient proxy values, response body, and repository path. Inspect public tool returns, logging, attempt metadata, and audit output. Sentinels may exist only inside restricted frozen request/response evidence when intentionally part of those bodies.

- [ ] **Step 6: V1 isolation test**

AST-scan every `src/byte_mcp/ox_v2/*.py`; no import may start with `byte_mcp.ox`. Verify V1 evidence inventory and `src/byte_mcp/ox/` hashes remain unchanged.

- [ ] **Step 7: Run full provider-free test suite**

```bash
python -m pytest tests/ox_v2 -q
python -m pytest -q
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m ruff check .
```

- [ ] **Step 8: Commit**

```bash
git add tests/ox_v2 src/byte_mcp/ox_v2
git commit -m "test: qualify OX V2 crash and replay boundaries"
```

---

### Task 9: V2-09 documentation, V1 freeze guard, and full local qualification

**Files:**
- Create: `docs/OX-V2.md`
- Modify: `README.md`
- Create: `tests/ox_v2/test_v1_freeze.py`

**Interfaces:**
- Adds no runtime capability.

- [ ] **Step 1: Add V1 freeze guard**

Check `src/byte_mcp/ox/` path/blob identities against baseline `94ff28810a06b7af2207196ac98c1152cc65b4b1`. Any later mutation inside the frozen package fails.

- [ ] **Step 2: Write `docs/OX-V2.md`**

Document PREPARE → conversational approval → SEND once → GET; local at-most-once Gateway initiation; one-review/one-send-opportunity; no retry/continuation/revalidation; separate SQLite evidence; OUTCOME_UNKNOWN semantics; exact egress flag; credential source; V1 isolation; and separate live-canary authorization.

- [ ] **Step 3: Add README pointer**

Link accepted spec and operator doc. Label V1 execution legacy/quiesced after final V1 canary closure.

- [ ] **Step 4: Full local qualification**

```bash
python -m pip check
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m ruff check .
python -m pytest
pwsh -NoLogo -NoProfile -File .\scripts\Check-Launcher.ps1
```

Require all PASS, V1 freeze guard PASS, zero OX provider requests, zero Wolfram provider requests.

- [ ] **Step 5: Verify final V2 tool surface**

Exactly `ox_v2_prepare`, `ox_v2_send`, `ox_v2_get`; no lifetime probe/retry/continuation/revalidation/recovery/alternate transport tool.

- [ ] **Step 6: Commit**

```bash
git add docs/OX-V2.md README.md tests/ox_v2
git commit -m "docs: close OX V2 local qualification contract"
```

---

### Task 10: V2-10 provider-free runtime promotion and live-canary boundary

**Files:**
- No production changes unless provider-free promotion exposes a defect; defects return to RED/GREEN development before another promotion attempt.

**Interfaces:**
- Consumes fully qualified candidate.
- Produces no provider request without new explicit Nolan approval.

- [ ] **Step 1: STOP for explicit transactional runtime-promotion authorization**

Present exact candidate commit, spec ancestry, full qualification results, V1 freeze guard, lifetime PASS evidence, and statement that paid egress remains disabled.

- [ ] **Step 2: After authorization, promote with paid egress disabled**

Require exact deployed HEAD, clean detached runtime, unchanged supervisor/launcher artifacts unless separately approved, READY/active, unchanged V1 evidence inventory, V2 tools discoverable, PREPARE/GET provider-free smoke tests, SEND returns POLICY_DENIED, zero OX/Wolfram requests.

- [ ] **Step 3: Provider-free post-promotion stability**

Run a bounded stability window crossing the historical supervisor cadence. Require stable server/tunnel identities and no repair/restart/provider calls.

- [ ] **Step 4: STOP at the live-canary boundary**

No live request is authorized by this plan. A later canary requires separate authorization to enable V2 paid egress, PREPARE one exact review, approve its `review_id + prepared_sha256`, and send exactly once. Ambiguity/failure ends the canary; another paid attempt requires a fresh PREPARE and fresh approval.

---

## Post-acceptance V1 retrieval follow-up

The accepted architecture retains V1 history through a separately named read-only retrieval surface, but that surface is deliberately not part of the V2 execution package and must not keep V1 runtime writers alive during the rebuild. After a successful V2 canary and explicit Nolan acceptance, prepare a separate bounded decommission change with its own review gate:

- expose a separately named read-only legacy retrieval tool such as `ox_v1_get_review`;
- do not register V1 send/continue/revalidate operations;
- do not initialize `OXProviderJobManager`, stale-transmission recovery, provider client, or any V1 writer;
- prove the adapter performs no writes against `qualification/ox-v1/final-evidence.json`;
- keep it outside `src/byte_mcp/ox_v2/` so V2 never imports/interprets V1 formats;
- require new explicit authorization before deployment.

## Plan Self-Review

- **Spec coverage:** Tasks 0–10 cover V1 closure/quiesce, mandatory lifetime gate, clean-room isolation, SQLite evidence/claim model, deterministic PREPARE, exact three-tool surface, at-most-once proof, streaming durable receipt, SSE completion validation, crash/restart/storage/privacy qualification, provider-free promotion, and the separate live-canary boundary.
- **Simplification preserved:** No durable/public TRANSMITTING state; no worker/recovery/retry framework; no V1 import from V2.
- **Type consistency:** `review_id + prepared_sha256` is the only SEND identity throughout; there is no public attempt ID.
- **No synthetic evidence:** Runtime-generated commit IDs, timestamps, counts, and hashes are always recorded from observed data, never guessed.
- **Authorization boundary:** This plan authorizes no live provider request; every runtime promotion and live-canary transition contains an explicit STOP gate.
