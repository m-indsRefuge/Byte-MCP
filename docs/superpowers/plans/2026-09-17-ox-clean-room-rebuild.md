# OX Clean-Room Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully archive and remove OX V1/V2, then build a new synchronous two-tool OX adversarial code-review subsystem that snapshots current repository state under Byte-MCP authority, sends at most one Vercel AI Gateway → Z.AI request per authorized review, preserves durable local evidence, and returns OX's free-form review.

**Architecture:** Build a new `byte_mcp.ox` package from scratch on the current NVIDIA-capable Byte-MCP lineage. Reuse only provider-neutral request identity, authorization, outcome, and one-shot transport primitives that already exist under `byte_mcp.providers`; OX owns repository scope, snapshotting, packet construction, evidence, provider-envelope parsing, lifecycle, and MCP integration. The active implementation contains no OX V1/V2 execution code and no compatibility layer.

**Tech Stack:** Python 3.12, FastMCP 1.28.1, stdlib filesystem/hash/json/pathlib/tempfile/os/threading utilities, existing `httpx>=0.28.1,<1`, existing `byte_mcp.providers` primitives, pytest, Ruff, PowerShell launcher qualification.

**Spec:** `docs/superpowers/specs/2026-09-17-ox-clean-room-rebuild-design.md`

## Global Constraints

- Re-verify the implementation baseline immediately before execution. The approved design was written from `fb87e39d24ee2e74f648da0495059f147f30fb89`; do not assume that SHA remains the correct live/converged base without fresh evidence.
- Execute implementation in an isolated worktree created with `superpowers:using-git-worktrees`; do not implement on the design branch.
- Preserve exact archival Git identities for OX V1 and abandoned OX V2 before deleting active-tree code.
- Remove old `src/byte_mcp/ox/`, `src/byte_mcp/ox_v2/`, old OX execution tests, old OX MCP registrations, V2 lifetime probe, continuation/revalidation/retry/background machinery, and obsolete active OX execution docs from the new implementation lineage.
- Historical V1/V2 source/evidence/specs remain recoverable through Git history/archive refs. Do not migrate old evidence into the new runtime.
- New OX public MCP surface is exactly `ox_review(...)` and `ox_get_review(review_id)`.
- One explicit user authorization for one `ox_review` invocation authorizes the complete lifecycle, including at most one outbound provider request. There is no second approval gate.
- No automatic retry, reconnect, resume, continuation, revalidation, background worker, queue, provider polling, startup recovery, or second POST under the same review identity.
- OX remains code-review-only in the first release; no general chat/tool loop.
- Provider route remains `https://ai-gateway.vercel.sh/v1/chat/completions`, model `zai/glm-5.3-flash`, Z.AI-only gateway routing, `stream=false`, `reasoning.effort="medium"`, `max_tokens=65536`.
- OX may inspect only repositories contained beneath Byte-MCP's configured `projects` root (the `/AiProjects` mapping). Callers select repository names/relative scope; they never supply arbitrary absolute filesystem paths.
- Support `FULL_REPOSITORY` and `BOUNDED` review modes.
- Filesystem bytes at snapshot time are authoritative; committed, staged, unstaged, and eligible untracked files are reviewable.
- Symlinks/junctions are never followed. Submodule contents are not recursively imported automatically.
- Hard-exclude secrets/env/key material, `.git`, virtual environments, dependency caches, build/dist/cache/coverage output, binary/database/archive/media artifacts, IDE/runtime caches, and Byte-MCP evidence stores.
- Packet/request construction uses only frozen stored artifact bytes; never reread repository content after snapshot freeze.
- No silent truncation, summarization, file dropping, or multi-call splitting. Oversized full-repository reviews fail locally and recommend a bounded review; provider requests remain zero.
- Provider response is free-form prose. Do not impose JSON/findings/severity/decision schemas.
- Persist exact complete provider response bytes before decoding/extracting assistant content.
- Durable evidence uses one filesystem directory per review, not SQLite. Do not add a database unless implementation evidence proves the file model cannot satisfy the approved contract; such a finding requires architecture review.
- Once the single send claim is durably consumed, it is never deleted or reset. Crash/ambiguity after claim cannot restore send authority.
- `ox_get_review` is read-only/local and performs zero provider networking.
- OX must not import NVIDIA. NVIDIA must not import OX. OX must not invoke Wolfram.
- Existing NVIDIA, Wolfram, provider-neutral, core Byte-MCP, launcher, and runtime contracts remain regression-protected.
- No live OX, NVIDIA, Wolfram, Vercel, Z.AI, or other provider calls during implementation or provider-free qualification. HTTP tests use `httpx.MockTransport` or loopback only.
- Maintain `docs/FAILURE_MAP.md` coverage for the new OX subsystem before local qualification is complete.
- No runtime promotion and no real OX provider request without separate explicit authorization after the exact candidate is fully provider-free qualified.

## Frozen Initial Product Bounds

These implementation constants are fixed for the first build so the code and tests have one contract:

```text
OX_REVIEW_ID_PREFIX                 = "OX-"
OX_SNAPSHOT_POLICY_VERSION          = "ox-snapshot-v1"
OX_PACKET_POLICY_VERSION            = "ox-packet-v1"
OX_MAX_ARTIFACT_BYTES               = 1_000_000
OX_MAX_ARTIFACTS                    = 5_000
OX_MAX_SNAPSHOT_CONTENT_BYTES       = 3_250_000
OX_MAX_PACKET_BYTES                 = 3_500_000
provider prepared-request max       = existing 4_000_000 bytes
provider response max               = existing 8_000_000 decoded bytes
connect timeout                     = 10 seconds
write timeout                       = 30 seconds
read timeout                        = 600 seconds
pool timeout                        = 10 seconds
absolute deadline                   = 600 seconds
```

The 3.5 MiB packet bound intentionally leaves serialization headroom below the existing shared 4,000,000-byte prepared-request bound. If canonical request serialization still exceeds the provider-neutral bound, fail locally before claim/networking.

## New File Map

Production:

```text
src/byte_mcp/ox/__init__.py          exports only new OX public/internal types required by server/tests
src/byte_mcp/ox/models.py            immutable records, states, review/snapshot identities
src/byte_mcp/ox/settings.py          fixed provider profile + local evidence path/config
src/byte_mcp/ox/scope.py             `/AiProjects` repository authority and bounded/full scope resolution
src/byte_mcp/ox/snapshot.py          deterministic current-filesystem snapshot/exclusion/hash logic
src/byte_mcp/ox/packet.py            deterministic frozen packet and provider request assembly
src/byte_mcp/ox/evidence.py          per-review durable filesystem evidence + atomic send claim
src/byte_mcp/ox/client.py            exactly-one provider execution + free-form envelope extraction
src/byte_mcp/ox/service.py           synchronous end-to-end lifecycle and safe retrieval
src/byte_mcp/ox/runtime.py           lazy runtime loading/fail isolation
src/byte_mcp/server.py               exactly two new OX MCP tools; preserve NVIDIA/Wolfram/core
```

Config/docs:

```text
config/ox-repositories.example.json  optional repository aliases beneath projects root
archive/OX-ARCHIVE.md                exact V1/V2 archival identities and active-removal statement
docs/OX.md                           current operator contract
docs/FAILURE_MAP.md                  living failure boundaries including new OX subsystem
README.md                             current OX pointer and two-tool surface
```

Tests:

```text
tests/ox/test_models.py
tests/ox/test_scope.py
tests/ox/test_snapshot.py
tests/ox/test_packet.py
tests/ox/test_evidence.py
tests/ox/test_client.py
tests/ox/test_service.py
tests/ox/test_mcp_surface.py
tests/ox/test_security.py
tests/ox/test_crash_and_concurrency.py
tests/ox/test_archive_absence.py
```

Old V1/V2 test files may be deleted when they exercise only archived execution behavior. Provider-neutral/NVIDIA/Wolfram tests remain untouched except for narrowly required regression assertions.

---

### Task 0: Execution Baseline, Archive Identities, and Isolated Worktree

**Files:**
- Create during implementation: `archive/OX-ARCHIVE.md`
- No production changes in this task.

**Interfaces:**
- Consumes: approved spec commit `b43a3700da83459135624a82d62efcd7d7dd12b4` and this plan.
- Produces: exact implementation baseline SHA, isolated worktree/branch, exact V1/V2 archival refs/identities, provider-call count statement `0`.

- [ ] **Step 1: Re-verify the converged implementation base before branching**

Run in the canonical Byte-MCP repository:

```powershell
git fetch --all --prune
git status --short
git rev-parse HEAD
git log -5 --oneline
```

Require a clean canonical worktree. Compare the current candidate lineage with the known NVIDIA-capable integration point `fb87e39d24ee2e74f648da0495059f147f30fb89` and any newer runtime-qualified commits. Do not choose stale `main` merely because it is the default branch.

- [ ] **Step 2: Create an isolated implementation worktree using the approved worktree skill**

Use `superpowers:using-git-worktrees` and create a branch named:

```text
feat/ox-clean-room-rebuild
```

from the freshly verified converged base. Record the exact base SHA in the implementation journal/commit message notes.

- [ ] **Step 3: Establish immutable archival refs before deletion**

Create non-moving archival refs pointing at the exact final V1 and abandoned V2 identities already established by the project. Minimum required refs:

```text
archive/ox-v1-final
archive/ox-v2-abandoned
```

Before creating them, verify the target commits from repository history rather than guessing. The expected historical anchors include V1 final/quiesce lineage and V2 design/probe lineage, but the command must use observed SHAs.

- [ ] **Step 4: Write the archival record**

Create `archive/OX-ARCHIVE.md` containing:

```markdown
# OX Historical Archive

OX V1 and the abandoned OX V2 implementation are historical only.
They are not runtime compatibility targets for the clean-room rebuild.

## V1
- archive ref: `archive/ox-v1-final`
- exact commit: `<observed SHA>`
- final evidence inventory: `qualification/ox-v1/final-evidence.json` at the archived ref

## V2
- archive ref: `archive/ox-v2-abandoned`
- exact commit: `<observed SHA>`
- historical clean-room V2 spec/plan/probe remain available at that ref

The active clean-room rebuild intentionally migrates no V1/V2 runtime state or evidence.
```

Replace only the angle-bracket SHA fields with observed values before committing; the final file must contain no placeholders.

- [ ] **Step 5: Commit archival metadata only**

```powershell
git add archive/OX-ARCHIVE.md
git commit -m "docs: archive historical OX implementations"
```

Checkpoint reconciliation: spec §§4, 21. Provider requests: 0.

---

### Task 1: Remove V1/V2 Active Execution and Prove Neighboring Systems Survive

**Files:**
- Delete: pre-rebuild `src/byte_mcp/ox/**`
- Delete: pre-rebuild `src/byte_mcp/ox_v2/**`
- Delete: old OX execution tests that exist solely for V1/V2
- Modify: `src/byte_mcp/server.py`
- Create: `tests/ox/test_archive_absence.py`
- Rewrite/Create: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- Consumes: Task 0 archive refs.
- Produces: active tree with zero old OX execution imports/tools while core, NVIDIA, and Wolfram remain available.

- [ ] **Step 1: Write RED absence/surface tests before deleting code**

Create `tests/ox/test_archive_absence.py` with assertions that the final active tree must not contain legacy runtime markers such as `ox_v2_lifetime_probe`, `ox_continue`, `ox_revalidate`, `OXProviderJobManager`, or imports from removed-generation modules. Use AST/text scans over `src/byte_mcp` excluding archive/docs.

