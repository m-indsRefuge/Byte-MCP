# OX Clean-Room Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully archive and remove OX V1/V2, then build a new synchronous two-tool OX adversarial code-review subsystem that snapshots current repository state under Byte-MCP authority, sends at most one Vercel AI Gateway → Z.AI request per authorized review, persists exact provider evidence before interpreting it, and returns OX's free-form review.

**Architecture:** Build a new `byte_mcp.ox` package from scratch on the freshly verified converged Byte-MCP lineage. Reuse only provider-neutral request identity, authorization, outcome, and one-shot transport primitives under `byte_mcp.providers`; OX owns scope, snapshotting, packet construction, evidence, response interpretation, lifecycle, and MCP integration. V1/V2 remain historical Git evidence only and have no runtime compatibility path.

**Tech Stack:** Python `>=3.12,<3.14`, `mcp[cli]==1.28.1`, `httpx>=0.28.1,<1`, stdlib filesystem/hash/json/pathlib/os/tempfile primitives, existing `byte_mcp.providers`, pytest, Ruff, PowerShell launcher qualification.

**Spec:** `docs/superpowers/specs/2026-09-17-ox-clean-room-rebuild-design.md`

## Global Constraints

- Re-verify the implementation baseline immediately before execution. The design branch originated from `fb87e39d24ee2e74f648da0495059f147f30fb89`; do not assume that SHA is still the correct converged implementation base.
- Execute in an isolated worktree created with `superpowers:using-git-worktrees`; never implement on `design/ox-clean-room-rebuild`.
- Archive exact V1/V2 identities before deletion. Historical source/evidence/specs remain available through Git refs/history; migrate no legacy runtime state.
- New public OX MCP surface is exactly `ox_review(...)` and `ox_get_review(review_id)`.
- One explicit authorization for one `ox_review` invocation covers that review's complete lifecycle and permits at most one outbound provider request. There is no second approval gate.
- No automatic retry, reconnect, resume, continuation, revalidation, queue, worker, provider polling, startup recovery, or second POST under one review identity.
- OX is code-review-only. No general chat and no provider tool loop.
- Provider route remains `https://ai-gateway.vercel.sh/v1/chat/completions` → Z.AI, model `zai/glm-5.3-flash`, provider allow-list `zai`, `stream=false`, `reasoning.effort="medium"`, `max_tokens=65536`.
- OX may inspect only repositories contained beneath Byte-MCP's configured `projects` root (`/AiProjects`). Callers never provide arbitrary absolute paths.
- Support `FULL_REPOSITORY` and `BOUNDED`; bounded requests never silently widen.
- Filesystem bytes at snapshot time are authoritative, including eligible staged, unstaged, and untracked material.
- Never follow symlinks or junctions. Do not recursively ingest submodules/nested repositories.
- Hard-exclude secret/env/key material, `.git`, virtualenvs, dependencies, generated/build/cache/coverage output, databases, archives, binary/media assets, IDE/runtime caches, and Byte-MCP evidence stores.
- Packet/request construction uses frozen bytes only. Never reread the working tree after snapshot freeze.
- Oversize reviews fail locally: no truncation, summarization, file dropping, splitting, or provider call.
- Provider response is free-form prose; impose no findings/severity/decision JSON schema.
- Persist the exact complete provider response bytes before decoding the provider envelope or extracting assistant text.
- Durable evidence is one local filesystem directory per review. No SQLite.
- Once `send.claim` is created, it is never deleted or reset. Crash/ambiguity cannot restore send authority.
- `ox_get_review` is local/read-only and performs zero networking.
- OX must not import NVIDIA; NVIDIA must not import OX; OX must not invoke Wolfram.
- Protect NVIDIA, Wolfram, core Byte-MCP, shared provider primitives, launcher, and runtime behavior from regression.
- Implementation and qualification use only mocks/loopback. Live OX, NVIDIA, Wolfram, Vercel, Z.AI, or other provider calls are forbidden until separately authorized.
- Maintain `docs/FAILURE_MAP.md`; a major slice is incomplete until significant implemented failure surfaces are documented.
- Runtime promotion and the first real OX review remain separate explicit authorization boundaries.

## Frozen Initial Product Bounds

```text
OX_REVIEW_ID_PREFIX           = "OX-"
OX_SNAPSHOT_POLICY_VERSION    = "ox-snapshot-v1"
OX_PACKET_POLICY_VERSION      = "ox-packet-v1"
OX_MAX_ARTIFACT_BYTES         = 1_000_000
OX_MAX_ARTIFACTS              = 5_000
OX_MAX_SNAPSHOT_CONTENT_BYTES = 3_250_000
OX_MAX_PACKET_BYTES           = 3_500_000
shared prepared-request max   = 4_000_000 bytes
shared response max           = 8_000_000 decoded bytes
connect timeout               = 10 seconds
write timeout                 = 30 seconds
read timeout                  = 600 seconds
pool timeout                  = 10 seconds
absolute deadline             = 600 seconds
```

The packet bound leaves deterministic serialization headroom below the existing shared prepared-request maximum. Any serialized request that still exceeds the shared limit fails before send claim/networking.

## File Map

Production:

```text
src/byte_mcp/ox/__init__.py    clean-room package exports only
src/byte_mcp/ox/models.py      immutable OX records and closed states
src/byte_mcp/ox/settings.py    fixed provider profile, limits, evidence-root loading
src/byte_mcp/ox/scope.py       projects-root repository/scope authority
src/byte_mcp/ox/snapshot.py    current-filesystem freeze, exclusions, hashes
src/byte_mcp/ox/packet.py      deterministic packet/request and pre-send safety
src/byte_mcp/ox/evidence.py    durable per-review files and irreversible send claim
src/byte_mcp/ox/client.py      exactly-one transport plus pure response extractor
src/byte_mcp/ox/service.py     synchronous lifecycle and safe retrieval
src/byte_mcp/ox/runtime.py     lazy OX runtime isolation
src/byte_mcp/server.py         exactly two OX MCP registrations
```

Documentation/configuration:

```text
archive/OX-ARCHIVE.md
config/ox-repositories.example.json
docs/OX.md
docs/FAILURE_MAP.md
README.md
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
tests/ox/test_crash_and_concurrency.py
tests/ox/test_mcp_surface.py
tests/ox/test_security.py
tests/ox/test_archive_absence.py
```

## Slice Map

```text
Slice 1 — Tasks 0–1: archive/remove V1/V2 and protect neighbors
Slice 2 — Tasks 2–4: models/settings, scope, snapshot
Slice 3 — Tasks 5–7: packet, evidence, secret/request preflight
Slice 4 — Task 8: one-shot provider transport and pure response extraction
Slice 5 — Tasks 9–11: lifecycle, crash/concurrency, MCP runtime
Slice 6 — Task 12: security/privacy/isolation qualification
Slice 7 — Tasks 13–14: failure-aware docs and final provider-free candidate
Post-candidate boundaries — Tasks 15–16: promotion and first live canary
```

---

### Task 0: Verify Execution Baseline and Freeze Historical Identities

**Files:**
- Create: `archive/OX-ARCHIVE.md`
- Production: none.

**Interfaces:**
- Consumes the approved spec and this plan.
- Produces a freshly observed implementation-base SHA, isolated implementation worktree, archival refs, and provider-call count `0`.

- [ ] **Step 1: Re-verify the converged base**

Run in the canonical Byte-MCP checkout:

```powershell
git fetch --all --prune
git status --short
git rev-parse HEAD
git log -8 --oneline
git merge-base --is-ancestor fb87e39d24ee2e74f648da0495059f147f30fb89 HEAD
```

Expected: clean canonical worktree and exit code `0` for the ancestry check. If HEAD is not the currently runtime-qualified/converged lineage, inspect the known integration/runtime refs and select the observed converged commit; do not default to stale `main`. Record the selected SHA in the implementation checkpoint.

- [ ] **Step 2: Create the isolated implementation worktree**

Invoke `superpowers:using-git-worktrees`. Create branch `feat/ox-clean-room-rebuild` from the freshly selected SHA. No source edits occur on the design branch.

- [ ] **Step 3: Verify and create archival refs**

```powershell
git cat-file -e 6603a8a5f22c32483d81ff8d932adab4de7f099a^{commit}
git cat-file -e 94ff28810a06b7af2207196ac98c1152cc65b4b1^{commit}
git cat-file -e 09e67969197aee5883e9111eb94d116245d0bd53^{commit}
git cat-file -e cb4aebfa344d74279bff245773c68a1d5a57aea6^{commit}
git update-ref refs/archive/ox-v1-final 6603a8a5f22c32483d81ff8d932adab4de7f099a
git update-ref refs/archive/ox-v2-probe 09e67969197aee5883e9111eb94d116245d0bd53
git update-ref refs/archive/ox-v2-design cb4aebfa344d74279bff245773c68a1d5a57aea6
```

The historical V1 frozen baseline is `94ff28810a06b7af2207196ac98c1152cc65b4b1`; the quiesced/final active V1 identity is `6603a8a5f22c32483d81ff8d932adab4de7f099a`. V2 probe/design identities are preserved independently.

- [ ] **Step 4: Write the archival record**

Create `archive/OX-ARCHIVE.md` with those exact refs/SHAs, `qualification/ox-v1/final-evidence.json`, final V1 review `OX-000013`, V2 probe/design identities, and the frozen historical probe blob identities `59802c4a24fdc90a02c68a69e003462713ee3d7b` and `fe3dd4a0bbe5e0b0a09f2ad004337cf870edea18`. State that no legacy runtime/evidence migration is supported.

- [ ] **Step 5: Commit**

```powershell
git add archive/OX-ARCHIVE.md
git commit -m "docs: archive historical OX implementations"
```

Checkpoint: spec archive boundary satisfied; provider calls `0`.

---

### Task 1: Remove V1/V2 Active Execution and Protect Neighboring Systems

**Files:**
- Delete: pre-rebuild `src/byte_mcp/ox/**`
- Delete: pre-rebuild `src/byte_mcp/ox_v2/**`
- Delete/archive-only: execution tests that exist solely for V1/V2 behavior.
- Modify: `src/byte_mcp/server.py`
- Create: `tests/ox/test_archive_absence.py`
- Create: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- Produces an active tree with no legacy OX execution imports/tools while existing core, Wolfram, and NVIDIA tools remain unchanged.

- [ ] **Step 1: RED — legacy absence and current surface**

Write tests that AST/text-scan active production code for removed-generation markers (`byte_mcp.ox_v2`, `ox_v2_lifetime_probe`, `ox_continue`, `ox_revalidate`, `OXProviderJobManager`, background/recovery registrations) and fail while legacy source exists. Capture the current non-OX surface exactly as:

```python
{
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_review",
    "nvidia_get_review",
}
```

Run:

```powershell
python -m pytest tests/ox/test_archive_absence.py tests/ox/test_mcp_surface.py -q
```

Expected: FAIL on legacy active OX source/tests present on the execution baseline.

- [ ] **Step 2: GREEN — remove only legacy OX execution**