Rewrite `tests/ox/test_mcp_surface.py` to assert that before the new tools are added there are no registered names beginning `ox_`, while the exact currently observed core/NVIDIA/Wolfram surface is preserved.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/ox/test_archive_absence.py tests/ox/test_mcp_surface.py -q
```

Expected: FAIL because old OX/V2 code or registration still exists on the baseline.

- [ ] **Step 3: Remove old active OX execution code/tests/registrations**

Delete the pre-rebuild `src/byte_mcp/ox/` and `src/byte_mcp/ox_v2/` trees and old execution-specific tests. Remove only OX registrations/imports from `server.py`; do not rewrite NVIDIA or Wolfram implementations.

- [ ] **Step 4: Run the absence and neighboring regression gate**

```powershell
python -m pytest tests/ox/test_archive_absence.py tests/ox/test_mcp_surface.py -q
python -m pytest tests/nvidia tests/wolfram -q
python -m ruff check src/byte_mcp/server.py tests/ox
```

Require PASS and zero provider calls.

- [ ] **Step 5: Commit the clean active-tree boundary**

```powershell
git add -A
git commit -m "chore: remove archived OX execution code"
```

Checkpoint reconciliation: spec §§4, 8, 21. Confirm no new OX production package has been introduced yet.

---

### Task 2: New OX Models and Settings Contract

**Files:**
- Create: `src/byte_mcp/ox/__init__.py`
- Create: `src/byte_mcp/ox/models.py`
- Create: `src/byte_mcp/ox/settings.py`
- Create: `tests/ox/test_models.py`

**Interfaces:**
- Produces:

```python
class OXReviewMode(StrEnum):
    FULL_REPOSITORY = "FULL_REPOSITORY"
    BOUNDED = "BOUNDED"

class OXReviewState(StrEnum):
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"

@dataclass(frozen=True, slots=True)
class OXReviewScope:
    repository: str
    mode: OXReviewMode
    paths: tuple[str, ...]
    objective: str

@dataclass(frozen=True, slots=True)
class OXArtifact:
    logical_path: str
    content: bytes
    byte_length: int
    content_sha256: str
    classification: str
    git_state: str | None

@dataclass(frozen=True, slots=True)
class OXSnapshot:
    repository: str
    mode: OXReviewMode
    requested_paths: tuple[str, ...]
    policy_version: str
    artifacts: tuple[OXArtifact, ...]
    total_content_bytes: int
    snapshot_sha256: str

@dataclass(frozen=True, slots=True, repr=False)
class OXPreparedReview:
    review_id: str
    scope: OXReviewScope
    snapshot: OXSnapshot
    packet_bytes: bytes
    packet_sha256: str
    prepared_request: PreparedProviderRequest
```

- [ ] **Step 1: Write RED model/settings tests**

Cover immutability, safe repr (no artifact/request bytes), review mode/state closed vocabularies, review objective non-empty/bounded, relative path normalization, and provider profile constants.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/ox/test_models.py -q
```

Expected: import failure because new package does not exist.

- [ ] **Step 3: Implement minimal models and settings**

In `settings.py` define exactly:

```python
OX_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
OX_MODEL_ID = "zai/glm-5.3-flash"
OX_MAX_ARTIFACT_BYTES = 1_000_000
OX_MAX_ARTIFACTS = 5_000
OX_MAX_SNAPSHOT_CONTENT_BYTES = 3_250_000
OX_MAX_PACKET_BYTES = 3_500_000
OX_SNAPSHOT_POLICY_VERSION = "ox-snapshot-v1"
OX_PACKET_POLICY_VERSION = "ox-packet-v1"
OX_TIMEOUT_POLICY = ProviderTimeoutPolicy(
    connect_seconds=10.0,
    write_seconds=30.0,
    read_seconds=600.0,
    pool_seconds=10.0,
    absolute_deadline_seconds=600.0,
)
```

Add `OXSettings.load()` that reads `AI_GATEWAY_API_KEY` only when called, resolves evidence root from `BYTE_MCP_OX_EVIDENCE_DIR` or `%LOCALAPPDATA%/Byte-MCP/ox`, and never logs/reprs the key.

- [ ] **Step 4: GREEN + Ruff**

```powershell
python -m pytest tests/ox/test_models.py -q
python -m ruff check src/byte_mcp/ox tests/ox/test_models.py
python -m ruff format --check src/byte_mcp/ox tests/ox/test_models.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/byte_mcp/ox tests/ox/test_models.py
git commit -m "feat: define clean-room OX contracts"
```

Checkpoint reconciliation: spec §§5, 7, 8, 16.

---

### Task 3: Repository Authority and Review Scope Resolution

**Files:**
- Create: `src/byte_mcp/ox/scope.py`
- Create: `tests/ox/test_scope.py`
- Create: `config/ox-repositories.example.json`

**Interfaces:**
- Consumes: `Settings`, `load_roots`, `OXReviewMode`, `OXReviewScope`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class OXResolvedRepository:
    alias: str
    path: Path

class OXScopeResolver:
    def __init__(self, projects_root: Path) -> None: ...
    def resolve_repository(self, repository: str) -> OXResolvedRepository: ...
    def resolve_scope(
        self,
        repository: str,
        mode: OXReviewMode,
        paths: Sequence[str],
        objective: str,
    ) -> tuple[OXResolvedRepository, OXReviewScope]: ...
```

- [ ] **Step 1: Write RED authority/scope tests**

Create temporary `/AiProjects`-like root fixtures. Prove repository name traversal (`..`, slash, backslash, absolute path, drive prefix, controls) is rejected; repository must be an immediate/contained directory beneath projects root; bounded paths must be normalized repository-relative POSIX paths; `FULL_REPOSITORY` requires no paths; `BOUNDED` requires at least one path; every selected path must remain under the repository.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/ox/test_scope.py -q
```

- [ ] **Step 3: Implement deterministic scope resolution**

Use `Path.resolve(strict=True)` on candidate repository/scope paths and `Path.is_relative_to(projects_root)`/repository root checks. Do not accept arbitrary configured external roots. The runtime will pass only the root alias `projects`; fail if it is absent.

- [ ] **Step 4: Add example config documentation only**

`config/ox-repositories.example.json` should show human-friendly aliases if desired, but aliases must still resolve to direct/contained repositories under the `projects` root; no arbitrary absolute paths.