Delete V1/V2 runtime trees and execution-only tests/registrations. Preserve historical docs through Git/archive refs. Do not edit NVIDIA/Wolfram production code.

- [ ] **Step 3: Verify neighbors**

```powershell
python -m pytest tests/ox/test_archive_absence.py tests/ox/test_mcp_surface.py -q
python -m pytest tests/providers tests/nvidia tests/wolfram -q
python -m ruff check src/byte_mcp/server.py tests/ox
```

Expected: PASS, provider calls `0`.

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "chore: remove archived OX execution code"
```

Reconcile Slice 1 against the spec before continuing.

---

### Task 2: Define Clean-Room Models and Settings

**Files:**
- Create: `src/byte_mcp/ox/__init__.py`
- Create: `src/byte_mcp/ox/models.py`
- Create: `src/byte_mcp/ox/settings.py`
- Create: `tests/ox/test_models.py`

**Interfaces:**

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
class OXSnapshotExclusion:
    logical_path: str
    reason: str

@dataclass(frozen=True, slots=True, repr=False)
class OXArtifact:
    logical_path: str
    content: bytes = field(repr=False)
    byte_length: int
    content_sha256: str
    classification: str
    git_state: str | None

@dataclass(frozen=True, slots=True, repr=False)
class OXSnapshot:
    repository: str
    mode: OXReviewMode
    requested_paths: tuple[str, ...]
    policy_version: str
    artifacts: tuple[OXArtifact, ...]
    exclusions: tuple[OXSnapshotExclusion, ...]
    total_content_bytes: int
    snapshot_sha256: str

@dataclass(frozen=True, slots=True, repr=False)
class OXPreparedReview:
    review_id: str
    scope: OXReviewScope
    snapshot: OXSnapshot
    packet_bytes: bytes = field(repr=False)
    packet_sha256: str
    prepared_request: PreparedProviderRequest = field(repr=False)
```

- [ ] **Step 1: RED**

Test frozen dataclasses, closed enums, safe repr, non-empty bounded objective, normalized relative scope paths, valid SHA/count invariants, and settings constants.

```powershell
python -m pytest tests/ox/test_models.py -q
```

Expected: import failure because the clean-room package is absent.

- [ ] **Step 2: GREEN**

Define in `settings.py`:

```python
OX_REVIEW_ID_PREFIX = "OX-"
OX_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
OX_MODEL_ID = "zai/glm-5.3-flash"
OX_SNAPSHOT_POLICY_VERSION = "ox-snapshot-v1"
OX_PACKET_POLICY_VERSION = "ox-packet-v1"
OX_MAX_ARTIFACT_BYTES = 1_000_000
OX_MAX_ARTIFACTS = 5_000
OX_MAX_SNAPSHOT_CONTENT_BYTES = 3_250_000
OX_MAX_PACKET_BYTES = 3_500_000
OX_TIMEOUT_POLICY = ProviderTimeoutPolicy(
    connect_seconds=10.0,
    write_seconds=30.0,
    read_seconds=600.0,
    pool_seconds=10.0,
    absolute_deadline_seconds=600.0,
)
```

`OXSettings.load()` reads `AI_GATEWAY_API_KEY` only when called. Evidence root: `BYTE_MCP_OX_EVIDENCE_DIR` when set; otherwise `%LOCALAPPDATA%/Byte-MCP/ox` on Windows or `${XDG_DATA_HOME:-~/.local/share}/byte-mcp/ox` elsewhere. `repr` exposes only whether a credential is configured.

- [ ] **Step 3: Verify and commit**

```powershell
python -m pytest tests/ox/test_models.py -q
python -m ruff check src/byte_mcp/ox tests/ox/test_models.py
python -m ruff format --check src/byte_mcp/ox tests/ox/test_models.py
git add src/byte_mcp/ox tests/ox/test_models.py
git commit -m "feat: define clean-room OX contracts"
```

---

### Task 3: Enforce Repository Authority and Bounded/Full Scope

**Files:**
- Create: `src/byte_mcp/ox/scope.py`
- Create: `tests/ox/test_scope.py`
- Create: `config/ox-repositories.example.json`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OXResolvedRepository:
    alias: str
    path: Path = field(repr=False)

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

- [ ] **Step 1: RED**

Test rejection of absolute paths, drive prefixes, `..`, slash/backslash repository names, control characters, repository symlink/junctions, bounded path symlink/junction components, and escape attempts. `FULL_REPOSITORY` requires no paths; `BOUNDED` requires at least one normalized repository-relative POSIX path.

```powershell
python -m pytest tests/ox/test_scope.py -q
```

Expected: import failure.

- [ ] **Step 2: GREEN — link-safe resolution**

Repository selection is a direct child of `projects_root`. Before any `.resolve()`, walk each existing lexical component and call the existing provider-neutral/core `is_link_or_junction()` security helper. Bounded paths use the established `resolve_under_root()` containment behavior or an OX-local equivalent with the same component-by-component link/junction rejection. Never call naked `Path.resolve(strict=True)` on user-selected scope before checking components.

`config/ox-repositories.example.json` may document friendly aliases, but every alias must remain contained beneath `projects`; arbitrary absolute targets are invalid.

- [ ] **Step 3: Verify and commit**

```powershell
python -m pytest tests/ox/test_scope.py -q
python -m ruff check src/byte_mcp/ox/scope.py tests/ox/test_scope.py
python -m ruff format --check src/byte_mcp/ox/scope.py tests/ox/test_scope.py
git add src/byte_mcp/ox/scope.py tests/ox/test_scope.py config/ox-repositories.example.json
git commit -m "feat: bound OX reviews to projects root"
```