- [ ] **Step 5: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_scope.py -q
python -m ruff check src/byte_mcp/ox/scope.py tests/ox/test_scope.py
python -m ruff format --check src/byte_mcp/ox/scope.py tests/ox/test_scope.py
git add src/byte_mcp/ox/scope.py tests/ox/test_scope.py config/ox-repositories.example.json
git commit -m "feat: bound OX reviews to projects root"
```

Checkpoint reconciliation: spec §6.

---

### Task 4: Frozen Current-Filesystem Snapshot Engine

**Files:**
- Create: `src/byte_mcp/ox/snapshot.py`
- Create: `tests/ox/test_snapshot.py`

**Interfaces:**
- Consumes: `OXResolvedRepository`, `OXReviewScope`, Task 2 bounds.
- Produces:

```python
def freeze_snapshot(
    repository: OXResolvedRepository,
    scope: OXReviewScope,
) -> OXSnapshot: ...
```

- [ ] **Step 1: Write RED inclusion tests**

Prove committed/current text, staged/unstaged filesystem bytes, and eligible untracked files are included from disk. A test must modify a tracked file after creating Git baseline and assert the snapshot contains the modified bytes, not committed bytes.

- [ ] **Step 2: Write RED exclusion/boundary tests**

Cover `.env`, `.git`, `.venv`, `venv`, `node_modules`, `dist`, `build`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, coverage output, database/archive/binary/media extensions, private key material paths, `data/ox` or configured Byte-MCP evidence paths, file >1,000,000 bytes, symlink/junction path, and submodule directory behavior. Symlink/junction selected directly must fail closed; otherwise excluded entries are recorded in manifest metadata without content.

- [ ] **Step 3: Write RED deterministic identity/bounds tests**

Prove sorted logical paths, per-file SHA-256, total content count, 5,001-artifact failure, >3,250,000 aggregate content failure, one-byte change → new snapshot hash, add/delete path → new snapshot hash, and scope change → new snapshot hash.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/ox/test_snapshot.py -q
```

- [ ] **Step 5: Implement snapshot policy**

Use `os.scandir`/`Path` without following links. Text eligibility is deterministic: reject NUL-containing content and bytes that fail UTF-8 decode; do not use extension-only allowlisting. Preserve exact original bytes in `OXArtifact.content`. Compute snapshot hash from canonical JSON metadata containing repository alias, review mode, requested paths, policy version, and sorted artifact `{logical_path, byte_length, content_sha256, classification, git_state}` records; content bytes are represented by their hashes in the snapshot identity.

Use Git only for optional state labels; failure to obtain Git state must not change content authority.

- [ ] **Step 6: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_snapshot.py -q
python -m ruff check src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
python -m ruff format --check src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
git add src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
git commit -m "feat: freeze current OX repository snapshots"
```

Checkpoint reconciliation: spec §§6, 9, 12.

---

### Task 5: Deterministic Free-Form Review Packet and Prepared Request

**Files:**
- Create: `src/byte_mcp/ox/packet.py`
- Create: `tests/ox/test_packet.py`

**Interfaces:**
- Consumes: `OXReviewScope`, `OXSnapshot`, existing `prepare_provider_request`.
- Produces:

```python
def build_review_packet(scope: OXReviewScope, snapshot: OXSnapshot) -> bytes: ...

def prepare_ox_request(packet_bytes: bytes) -> PreparedProviderRequest: ...
```

- [ ] **Step 1: Write RED packet determinism/content tests**

Assert identical frozen snapshot → byte-identical packet; objective/scope/snapshot SHA are present; every artifact appears once in sorted order; only logical relative paths appear; absolute temp/root paths do not appear; exact frozen content is embedded; no JSON findings/schema instruction exists.

- [ ] **Step 2: Write RED oversize/provider identity tests**

Packet >3,500,000 bytes must fail before provider preparation. Prepared request must use exactly:

```python
{
    "model": "zai/glm-5.3-flash",
    "stream": False,
    "max_tokens": 65536,
    "reasoning": {"effort": "medium"},
    "providerOptions": {"gateway": {"only": ["zai"]}},
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": packet_text},
    ],
}
```

where `SYSTEM_PROMPT` requires independent adversarial code review, review only supplied frozen evidence, identify correctness/security/reliability/regression/architecture/edge-case/testing concerns, and respond naturally as a technical reviewer. No structured-output instruction.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest tests/ox/test_packet.py -q
```

- [ ] **Step 4: Implement packet/request construction**

Require packet UTF-8 because snapshot text eligibility already guarantees UTF-8 artifacts. Call shared `prepare_provider_request(provider_id="ox", method="POST", target_origin="https://ai-gateway.vercel.sh", endpoint_path="/v1/chat/completions", model_id="zai/glm-5.3-flash", body=...)`. Never call `json=` later; the prepared exact bytes are authority.

- [ ] **Step 5: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_packet.py -q
python -m ruff check src/byte_mcp/ox/packet.py tests/ox/test_packet.py
python -m ruff format --check src/byte_mcp/ox/packet.py tests/ox/test_packet.py
git add src/byte_mcp/ox/packet.py tests/ox/test_packet.py
git commit -m "feat: build deterministic free-form OX packets"
```

Checkpoint reconciliation: spec §§11, 12, 16.

---

### Task 6: Durable Per-Review Evidence and Irreversible Send Claim

**Files:**
- Create: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_evidence.py`

**Interfaces:**
- Consumes: `OXPreparedReview`, provider outcomes/observations.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class OXReviewEvidence:
    review_id: str
    state: OXReviewState
    snapshot_sha256: str
    request_sha256: str
    provider_started_at: str | None
    provider_finished_at: str | None
    attempt_outcome: str | None
    response_bytes: int | None
    review_text: str | None

class OXEvidencestore:
    def allocate_review_id(self) -> str: ...
    def persist_prepared(self, prepared: OXPreparedReview) -> None: ...
    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool: ...
    def persist_response(self, review_id: str, body: bytes) -> None: ...
    def persist_review_text(self, review_id: str, text: str) -> None: ...
    def finalize(self, review_id: str, terminal_metadata: Mapping[str, object]) -> None: ...
    def get(self, review_id: str) -> OXReviewEvidence: ...
```

Use class name exactly `OXEvidenceStore` (capital `S`) in implementation; the signature above's spelling is corrected here.

- [ ] **Step 1: Write RED evidence-layout/atomicity tests**

For review `OX-000001`, require directory files:

```text
review.json
snapshot.json
packet.bin
request.bin
```

before send; `send.claim` appears atomically on first claim; `response.bin` appears only after full response persistence; `review.txt` only after successful free-form extraction; terminal metadata is stored in `review.json` via temp-file + `os.replace`.

- [ ] **Step 2: Write RED replay/crash tests**

First `claim_send(...)` returns `True`; second returns `False`; restarting a new `OXEvidenceStore` instance sees `send.claim` and cannot reclaim. A claim file is never deleted by finalize/failure paths. A review with claim but no terminal metadata projects `OUTCOME_UNKNOWN`.

- [ ] **Step 3: Write RED privacy tests**

`get()` must not return packet/request/raw-response bytes or absolute evidence paths. Safe `repr` must not contain packet/request/review content.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/ox/test_evidence.py -q
```

- [ ] **Step 5: Implement filesystem evidence store**

Allocate IDs under an evidence-root lock by scanning existing `OX-\d{6}` directories and atomically creating the next directory with `mkdir(exist_ok=False)`. Create `send.claim` with `os.open(..., O_CREAT | O_EXCL | O_WRONLY)` and canonical JSON containing review ID, request SHA, and claimed timestamp. Never remove `send.claim`.

Persist immutable artifacts with exclusive-create semantics; if an expected immutable file already exists with different bytes, fail closed. `review.json` is the only replaceable projection and must be written atomically.

- [ ] **Step 6: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_evidence.py -q
python -m ruff check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
python -m ruff format --check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git add src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git commit -m "feat: persist immutable OX review evidence"
```

Checkpoint reconciliation: spec §§13, 15, 17.

---

### Task 7: Pre-Claim Secret Scan and Exact Credential Exclusion

**Files:**
- Create: `tests/ox/test_security.py`
- Modify: `src/byte_mcp/ox/packet.py`
- Modify: `src/byte_mcp/ox/service.py` only after Task 9 creates it; until then implement a helper in `packet.py` exported as below.

**Interfaces:**
- Produces:

```python
def validate_packet_safety(packet_bytes: bytes, *, exact_credential: str | None) -> None: ...
```

- [ ] **Step 1: Write RED secret-safety tests**

Require local failure for packet containing PEM private-key markers (`-----BEGIN ... PRIVATE KEY-----`), exact configured API credential bytes, and configured strong secret sentinels. Near-match credential must not trigger the exact-credential gate. Error messages must be closed/safe and never echo the secret.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/ox/test_security.py -q
```

- [ ] **Step 3: Implement bounded safety validation**

Scan only already-frozen packet bytes. Exact credential comparison uses `exact_credential.encode("utf-8")` and fails if present. Private-key markers are fixed byte tokens. Do not add heuristic entropy scanners or arbitrary regex credential guessing in V1 of this rebuild.

- [ ] **Step 4: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_security.py -q
python -m ruff check src/byte_mcp/ox/packet.py tests/ox/test_security.py
python -m ruff format --check src/byte_mcp/ox/packet.py tests/ox/test_security.py
git add src/byte_mcp/ox/packet.py tests/ox/test_security.py
git commit -m "feat: fail closed on unsafe OX packets"
```

Checkpoint reconciliation: spec §10.

---

### Task 8: One-Shot OX Provider Client with Free-Form Response Extraction

**Files:**
- Create: `src/byte_mcp/ox/client.py`
- Create: `tests/ox/test_client.py`

**Interfaces:**
- Consumes: `PreparedProviderRequest`, `ProviderAuthorization`, `ProviderTransmissionContext`, `ProviderTimeoutPolicy`, `execute_once`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class OXProviderResult:
    review_text: str
    raw_response: bytes = field(repr=False)
    request_sha256: str
    transport_observation: ProviderTransportObservation

async def execute_ox_review(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OXProviderResult: ...
```

- [ ] **Step 1: Write RED one-request/exact-body tests**

With `httpx.MockTransport`, assert one handler invocation, exact `prepared_request.body_bytes`, endpoint exactly Vercel gateway, no redirects/fallback, and request hash identity preserved.

- [ ] **Step 2: Write RED free-form envelope tests**

For complete 2xx JSON require one `choices[0].message` with role `assistant` and non-empty string `content`; accept arbitrary prose/Markdown and phrases such as `PASS`, bullet lists, headings, or “no material issues.” Reject empty/whitespace-only content, malformed JSON, missing/multiple choices, wrong role/content type as local protocol failure after transport completion. Do not parse findings.

- [ ] **Step 3: Write RED transport mapping tests**