---

### Task 4: Freeze the Current Filesystem Snapshot

**Files:**
- Create: `src/byte_mcp/ox/snapshot.py`
- Create: `tests/ox/test_snapshot.py`

**Interface:**

```python
def freeze_snapshot(repository: OXResolvedRepository, scope: OXReviewScope) -> OXSnapshot: ...
```

- [ ] **Step 1: RED — current bytes and inclusions**

Create a temp Git repository. Commit a file, then stage/unstage modifications and create an eligible untracked file. Assert snapshot bytes equal current filesystem bytes, not committed bytes.

- [ ] **Step 2: RED — exclusions, links, nested repos**

Test `.env`, `.git`, `.venv`, `venv`, `node_modules`, `dist`, `build`, caches, coverage, private keys/certs, databases, archives, binary/media, evidence paths, artifact >1,000,000 bytes, symlink/junction, and nested repo/submodule. Direct selection of a link/junction fails closed; traversal encounters are recorded as exclusions and never followed.

- [ ] **Step 3: RED — determinism and limits**

Assert sorted logical paths, deterministic exclusions, per-file SHA-256, UTF-8/NUL classification, 5,001-artifact failure, aggregate content >3,250,000 failure, and distinct snapshot SHA for any byte/path/inventory/scope change.

```powershell
python -m pytest tests/ox/test_snapshot.py -q
```

Expected: FAIL because `freeze_snapshot` is absent.

- [ ] **Step 4: GREEN**

Use `os.scandir` without following links. Reject content containing NUL or invalid UTF-8 as non-text. Preserve exact bytes for included artifacts. Do not recursively enter any directory that is a link/junction or contains nested Git-repository metadata. Git is optional metadata only; its failure must not alter content authority.

Canonical snapshot identity is SHA-256 of canonical JSON binding repository alias, mode, requested paths, `OX_SNAPSHOT_POLICY_VERSION`, sorted included `{logical_path, byte_length, content_sha256, classification, git_state}` and sorted `{logical_path, reason}` exclusions. No absolute path enters the manifest.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest tests/ox/test_snapshot.py -q
python -m ruff check src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
python -m ruff format --check src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
git add src/byte_mcp/ox/snapshot.py tests/ox/test_snapshot.py
git commit -m "feat: freeze current OX repository snapshots"
```

Reconcile Slice 2 against the spec before continuing.

---

### Task 5: Build Deterministic Packet and Prepared Request

**Files:**
- Create: `src/byte_mcp/ox/packet.py`
- Create: `tests/ox/test_packet.py`

**Interfaces:**

```python
def build_review_packet(scope: OXReviewScope, snapshot: OXSnapshot) -> bytes: ...
def prepare_ox_request(packet_bytes: bytes) -> PreparedProviderRequest: ...
```

- [ ] **Step 1: RED**

Assert identical frozen snapshot → byte-identical packet; packet includes objective, normalized scope, `OX_PACKET_POLICY_VERSION`, snapshot SHA, bounded repository metadata, each artifact exactly once in sorted order, and exact frozen text. Assert no absolute local path and no structured findings/JSON response instruction. Packet >3,500,000 bytes fails locally.

Prepared body must equal canonical serialization of:

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

`SYSTEM_PROMPT` says OX is an independent adversarial code reviewer; it reviews only supplied frozen material; checks correctness, security, reliability, regression, architecture, edge cases, and testing; and responds naturally.

```powershell
python -m pytest tests/ox/test_packet.py -q
```

Expected: FAIL because packet functions are absent.

- [ ] **Step 2: GREEN**

Call existing `prepare_provider_request(provider_id="ox", method="POST", target_origin="https://ai-gateway.vercel.sh", endpoint_path="/v1/chat/completions", model_id="zai/glm-5.3-flash", body=body)`. The returned `body_bytes` are the request authority; later transport must not use `json=` or reserialize.

- [ ] **Step 3: Verify and commit**

```powershell
python -m pytest tests/ox/test_packet.py -q
python -m ruff check src/byte_mcp/ox/packet.py tests/ox/test_packet.py
python -m ruff format --check src/byte_mcp/ox/packet.py tests/ox/test_packet.py
git add src/byte_mcp/ox/packet.py tests/ox/test_packet.py
git commit -m "feat: build deterministic free-form OX packets"
```

---

### Task 6: Persist Durable Evidence and Irreversible Send Authority

**Files:**
- Create: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_evidence.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OXReviewEvidence:
    review_id: str
    state: OXReviewState
    repository: str
    mode: OXReviewMode
    snapshot_sha256: str
    request_sha256: str
    provider_started_at: str | None
    provider_finished_at: str | None
    attempt_outcome: str | None
    response_bytes: int | None
    review_text: str | None

class OXEvidenceStore:
    def allocate_review_id(self) -> str: ...
    def persist_prepared(self, prepared: OXPreparedReview) -> None: ...
    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool: ...
    def persist_response(self, review_id: str, body: bytes) -> None: ...
    def persist_review_text(self, review_id: str, text: str) -> None: ...
    def finalize(self, review_id: str, terminal_metadata: Mapping[str, object]) -> None: ...
    def get(self, review_id: str) -> OXReviewEvidence: ...
```

- [ ] **Step 1: RED — layout and immutability**

Before send require `review.json`, `snapshot.json`, `packet.bin`, `request.bin`. First claim atomically creates `send.claim`; first claim returns `True`, all later/restarted claims return `False`. Immutable files cannot be rewritten with different bytes. `response.bin` and `review.txt` are write-once.