Use shared provider-neutral failure mappings. Verify connect failures remain definite `NOT_SENT`; write/read/deadline/remote protocol remain `OUTCOME_UNKNOWN`; complete 3xx/4xx/5xx are `REJECTED`; exactly one transport execution occurs for all contacted paths.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/ox/test_client.py -q
```

- [ ] **Step 5: Implement minimal client**

Create `ProviderAuthorization(f"Bearer {api_key}")` and call shared `execute_once` exactly once with `OX_TIMEOUT_POLICY`. Do not catch and retry. On successful complete transport response, preserve `response.body` exactly in `OXProviderResult.raw_response`, then decode JSON from those bytes and extract free-form assistant content.

- [ ] **Step 6: GREEN + provider regression**

```powershell
python -m pytest tests/ox/test_client.py tests/providers tests/nvidia -q
python -m ruff check src/byte_mcp/ox/client.py tests/ox/test_client.py
python -m ruff format --check src/byte_mcp/ox/client.py tests/ox/test_client.py
```

- [ ] **Step 7: Commit**

```powershell
git add src/byte_mcp/ox/client.py tests/ox/test_client.py
git commit -m "feat: execute one free-form OX provider review"
```

Checkpoint reconciliation: spec §§8, 14, 16. Provider calls: 0 real; mock/loopback only.

---

### Task 9: Synchronous OX Review Service Lifecycle

**Files:**
- Create: `src/byte_mcp/ox/service.py`
- Create: `tests/ox/test_service.py`
- Modify: `tests/ox/test_security.py`

**Interfaces:**
- Consumes all prior tasks.
- Produces:

```python
class OXReviewService:
    def __init__(
        self,
        scope_resolver: OXScopeResolver,
        evidence_store: OXEvidencestore,
        settings_loader: Callable[[], OXSettings] = OXSettings.load,
    ) -> None: ...

    async def review(
        self,
        *,
        repository: str,
        mode: str,
        paths: Sequence[str] | None,
        objective: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> dict[str, object]: ...

    def get_review(self, review_id: str) -> dict[str, object]: ...
```

Implementation must use the corrected type `OXEvidenceStore` in annotations; do not introduce `OXEvidencestore` as a second name.

- [ ] **Step 1: Write RED happy-path lifecycle test**

With temp projects root/evidence root and MockTransport, call `review()` once and assert order/effects: scope validated → snapshot frozen → packet/request persisted → credential safety validated → send claimed → one provider request → exact `response.bin` persisted → `review.txt` persisted → terminal `COMPLETED` metadata → returned free-form review text.

- [ ] **Step 2: Write RED pre-network failure tests**

Invalid scope, oversize snapshot/packet, missing API key, packet secret, exact credential collision, prepared-request integrity mismatch, and prepared evidence write failure must produce zero transport handler calls and no `send.claim` unless the failure occurs after claim by design.

- [ ] **Step 3: Write RED post-claim failure tests**

Connect `NOT_SENT` after claim finalizes `FAILED` with send claim consumed. Complete provider rejection finalizes `FAILED`. Write/read/deadline/ambiguous transport finalizes `OUTCOME_UNKNOWN`. Protocol/empty assistant response after complete transport persists `response.bin` and finalizes `FAILED`. Any failure persisting raw response after network completion must never report `COMPLETED` and must keep claim consumed.

- [ ] **Step 4: Write RED retrieval test**

`get_review()` returns only review ID/state/repository/mode/snapshot SHA/request SHA/provider/model/timestamps/outcome/safe counts/free-form review text when complete. It performs no network call and omits absolute paths/raw packet/raw request/raw provider envelope.

- [ ] **Step 5: Run RED**

```powershell
python -m pytest tests/ox/test_service.py tests/ox/test_security.py -q
```

- [ ] **Step 6: Implement synchronous lifecycle**

Generate/allocate review ID before networking. Build `OXPreparedReview` and `persist_prepared`. Load API key only after preparation; run packet safety scan before `claim_send`. Call `claim_send` exactly once. If claim returns false, return/project existing evidence and never invoke transport. Build `ProviderTransmissionContext` with exact request SHA and observed UTC timestamp only after successful claim. Persist raw response before `review.txt` and finalization.

- [ ] **Step 7: GREEN + Ruff + commit**

```powershell
python -m pytest tests/ox/test_service.py tests/ox/test_security.py -q
python -m ruff check src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
python -m ruff format --check src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
git add src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
git commit -m "feat: add synchronous OX review lifecycle"
```

Checkpoint reconciliation: spec §§5, 10, 13–17.

---

### Task 10: Crash, Concurrency, Replay, and Evidence Ordering Qualification

**Files:**
- Create: `tests/ox/test_crash_and_concurrency.py`
- Modify production only when a RED test exposes a contract defect.

**Interfaces:**
- Verifies `OXEvidenceStore` and `OXReviewService`; adds no new product capability.

- [ ] **Step 1: Write duplicate concurrent claim test**

Use two threads/processes against the same review evidence directory and barrier-synchronize `claim_send`. Require exactly one `True`, one `False`, one immutable `send.claim`, and at most one fake transport invocation when exercised through service-level duplicate execution.

- [ ] **Step 2: Write forced-boundary crash tests**

Simulate/reopen after:

```text
prepared evidence before claim
claim before transport
transport complete before response persistence
response persistence before review.txt
review.txt before terminal finalization
terminal finalization before MCP return
```

Expected durable projection:

```text
before claim                         READY
claim with no terminal               OUTCOME_UNKNOWN
claim + response, no terminal        OUTCOME_UNKNOWN
claim + review.txt, no terminal      OUTCOME_UNKNOWN
terminal completed                   COMPLETED
```

No restart path may delete claim or invoke provider networking.

- [ ] **Step 3: Write evidence-ordering assertions**

A `COMPLETED` terminal state is impossible unless `response.bin` and non-empty `review.txt` both exist and hash/count metadata matches. Corruption/mismatch causes safe local failure/unknown projection; never fabricate completion.

- [ ] **Step 4: Run focused crash suite**

```powershell
python -m pytest tests/ox/test_crash_and_concurrency.py -q
```

- [ ] **Step 5: Fix only RED-proven contract defects, then rerun**

```powershell
python -m pytest tests/ox/test_crash_and_concurrency.py tests/ox/test_evidence.py tests/ox/test_service.py -q
python -m ruff check src/byte_mcp/ox tests/ox/test_crash_and_concurrency.py
```

- [ ] **Step 6: Commit qualification**

```powershell
git add src/byte_mcp/ox tests/ox/test_crash_and_concurrency.py
git commit -m "test: qualify OX crash and replay boundaries"
```

Checkpoint reconciliation: spec §§14, 15, 17.

---

### Task 11: Lazy Runtime and Exact Two-Tool MCP Surface

**Files:**
- Create: `src/byte_mcp/ox/runtime.py`
- Modify: `src/byte_mcp/server.py`
- Rewrite/Create: `tests/ox/test_mcp_surface.py`
- Modify: server/runtime tests as required by observed baseline paths.

**Interfaces:**
- Produces exactly:

```python
@mcp.tool(...)
async def ox_review(
    repository: str,
    mode: str,
    objective: str,
    paths: list[str] | None = None,
) -> dict[str, object]: ...

@mcp.tool(annotations=READ_ONLY)
def ox_get_review(review_id: str) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED runtime isolation/surface tests**

Assert core server import/startup succeeds when OX configuration is unavailable. `ox_review` and `ox_get_review` are registered exactly once; no other `ox_` tool exists. Preserve exact observed NVIDIA and Wolfram tool names. `ox_get_review` must be read-only/openWorld false; `ox_review` external/openWorld true and non-idempotent.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/ox/test_mcp_surface.py -q
```

- [ ] **Step 3: Implement lazy runtime**

`OXRuntime.load(repo_root, roots)` obtains only the existing `projects` root from `load_roots(Settings)` and initializes `OXScopeResolver` + `OXEvidenceStore`; configuration errors are contained in runtime state and do not block core/NVIDIA/Wolfram startup. Do not load provider credential at startup.

- [ ] **Step 4: Register exactly two tools in `server.py`**

Use lazy `import_module("byte_mcp.ox.runtime")` if necessary to preserve startup isolation. `ox_review` delegates one synchronous lifecycle invocation; `ox_get_review` only reads evidence.

- [ ] **Step 5: GREEN + full surface regression**

```powershell
python -m pytest tests/ox/test_mcp_surface.py tests/nvidia tests/wolfram -q
python -m ruff check src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
python -m ruff format --check src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
git commit -m "feat: expose clean-room OX review tools"
```

Checkpoint reconciliation: spec §§5, 7, 18.

---

### Task 12: Full Security and Isolation Qualification

**Files:**
- Modify: `tests/ox/test_security.py`
- Modify: `tests/ox/test_archive_absence.py`
- Production only if a RED test proves a defect.

**Interfaces:**
- Adds no capabilities; qualifies boundaries.

- [ ] **Step 1: Add privacy sentinel matrix**

Seed sentinels in API key, absolute repository path, HTTP exception message, proxy environment, raw response envelope, packet content, and excluded secret file. Inspect MCP/public result, logs/captured logging records, `review.json`, and safe exception text. Only intended restricted files (`packet.bin`, `request.bin`, `response.bin`, snapshot artifact storage if used) may contain provider-bound/repository content. API key and raw exception/proxy values must never persist.

- [ ] **Step 2: Add import isolation test**

AST-scan `src/byte_mcp/ox/*.py`; reject imports beginning `byte_mcp.nvidia` or `byte_mcp.wolfram`. AST-scan NVIDIA package and reject `byte_mcp.ox` imports.

- [ ] **Step 3: Add network-block test**

Monkeypatch/socket-guard non-loopback networking for all OX tests and prove `ox_get_review`, snapshotting, packet preparation, failures before claim, and runtime initialization never attempt networking.

- [ ] **Step 4: Run security/isolation suite**

```powershell
python -m pytest tests/ox/test_security.py tests/ox/test_archive_absence.py -q
```

- [ ] **Step 5: Fix only RED-proven defects and rerun all OX tests**

```powershell
python -m pytest tests/ox -q
python -m ruff check src/byte_mcp/ox tests/ox
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/ox tests/ox
git commit -m "test: harden OX security boundaries"
```

Checkpoint reconciliation: spec §§6, 8–10, 18.

---

### Task 13: Operator Documentation and Failure Map

**Files:**
- Create: `docs/OX.md`
- Modify/Create: `docs/FAILURE_MAP.md`
- Modify: `README.md`
- Modify: `archive/OX-ARCHIVE.md` only if final observed archive identities need clarification.

**Interfaces:**
- Adds no runtime capability.

- [ ] **Step 1: Write current OX operator contract**

`docs/OX.md` must document:

```text
purpose: independent adversarial code review only
public tools: ox_review / ox_get_review
projects-root authority
FULL_REPOSITORY and BOUNDED modes
current-filesystem snapshot semantics
hard exclusions
one authorization = one lifecycle = max one provider request
no automatic retry
free-form output
local evidence file layout
FAILED vs OUTCOME_UNKNOWN
oversize behavior
no V1/V2 compatibility
separate runtime-promotion/live-call approvals
```

Include a local forensic procedure for inspecting `response.bin`, `request.bin`, and snapshot metadata without widening the MCP GET surface.

- [ ] **Step 2: Add OX failure boundaries to `docs/FAILURE_MAP.md`**

Document for each major boundary: observable symptom, likely cause, first diagnostics, propagation, safe recovery, data risk, “do not” warnings, and related tests. Include scope escape, exclusion/secret failure, oversize packet, claim conflict, connect failure, write/read/deadline ambiguity, provider rejection, malformed/empty response, response persistence failure, crash after claim, evidence corruption, and runtime config isolation.

- [ ] **Step 3: Update README current surface**

Link `docs/OX.md` and archive note. Do not describe V1/V2 execution as available.

- [ ] **Step 4: Documentation self-check and commit**

Search current docs for obsolete instructions that could be mistaken for active OX execution guidance. Historical files may remain only where clearly archival; remove/move active pointers that conflict with the new contract.

```powershell
git add docs/OX.md docs/FAILURE_MAP.md README.md archive/OX-ARCHIVE.md
git commit -m "docs: document clean-room OX operation"
```

Checkpoint reconciliation: spec §§4, 19.

---

### Task 14: Full Provider-Free Local Qualification and Plan Reconciliation

**Files:**
- No production changes unless a failing gate reveals a defect; any fix returns through RED/GREEN and gets its own commit.

**Interfaces:**
- Produces: exact locally qualified candidate SHA and evidence summary.

- [ ] **Step 1: Run dependency/compile/lint/format gates**

```powershell
python -m pip check
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m ruff check .
```

Determine the exact changed Python file set from Git and run:

```powershell
python -m ruff format --check <exact changed Python files>
```

Do not hide historical unrelated format failures by formatting untouched files.

- [ ] **Step 2: Run full tests**

```powershell
python -m pytest tests/ox -q
python -m pytest tests/providers tests/nvidia tests/wolfram -q
python -m pytest
```

Require all PASS.

- [ ] **Step 3: Run launcher/runtime checks**

```powershell
pwsh -NoLogo -NoProfile -File .\scripts\Check-Launcher.ps1
```

Require PASS. No live runtime mutation occurs in this task.

- [ ] **Step 4: Verify exact active MCP surface statically/in tests**

Require core Byte-MCP + observed NVIDIA + Wolfram + exactly `ox_review` and `ox_get_review`; no V1/V2/lifetime/retry/continuation/revalidation OX tool.

- [ ] **Step 5: Run frozen-neighbor diff check**

Compare NVIDIA/Wolfram production paths against the implementation base. Any intentional provider-neutral change must be separately listed with tests proving existing NVIDIA behavior. There must be no direct NVIDIA/Wolfram production edits made merely to accommodate OX.

- [ ] **Step 6: Reconcile implementation against the approved spec and this plan**

Write a local/checkpoint report answering exactly:

```text
What did the plan require?
What now exists?
What tests prove it?
Did we introduce anything not authorized?
Did any assumption change?
What remains?
```

Then explicitly check:

```text
V1/V2 active execution absent
exact two-tool OX surface
projects-root only
bounded + full modes
current dirty/untracked state included
snapshot immutable
secret/oversize fail closed before network
one provider request maximum
no automatic retry
free-form response only
raw response persisted before review extraction
file evidence model only
restart never restores send authority
NVIDIA/Wolfram/core regressions PASS
FAILURE_MAP complete
provider calls during qualification = 0
```

- [ ] **Step 7: Verify clean candidate identity**

```powershell
git status --short
git rev-parse HEAD
git log -10 --oneline
```

Require clean worktree. Record exact candidate SHA. If plan/checklist documentation was committed during qualification, rerun all affected verification before claiming the new HEAD qualified.

- [ ] **Step 8: STOP before runtime promotion**

Present exact candidate SHA, full provider-free gate results, archive identities, tool surface, and statement:

```text
OX_PROVIDER_CALLS=0
NVIDIA_PROVIDER_CALLS=0
WOLFRAM_PROVIDER_CALLS=0
RUNTIME_MUTATIONS=0
```

Do not promote automatically.

Checkpoint reconciliation: spec §§19–21.

---

### Task 15: Separately Authorized Provider-Free Runtime Promotion

**Files:**
- No planned production changes. Defects found during promotion return to implementation with RED/GREEN before another candidate is proposed.

**Interfaces:**
- Consumes: exact Task 14 qualified candidate and fresh explicit runtime-promotion authorization.
- Produces: deployed provider-disabled/unused OX tool surface with zero provider requests.

- [ ] **Step 1: Obtain explicit authorization naming the exact candidate SHA**

No authorization from design or implementation planning counts for runtime mutation.

- [ ] **Step 2: Fresh preflight live runtime identity**

Verify current runtime HEAD, detached/clean state, supervisor/launcher status, existing NVIDIA/Wolfram/core surface, ports/tunnel health, and exact candidate delta. STOP on unexpected drift.

- [ ] **Step 3: Promote transactionally using established Byte-MCP runtime procedure**

Stop/start through the tracked operational scripts, deploy exact detached candidate, and wait until runtime classification is READY/active with server/tunnel health true. Do not make OX/NVIDIA/Wolfram provider requests during this operation.

- [ ] **Step 4: Provider-free live surface checks**

Verify exactly `ox_review` and `ox_get_review` appear alongside unchanged core/NVIDIA/Wolfram tools. Exercise only provider-free/local behavior such as invalid scope or local GET of non-existent review; do not invoke a valid `ox_review` that would reach provider transmission.

- [ ] **Step 5: Stability window**

Cross at least one established supervisor cadence and verify server/tunnel identities remain stable and no automatic repair/restart/provider activity occurred.

- [ ] **Step 6: STOP before first real OX review**

Report runtime evidence and require a fresh explicit user instruction for one real OX review.

---

### Task 16: First Real OX Canary — Separate Authorization Boundary

**Files:**
- No planned code changes.

**Interfaces:**
- Consumes: deployed exact qualified candidate and one explicit user authorization such as “Run an OX review of this bounded scope.”
- Produces: at most one real Vercel AI Gateway → Z.AI request and durable OX review evidence.

- [ ] **Step 1: Resolve the authorized review scope exactly as requested**

Do not infer a broader repository scope than the user authorized.

- [ ] **Step 2: Execute exactly one `ox_review` lifecycle**

The single authorization covers snapshot → packet → local evidence → claim → at most one provider request → response persistence → free-form review return. No second approval prompt.

- [ ] **Step 3: On success, read back evidence locally**

Use `ox_get_review(review_id)` and local evidence inspection to verify request identity, response evidence, final free-form review, and one-request maximum.

- [ ] **Step 4: On definite or ambiguous failure, STOP**

No automatic retry. `OUTCOME_UNKNOWN` remains consumed. Another paid review requires fresh user authorization and a new review identity.

- [ ] **Step 5: Close acceptance**

If canary behavior matches the approved contract, record the accepted runtime/canary identity in current OX operator documentation or a dedicated qualification receipt through a separately reviewed documentation-only commit. Do not reopen V1/V2 compatibility.

---

## Plan Self-Review

### Spec coverage

- Archive/remove V1/V2: Tasks 0–1, 13–14.
- Two-tool surface and whole-lifecycle approval: Tasks 9, 11, 15–16.
- No retry/background/continuation/revalidation: Global Constraints, Tasks 8–10, 14, 16.
- `/AiProjects`/projects-root authority: Task 3.
- Full + bounded scope and current dirty/untracked files: Tasks 3–4.
- Snapshot immutability/hash identity: Task 4.
- Exclusions/symlink/submodule/security: Tasks 4, 7, 12.
- Single frozen packet/free-form provider response: Tasks 5, 8.
- Oversize fail-closed/no truncation: Tasks 4–5, 9.
- Per-review filesystem evidence/no SQLite: Task 6.
- Irreversible send authority and crash semantics: Tasks 6, 9–10.
- Raw response persistence before interpretation/final completion: Tasks 8–10.
- Read-only retrieval: Tasks 9, 11–12.
- NVIDIA/Wolfram/provider-neutral isolation: Tasks 1, 8, 11–12, 14.
- Failure map/docs: Task 13.
- Provider-free full qualification: Task 14.
- Separate runtime promotion and live-call authorization: Tasks 15–16.

### Placeholder scan

The implementation plan contains no implementation-time `TBD`/`TODO` requirements. Task 0's archival example uses angle-bracket notation only as an explicit instruction to substitute freshly observed immutable SHAs before committing; the committed archival file is forbidden from retaining placeholders.

### Type consistency

Canonical names used by later tasks are:

```text
OXReviewMode
OXReviewState
OXReviewScope
OXResolvedRepository
OXArtifact
OXSnapshot
OXPreparedReview
OXSettings
OXScopeResolver
OXEvidenceStore
OXProviderResult
OXReviewService
```

`OXEvidenceStore` is the only valid evidence-store class name. Any lowercase-`s` spelling shown in explanatory snippets is explicitly corrected and must not be implemented.

### Scope check

This plan is intentionally one implementation campaign because every task contributes to one independently testable OX subsystem and the user explicitly requested end-to-end execution with routine plan reconciliation. Runtime promotion and the paid canary remain separate authorization boundaries rather than implementation subprojects.