- [ ] **Step 2: RED — durability and projection**

A claim with no trustworthy terminal outcome projects `OUTCOME_UNKNOWN`; pre-claim prepared evidence projects `READY`. `COMPLETED` requires durable `response.bin`, non-empty `review.txt`, and matching stored hashes/counts. Safe `get()` exposes no raw restricted bytes or absolute paths.

```powershell
python -m pytest tests/ox/test_evidence.py -q
```

Expected: FAIL because store is absent.

- [ ] **Step 3: GREEN — filesystem atomicity**

Allocate IDs by scanning existing `OX-\d{6}` directories, then atomically `mkdir(exist_ok=False)` the next candidate; on `FileExistsError`, increment and retry locally. No process-global lock is relied upon for correctness.

Create `send.claim` using `os.open(..., os.O_CREAT | os.O_EXCL | os.O_WRONLY)`. Atomic mutable projection writes use temp file in the same directory → `flush()` → `os.fsync(file.fileno())` → `os.replace()`, followed by directory fsync where supported. Immutable files use exclusive-create and fsync. Never delete `send.claim`.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest tests/ox/test_evidence.py -q
python -m ruff check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
python -m ruff format --check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git add src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git commit -m "feat: persist immutable OX review evidence"
```

---

### Task 7: Fail Closed on Provider-Bound Secret and Request-Identity Risk

**Files:**
- Modify: `src/byte_mcp/ox/packet.py`
- Create: `tests/ox/test_security.py`

**Interface:**

```python
def validate_provider_bound_safety(
    packet_bytes: bytes,
    request_bytes: bytes,
    *,
    exact_credential: str | None,
) -> None: ...
```

- [ ] **Step 1: RED**

Test PEM private-key markers and exact credential occurrence independently in `packet_bytes` and serialized `request_bytes`; every case fails safely without echoing the secret. A near-match credential is not treated as exact. Also test `validate_prepared_provider_request_integrity()` detects body/request identity tampering before claim.

```powershell
python -m pytest tests/ox/test_security.py -q
```

Expected: FAIL because safety helper is absent.

- [ ] **Step 2: GREEN**

Scan only already-frozen provider-bound bytes. Fixed strong markers include the private-key header families (`BEGIN PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`, `BEGIN EC PRIVATE KEY`, `BEGIN OPENSSH PRIVATE KEY`). Exact credential comparison uses UTF-8 bytes when configured. Do not add entropy scoring or claim universal secret detection.

- [ ] **Step 3: Verify and commit**

```powershell
python -m pytest tests/ox/test_security.py -q
python -m ruff check src/byte_mcp/ox/packet.py tests/ox/test_security.py
python -m ruff format --check src/byte_mcp/ox/packet.py tests/ox/test_security.py
git add src/byte_mcp/ox/packet.py tests/ox/test_security.py
git commit -m "feat: fail closed on unsafe OX provider material"
```

Reconcile Slice 3 against the spec before continuing.

---

### Task 8: Execute Exactly One Transport and Parse Only After Evidence Persistence

**Files:**
- Create: `src/byte_mcp/ox/client.py`
- Create: `tests/ox/test_client.py`

**Interfaces:**

```python
async def execute_ox_transport(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderTransportResponse: ...

def extract_ox_review_text(response_body: bytes) -> str: ...
```

`execute_ox_transport` does **not** decode or semantically inspect the response body. This separation is required so `service.py` can durably persist `response.bin` before calling `extract_ox_review_text`.

- [ ] **Step 1: RED — one transport**

With `httpx.MockTransport`, assert one handler invocation, exact `prepared_request.body_bytes`, Vercel endpoint, no redirect/fallback/retry, request identity preserved, and shared outcome mappings: connect/pool definite `NOT_SENT`; complete non-2xx `REJECTED`; write/read/deadline/remote uncertainty `OUTCOME_UNKNOWN`.

- [ ] **Step 2: RED — pure free-form extraction**

After a caller supplies already-persisted bytes, accept one non-empty `choices[0].message` with role `assistant` and string `content`. Accept arbitrary prose/Markdown including “I found no material issues.” Reject malformed JSON, missing/multiple choices, wrong role/type, and whitespace-only content. Do not parse findings or severity.

```powershell
python -m pytest tests/ox/test_client.py -q
```

Expected: FAIL because client functions are absent.

- [ ] **Step 3: GREEN**

`execute_ox_transport` constructs `ProviderAuthorization(f"Bearer {api_key}")` and calls shared `execute_once(...)` exactly once using `OX_TIMEOUT_POLICY`; it returns the raw `ProviderTransportResponse` unchanged. `extract_ox_review_text` is a pure bytes → text protocol function with no networking or persistence.

- [ ] **Step 4: Verify shared provider regression and commit**

```powershell
python -m pytest tests/ox/test_client.py tests/providers tests/nvidia -q
python -m ruff check src/byte_mcp/ox/client.py tests/ox/test_client.py
python -m ruff format --check src/byte_mcp/ox/client.py tests/ox/test_client.py
git add src/byte_mcp/ox/client.py tests/ox/test_client.py
git commit -m "feat: add one-shot OX provider transport"
```

Provider calls: `0` real; mock/loopback only. Reconcile Slice 4.

---

### Task 9: Orchestrate the Synchronous Review Lifecycle

**Files:**
- Create: `src/byte_mcp/ox/service.py`
- Create: `tests/ox/test_service.py`
- Modify: `tests/ox/test_security.py`

**Interface:**

```python
class OXReviewService:
    def __init__(
        self,
        scope_resolver: OXScopeResolver,
        evidence_store: OXEvidenceStore,
        settings_loader: Callable[[], OXSettings],
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

- [ ] **Step 1: RED — success ordering**

Assert exact order:

```text
scope → snapshot → packet/request → persist prepared
→ load credential → validate prepared-request integrity
→ scan packet + request for credential/private-key markers
→ claim send exactly once
→ execute one transport
→ persist exact complete response.bin
→ if 2xx: extract assistant text
→ persist review.txt
→ persist COMPLETED review.json
→ return review
```

The mock transport must prove exactly one request.

- [ ] **Step 2: RED — pre-claim failures**

Invalid scope, unsafe snapshot, oversize snapshot/packet/request, missing credential, packet/request secret collision, prepared-request integrity mismatch, and prepared-evidence persistence failure produce zero transport calls and no `send.claim`.

- [ ] **Step 3: RED — post-claim outcomes**

After claim: `NOT_SENT` connect/pool failure → terminal `FAILED`, claim consumed; complete provider rejection → persist complete response bytes then `FAILED`; write/read/deadline/remote uncertainty → `OUTCOME_UNKNOWN`; 2xx malformed/empty assistant → persist `response.bin` first, then `FAILED`; inability to persist the complete response after remote activity → never `COMPLETED`, conservatively `OUTCOME_UNKNOWN`. No path retries.

- [ ] **Step 4: RED — retrieval**

`get_review()` performs zero networking and returns only safe review ID/state/repository/mode/scope summary/snapshot SHA/request SHA/provider/model/timestamps/outcome/safe counts/review text when completed. No absolute path, packet, request body, raw envelope, key, environment, or arbitrary exception.

```powershell
python -m pytest tests/ox/test_service.py tests/ox/test_security.py -q
```

Expected: FAIL because service is absent.

- [ ] **Step 5: GREEN and verify**

Implement exactly the ordering above. If `claim_send` returns `False`, project existing evidence and never call transport.

```powershell
python -m pytest tests/ox/test_service.py tests/ox/test_security.py -q
python -m ruff check src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
python -m ruff format --check src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
git add src/byte_mcp/ox/service.py tests/ox/test_service.py tests/ox/test_security.py
git commit -m "feat: add synchronous OX review lifecycle"
```

---

### Task 10: Qualify Crash, Replay, Concurrency, and Evidence Ordering

**Files:**
- Create: `tests/ox/test_crash_and_concurrency.py`
- Modify production only for a RED-proven defect.

- [ ] **Step 1: RED — concurrent claim**

Barrier-synchronize two threads/processes claiming the same review. Require exactly one `True`, one `False`, one immutable `send.claim`, and at most one mock transport invocation through service-level duplicate execution.

- [ ] **Step 2: RED — restart projections**

Simulate restart after: prepared-before-claim; claim-before-transport; completed HTTP before response persistence; response persistence before review text; review text before terminal metadata; terminal completion before MCP return.

Expected projection:

```text
prepared, no claim                    READY
claim, no trustworthy terminal        OUTCOME_UNKNOWN
claim + response, no terminal         OUTCOME_UNKNOWN
claim + review.txt, no terminal       OUTCOME_UNKNOWN
valid terminal completion             COMPLETED
```

Restart performs no network, never removes claim, and never reconstructs send authority.

- [ ] **Step 3: RED — completion evidence invariant**

Corrupt/missing `response.bin`, `review.txt`, hashes, or counts must prevent a trustworthy `COMPLETED` projection.

```powershell
python -m pytest tests/ox/test_crash_and_concurrency.py -q
```

Expected: RED until all failure boundaries are implemented.

- [ ] **Step 4: Fix only proven defects, verify, commit**

```powershell
python -m pytest tests/ox/test_crash_and_concurrency.py tests/ox/test_evidence.py tests/ox/test_service.py -q
python -m ruff check src/byte_mcp/ox tests/ox/test_crash_and_concurrency.py
git add src/byte_mcp/ox tests/ox/test_crash_and_concurrency.py
git commit -m "test: qualify OX crash and replay boundaries"
```

---

### Task 11: Lazy Runtime and Exact Two-Tool MCP Surface

**Files:**
- Create: `src/byte_mcp/ox/runtime.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/ox/test_mcp_surface.py`

**Interfaces:**

```python
@dataclass(slots=True)
class OXRuntime:
    @classmethod
    def load(cls, settings: Settings, roots: Mapping[str, Path]) -> "OXRuntime": ...
    def require_service(self) -> OXReviewService: ...
```

Server calls `OXRuntime.load(SETTINGS, service().roots)`. It must require the existing `projects` root and must not reload or invent a second filesystem authority source.

MCP surface:

```python
@mcp.tool(annotations=OX_EXTERNAL)
async def ox_review(
    repository: str,
    mode: str,
    objective: str,
    paths: list[str] | None = None,
) -> dict[str, object]: ...

@mcp.tool(annotations=READ_ONLY)
def ox_get_review(review_id: str) -> dict[str, object]: ...
```

- [ ] **Step 1: RED**

Assert server import/start succeeds even when OX provider credential/config is unavailable; provider key is not loaded at startup. Assert exactly two `ox_` registrations. Preserve exact core/Wolfram/NVIDIA names. `ox_get_review`: read-only/idempotent/openWorld false. `ox_review`: non-idempotent/external/openWorld true.

```powershell
python -m pytest tests/ox/test_mcp_surface.py -q
```

Expected: FAIL because clean-room OX tools are not registered.

- [ ] **Step 2: GREEN**

Lazy-import `byte_mcp.ox.runtime` from server as needed. Contain OX runtime configuration failure so it cannot block core/NVIDIA/Wolfram startup. Update server instructions to describe OX specifically as independent adversarial code review, not general external validation.

- [ ] **Step 3: Verify and commit**

```powershell
python -m pytest tests/ox/test_mcp_surface.py tests/nvidia tests/wolfram -q
python -m ruff check src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
python -m ruff format --check src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
git add src/byte_mcp/server.py src/byte_mcp/ox/runtime.py tests/ox/test_mcp_surface.py
git commit -m "feat: expose clean-room OX review tools"
```

Reconcile Slice 5 against the spec before continuing.

---

### Task 12: Full Security, Privacy, and Isolation Qualification

**Files:**
- Modify: `tests/ox/test_security.py`
- Modify: `tests/ox/test_archive_absence.py`
- Production only for RED-proven defects.

- [ ] **Step 1: RED — privacy sentinel matrix**

Place distinct sentinels in API key, absolute repository path, proxy environment, transport exception, packet source, excluded secret file, and raw provider envelope. Inspect public MCP result, logs, safe exceptions, `review.json`, and `snapshot.json`. API key, proxy/environment values, arbitrary exception strings, and absolute paths must never persist or appear publicly. Restricted `packet.bin`, `request.bin`, `response.bin` intentionally contain canonical evidence but never the credential.

- [ ] **Step 2: RED — import/network isolation**

AST-scan `src/byte_mcp/ox/*.py` rejecting `byte_mcp.nvidia` and `byte_mcp.wolfram`; scan NVIDIA rejecting `byte_mcp.ox`. Install a non-loopback socket/network guard and prove scope/snapshot/packet/pre-claim failures/runtime initialization/`ox_get_review` make no network calls.

- [ ] **Step 3: RED — redirects and tool authority**

Prove redirects are not followed, no provider tool loop exists, and no Wolfram path is callable from OX.

```powershell
python -m pytest tests/ox/test_security.py tests/ox/test_archive_absence.py -q
```

Expected: RED until all isolation assertions hold.

- [ ] **Step 4: Fix only proven defects and commit**

```powershell
python -m pytest tests/ox -q
python -m ruff check src/byte_mcp/ox tests/ox
git add src/byte_mcp/ox tests/ox
git commit -m "test: harden OX security boundaries"
```

Reconcile Slice 6.

---

### Task 13: Write Operator Contract and Living Failure Map

**Files:**
- Create: `docs/OX.md`
- Create/Modify: `docs/FAILURE_MAP.md`
- Modify: `README.md`
- Modify: `archive/OX-ARCHIVE.md` only for verified archival clarification.

- [ ] **Step 1: Document the current operator contract**

`docs/OX.md` must cover: code-review-only purpose; exact two tools; projects-root authority; bounded/full modes; current-filesystem snapshot; exclusions; one authorization/one lifecycle/max-one-request; no retry; free-form output; evidence layout; `FAILED` vs `OUTCOME_UNKNOWN`; oversize behavior; no V1/V2 compatibility; restricted forensic inspection of `packet.bin`, `request.bin`, `response.bin`, `snapshot.json`; separate promotion/live-canary approvals.

- [ ] **Step 2: Update `docs/FAILURE_MAP.md`**

For scope escape/link, exclusion/secret, oversize, prepared-request mismatch, send-claim conflict, connect failure, write/read/deadline ambiguity, complete rejection, malformed/empty response, response persistence failure, crash after claim, evidence corruption, runtime configuration isolation, and MCP surface drift, document observable symptom, likely cause, first diagnostic, propagation, safe recovery, evidence/data risk, do-not warning, and exact related tests.

- [ ] **Step 3: Remove current-facing obsolete OX guidance**

Search README/docs for legacy execution instructions. Keep history only where clearly archival. README links only to the new OX contract and archive note.

- [ ] **Step 4: Commit**

```powershell
git add docs/OX.md docs/FAILURE_MAP.md README.md archive/OX-ARCHIVE.md
git commit -m "docs: document clean-room OX operation"
```

---

### Task 14: Final Provider-Free Qualification and Candidate Freeze

**Files:**
- No planned product changes. Any defect returns through a focused RED/GREEN fix and separate commit.

- [ ] **Step 1: Dependency, compile, lint, format**

```powershell
python -m pip check
python -m compileall -q src tests scripts/mcp_smoke_test.py scripts/wolfram_qualification.py scripts/wolfram_native_calibration.py
python -m ruff check .
python -m ruff format --check src/byte_mcp/ox src/byte_mcp/server.py tests/ox
```

Expected: PASS. Do not reformat unrelated historical files.

- [ ] **Step 2: Full tests**

```powershell
python -m pytest tests/ox -q
python -m pytest tests/providers tests/nvidia tests/wolfram -q
python -m pytest
```

Expected: all PASS, zero live provider calls.

- [ ] **Step 3: Launcher/runtime-static checks**

```powershell
pwsh -NoLogo -NoProfile -File .\scripts\Check-Launcher.ps1
```

Expected: PASS. No live runtime promotion/mutation.

- [ ] **Step 4: Exact surface/absence/neighbor checks**

Require only core + `wolfram_query` + `nvidia_review` + `nvidia_get_review` + `ox_review` + `ox_get_review`; no legacy/lifetime/retry/continuation/revalidation OX tool. Diff NVIDIA/Wolfram production paths against the implementation base; any shared-provider change must be separately justified by tests, and no direct neighbor edit may exist merely to accommodate OX.

- [ ] **Step 5: Final reconciliation**

Record answers to:

```text
What did the approved plan require?
What now exists?
What tests prove it?
Did implementation add anything not authorized?
Did an assumption change?
What remains?
```

Explicitly verify: V1/V2 execution absent; exact two-tool surface; projects-root only; bounded+full; dirty/untracked included; snapshot immutable; secret/oversize/request-integrity fail before claim/network; one request max; no retry; response persisted before extraction; free-form output; file evidence only; restart never restores authority; NVIDIA/Wolfram/core PASS; failure map complete; provider calls `0`.

- [ ] **Step 6: Freeze exact candidate**

```powershell
git status --short
git rev-parse HEAD
git log -12 --oneline
```

Require clean worktree. If qualification caused any committed fix/docs change, rerun affected gates on the new HEAD before claiming it qualified.

- [ ] **Step 7: STOP before runtime promotion**

Report exact candidate SHA, archive identities, complete gate results, exact MCP surface, and:

```text
OX_PROVIDER_CALLS=0
NVIDIA_PROVIDER_CALLS=0
WOLFRAM_PROVIDER_CALLS=0
RUNTIME_MUTATIONS=0
```

Do not promote automatically. Reconcile Slice 7.

---

### Task 15: Separately Authorized Provider-Free Runtime Promotion

**Precondition:** fresh explicit authorization naming the exact Task 14 candidate SHA.

- [ ] **Step 1: Read `superpowers:verification-before-completion` and use the established Byte-MCP runtime procedure.**
- [ ] **Step 2: Verify current runtime HEAD, cleanliness, supervisor/launcher status, ports/tunnel health, current tool surface, and candidate delta. STOP on drift.**
- [ ] **Step 3: Promote exact candidate transactionally with OX provider activity unused/disabled during verification.**
- [ ] **Step 4: Verify deployed candidate identity, READY runtime, stable tunnel/server, exact tools, and core/NVIDIA/Wolfram/OX local surfaces with zero provider calls.**
- [ ] **Step 5: Cross an established supervisor cadence and recheck stability.**
- [ ] **Step 6: STOP before any valid live `ox_review`.**

No production defect is patched in-place during promotion; return to implementation with RED/GREEN and produce a new candidate.

---

### Task 16: First Real OX Canary — Separate Authorization Boundary

**Precondition:** provider-free runtime promotion has passed and Nolan explicitly authorizes one actual OX review with a specific repository/scope/objective.

- [ ] **Step 1: Resolve exactly the authorized bounded/full scope; never widen it.**
- [ ] **Step 2: Execute one `ox_review` lifecycle. The authorization covers snapshot → packet/request → evidence → irreversible claim → at most one provider request → response persistence → free-form result. No second approval.**
- [ ] **Step 3: On success, use `ox_get_review(review_id)` plus restricted local evidence inspection to verify identity, exact response evidence, and one-request maximum.**
- [ ] **Step 4: On `FAILED` or `OUTCOME_UNKNOWN`, STOP. Never retry. A later provider call requires a new review identity and fresh authorization.**
- [ ] **Step 5: If accepted, record the runtime/canary identity in a documentation-only qualification receipt.**

---

## Plan Self-Review

### Spec coverage

- Archive/remove V1/V2: Tasks 0–1, 13–14.
- Whole-lifecycle single approval and exact two-tool surface: Tasks 9, 11, 15–16.
- No retry/background/continuation/revalidation: Global Constraints, Tasks 8–10, 14, 16.
- `/AiProjects` authority and link-safe bounded/full scope: Task 3.
- Current dirty/untracked filesystem state, exclusions, deterministic snapshot: Task 4.
- Frozen packet, packet policy identity, oversize fail-closed: Task 5.
- Durable filesystem evidence and irreversible send claim: Task 6.
- Layered packet/request credential safety and request-integrity preflight: Task 7.
- One-shot transport with response interpretation separated from transport: Task 8.
- Exact raw response persistence before interpretation/final completion: Task 9.
- Crash/restart/concurrency/send-authority semantics: Task 10.
- Lazy OX runtime and exact MCP surface: Task 11.
- Privacy/import/network isolation: Task 12.
- Failure-aware/operator docs: Task 13.
- Provider-free qualification and exact candidate freeze: Task 14.
- Separate promotion/live provider authorization: Tasks 15–16.

### Placeholder scan

No `TBD`, `TODO`, angle-bracket substitution, unnamed future file, or command placeholder remains. Historical archive SHAs are concrete. Format qualification names the exact planned changed Python scope rather than an unresolved file-list token.

### Type and ordering consistency

Canonical names are `OXReviewMode`, `OXReviewState`, `OXReviewScope`, `OXSnapshotExclusion`, `OXResolvedRepository`, `OXArtifact`, `OXSnapshot`, `OXPreparedReview`, `OXSettings`, `OXScopeResolver`, `OXEvidenceStore`, `OXReviewEvidence`, `OXReviewService`, `execute_ox_transport`, and `extract_ox_review_text`.

The provider response ordering is deliberately split across client/service: transport returns canonical complete bytes; service persists `response.bin`; only then may `extract_ox_review_text` decode/interpret those bytes. No client abstraction is allowed to parse before persistence.

### Security consistency

Scope resolution checks link/junction components before canonical resolution. Provider-bound safety scans both packet and exact serialized request. Prepared-request integrity is revalidated before irreversible send claim. `send.claim` is permanent, and restart never restores authority.

### Scope check

This remains one cohesive implementation campaign with seven provider-free implementation slices. Tasks 15 and 16 are explicit post-candidate boundaries and are not authorized by implementation approval.
