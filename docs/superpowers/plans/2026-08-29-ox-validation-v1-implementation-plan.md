# Byte-MCP OX Validation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated OX / GLM-5.3-Flash external-validation capability to the existing Byte-MCP server, with deterministic committed-state review bundles, digest-bound human approval, append-only evidence, fixed Z.AI-only Vercel routing, multi-turn review/adjudication, and blind/targeted revalidation.

**Architecture:** Preserve the existing `FileService` and four local tools. Add an isolated `byte_mcp.ox` subsystem containing OX-only settings, a deterministic repository registry/Git-object reader, bundle builder, append-only evidence store, provider protocol/client, orchestration service, and optional runtime. Use Vercel AI Gateway only as transport to fixed `zai/glm-5.3-flash`; enforce `providerOptions.gateway.only=["zai"]` in every provider request.

**Tech Stack:** Python 3.12; `mcp[cli]==1.28.1`; `dulwich>=1.2.13,<2` for read-only Git-object access; stable `httpx>=0.28.1,<1` for direct Vercel REST; stdlib dataclasses/JSON/SHA-256/threading/atomic filesystem operations; pytest; ruff; GitHub Actions on Windows and Ubuntu.

**Spec:** `docs/superpowers/specs/2026-08-29-ox-integration-design.md`

## Global Constraints

- One Byte-MCP server only; no second OX server/tunnel/repository.
- OX-specific implementation only; no model/provider abstraction.
- Fixed endpoint `https://ai-gateway.vercel.sh/v1/chat/completions`, model `zai/glm-5.3-flash`, provider allowlist `zai` only.
- `AI_GATEWAY_API_KEY` is environment-only and never committed, persisted, logged, returned, or embedded in exceptions.
- Existing `list_roots`, `list_directory`, `search`, and `fetch` remain functional when OX is disabled or misconfigured.
- Public OX tools accept repository aliases and exact 40-hex commit SHAs, never arbitrary filesystem paths or mutable working-tree snapshots.
- No supported OX path executes repository code, Git subprocesses, tests/builds/package managers/shells, or arbitrary subprocesses.
- Preparation makes zero provider calls. Repository transmission requires a second explicit digest-bound approval action.
- `ox_continue` cannot introduce new repository artifacts. Scope expansion requires a new prepared/approved bundle.
- Canonical OX evidence is append-only and stored outside every reviewed repository.
- One Byte-MCP process owns a given OX evidence root; ID allocation and per-review mutations are thread-safe in-process.
- Each outbound action performs at most one HTTP request and one provider response; no automatic retries or provider fallback.
- Automated tests use fakes/`httpx.MockTransport`; they never use Nolan's real key or credits.
- A provider response is not reported as a successful evidenced review until required response/attempt evidence is durable.
- Existing compile/lint/test/dependency CI gates remain green on Windows and Ubuntu.

## Locked module layout

Create:

```text
src/byte_mcp/ox/
├── __init__.py
├── models.py          # enums/dataclasses only
├── settings.py        # OX environment/default paths
├── repositories.py    # registry + immutable Dulwich reads
├── bundles.py         # deterministic packet/manifest construction
├── evidence.py        # append-only evidence + transitions/locks
├── protocol.py        # messages + strict findings
├── client.py          # only HTTP-capable module
├── service.py         # review orchestration
└── runtime.py         # optional AVAILABLE/DISABLED/MISCONFIGURED lifecycle
```

Create tests under `tests/ox/`. Do not add OX implementation to existing `src/byte_mcp/service.py`.

---

### Task 1: OX settings, domain contracts, errors, and dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `src/byte_mcp/errors.py`
- Create: `src/byte_mcp/ox/__init__.py`
- Create: `src/byte_mcp/ox/models.py`
- Create: `src/byte_mcp/ox/settings.py`
- Create: `config/ox-repositories.example.json`
- Create: `tests/ox/__init__.py`
- Create: `tests/ox/test_models.py`
- Create: `tests/ox/test_settings.py`

**Interfaces:**
- Produces `OXSettings.load(repo_root: Path) -> OXSettings`.
- Produces enums `OXAvailability`, `ReviewState`, `AttemptOutcome`, `FindingStatus`.
- Produces immutable contracts `VerificationRecord`, `ProviderUsage`, `ProviderResult`, `Finding`, `AdjudicationEvent`.
- Produces all OX error classes as `ByteMCPError` descendants.

- [ ] **Step 1: Write RED tests for settings and secret-safe representation**

```python
def test_missing_key_is_allowed_in_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    settings = OXSettings.load(tmp_path)
    assert settings.api_key is None


def test_settings_repr_redacts_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "SENTINEL-SECRET")
    settings = OXSettings.load(tmp_path)
    assert "SENTINEL-SECRET" not in repr(settings)
```

Also test platform evidence-root selection and integer bounds.

- [ ] **Step 2: Run RED**

```bash
pytest tests/ox/test_models.py tests/ox/test_settings.py -v
```

Expected: import failures because `byte_mcp.ox` does not exist.

- [ ] **Step 3: Add dependencies and ignored local config**

Add runtime dependencies:

```toml
"dulwich>=1.2.13,<2",
"httpx>=0.28.1,<1",
```

Add `config/ox-repositories.local.json` to `.gitignore`.

- [ ] **Step 4: Add exact OX error taxonomy**

Add these to `src/byte_mcp/errors.py`:

```python
class OXUnavailableError(ByteMCPError): ...
class OXConfigurationError(ByteMCPError): ...
class OXApprovalError(ByteMCPError): ...
class OXRepositoryError(ByteMCPError): ...
class OXScopeError(ByteMCPError): ...
class OXBundleError(ByteMCPError): ...
class OXEvidenceError(ByteMCPError): ...
class OXAuthenticationError(ByteMCPError): ...
class OXPermissionError(ByteMCPError): ...
class OXRequestError(ByteMCPError): ...
class OXContextLimitError(ByteMCPError): ...
class OXRateLimitError(ByteMCPError): ...
class OXQuotaError(ByteMCPError): ...
class OXProviderUnavailableError(ByteMCPError): ...
class OXTransportError(ByteMCPError): ...
class OXProtocolError(ByteMCPError): ...
class OXFindingValidationError(OXProtocolError): ...
```

Provider-call errors that need delivery semantics expose a safe `attempt_outcome: str` attribute; they never retain/request headers.

- [ ] **Step 5: Implement settings and model contracts**

Use:

```python
@dataclass(frozen=True, slots=True, repr=False)
class OXSettings:
    api_key: str | None
    repositories_file: Path
    evidence_root: Path
    max_bundle_bytes: int = 4_000_000
    max_output_tokens: int = 16_384
    gateway_url: str = "https://ai-gateway.vercel.sh/v1/chat/completions"
    model: str = "zai/glm-5.3-flash"
    provider_slug: str = "zai"
```

`BYTE_MCP_OX_REPOSITORIES_FILE` defaults to `config/ox-repositories.local.json`. `BYTE_MCP_OX_EVIDENCE_DIR` overrides the platform default; otherwise use `%LOCALAPPDATA%/Byte-MCP/ox` on Windows, `$XDG_DATA_HOME/byte-mcp/ox` on Unix when set, otherwise `~/.local/share/byte-mcp/ox`. Bound bundle bytes to `16_384..16_000_000` and output tokens to `1_024..65_536`. Strip the environment key and treat blank as absent. `repr(settings)` reports only `api_key_configured=True/False`.

Use string enums with values exactly matching the approved spec, including `PREPARED`, `TRANSMITTING`, `REVIEWED`, `FAILED`, `OUTCOME_UNKNOWN`, `REVALIDATION_PREPARED`, `REVALIDATION_TRANSMITTING`, `BLIND_REVALIDATED`, `REVALIDATED`; attempt outcomes `NOT_SENT`, `REJECTED`, `COMPLETED`, `OUTCOME_UNKNOWN`; and finding statuses `RAISED`, `REPRODUCED`, `CONFIRMED`, `DISPROVED`, `DEFERRED`, `UNRESOLVED`, `REMEDIATED`, `REVALIDATED`.

- [ ] **Step 6: Add the repository-registry example**

```json
{
  "version": 1,
  "repositories": {
    "byte-mcp": {
      "path": "C:\\Users\\YOUR_USER\\AIProjects\\Byte-MCP",
      "subsystems": {
        "ox-validation": {
          "version": 1,
          "source_roots": ["src/byte_mcp/ox"],
          "test_roots": ["tests/ox"],
          "boundary_files": ["src/byte_mcp/server.py", "src/byte_mcp/errors.py", "src/byte_mcp/settings.py"],
          "context_files": ["pyproject.toml", "docs/superpowers/specs/2026-08-29-ox-integration-design.md"]
        }
      }
    }
  }
}
```

- [ ] **Step 7: Run GREEN and commit**

```bash
python -m compileall -q src tests
ruff check .
pytest tests/ox/test_models.py tests/ox/test_settings.py -v
pip check
git add pyproject.toml .gitignore config/ox-repositories.example.json src/byte_mcp/errors.py src/byte_mcp/ox tests/ox
git commit -m "feat: add OX validation contracts"
```

---

### Task 2: Repository registry and immutable Git-object reader

**Files:**
- Create: `src/byte_mcp/ox/repositories.py`
- Create: `tests/ox/helpers.py`
- Create: `tests/ox/test_repositories.py`

**Interfaces:**
- Produces `RepositoryRegistry.load(path: Path) -> RepositoryRegistry` and `.get(alias: str) -> RepositoryDefinition`.
- Produces `validate_ox_local_config(settings: OXSettings) -> RepositoryRegistry`.
- Produces `GitRepository.open(definition)`, `.resolve_commit(str)`, `.read_file(commit, path)`, `.iter_root_files(commit, root)`, `.repository_tree(commit)`, `.diff(base, target)`.

- [ ] **Step 1: Build RED Dulwich fixtures/tests without shell commands**

Use `dulwich.porcelain.init/add/commit` in `tests/ox/helpers.py` to create temporary repositories and exact commits. Tests prove: unknown alias denied; configured path must be absolute/existing Git repo; exact 40-hex SHA required; dirty working-tree edits do not change committed reads; recursive root expansion is stable POSIX-path order; missing mandatory roots/files fail; required symlink/submodule entries are rejected rather than followed/omitted; base-to-target diff comes from Git trees.

- [ ] **Step 2: Run RED**

```bash
pytest tests/ox/test_repositories.py -v
```

- [ ] **Step 3: Implement strict registry contracts**

```python
@dataclass(frozen=True, slots=True)
class SubsystemDefinition:
    subsystem_id: str
    version: int
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    boundary_files: tuple[str, ...]
    context_files: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RepositoryDefinition:
    alias: str
    path: Path
    subsystems: Mapping[str, SubsystemDefinition]
```

Aliases/IDs match `^[a-z][a-z0-9_-]{0,63}$`. Logical Git paths are relative forward-slash paths; reject absolute paths, drive prefixes, backslashes used for traversal, NUL, `.`/`..` traversal segments, and empty roots.

`validate_ox_local_config()` also rejects any configured `evidence_root` that is equal to or contained by an allowlisted repository, or any repository contained by the evidence root.

- [ ] **Step 4: Implement Dulwich immutable reads**

Open with `dulwich.repo.Repo`; resolve the object and require `Commit`. Walk committed trees via `repo.object_store.iter_tree_contents(commit.tree)`. Treat only regular file modes `0o100644`/`0o100755` as artifacts. Reject mode `0o120000` symlinks and `0o160000` submodules when matched by mandatory scope. Never dereference them through the working filesystem.

Generate diff bytes with `dulwich.patch.write_tree_diff(BytesIO(), repo.object_store, base_commit.tree, target_commit.tree, diff_binary=False)`.

- [ ] **Step 5: GREEN and commit**

```bash
ruff check src/byte_mcp/ox/repositories.py tests/ox/helpers.py tests/ox/test_repositories.py
pytest tests/ox/test_repositories.py -v
git add src/byte_mcp/ox/repositories.py tests/ox/helpers.py tests/ox/test_repositories.py
git commit -m "feat: add immutable OX repository reader"
```

---

### Task 3: Deterministic bundle and manifest construction

**Files:**
- Create: `src/byte_mcp/ox/bundles.py`
- Create: `tests/ox/test_bundles.py`

**Interfaces:**
- Produces immutable `BundleArtifact`, `ManifestEntry`, `ReviewManifest`, `PreparedBundle`.
- Produces `sha256_json(value: object) -> str` and `BundleBuilder.prepare(...) -> PreparedBundle`.

- [ ] **Step 1: Write RED determinism/completeness tests**

Tests prove every source/test root recursively contributes every regular blob; boundary/context files are mandatory; repeated paths have deterministic category metadata without duplicate payload transmission; ordering is stable; dirty working tree cannot substitute content; subsystem-definition hash changes with definition; verification stdout/stderr are preserved and hashed; identical input yields identical manifest digest; `max_bundle_bytes + 1` raises `OXBundleError` instead of trimming.

- [ ] **Step 2: Run RED**

```bash
pytest tests/ox/test_bundles.py -v
```

- [ ] **Step 3: Implement canonical hashing and packet fields**

Canonical JSON uses UTF-8, `ensure_ascii=False`, `sort_keys=True`, separators `(",", ":")`. Protocol version is `ox-review-v1`. Compute `manifest_sha256` over the canonical manifest payload with the digest field omitted.

Each artifact records logical path, sorted category tuple, raw byte length, raw SHA-256, and provider text. Provider text uses strict UTF-8 first; if invalid, decode with UTF-8 replacement and mark `text_encoding="utf-8-replacement"`; the raw hash never changes.

Packet includes repository identity, exact commits, subsystem definition/hash, deterministic repository tree, exact diff when a base exists, source/tests/boundary/context artifacts, verification evidence, and manifest. No summarization/ranking/truncation/fuzzy inference is permitted.

- [ ] **Step 4: GREEN and commit**

```bash
ruff check src/byte_mcp/ox/bundles.py tests/ox/test_bundles.py
pytest tests/ox/test_repositories.py tests/ox/test_bundles.py -v
git add src/byte_mcp/ox/bundles.py tests/ox/test_bundles.py
git commit -m "feat: build deterministic OX review bundles"
```

---

### Task 4: Append-only evidence, state reconstruction, concurrency, and retry claims

**Files:**
- Create: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_evidence.py`

**Interfaces:**
- Produces `EvidenceStore(root: Path)`.
- Produces review/revalidation/attempt ID allocation.
- Produces `persist_prepared_review`, `claim_initial_transmission`, `claim_retry_transmission`, `record_attempt_outcome`, `append_thread_message`, `persist_provider_response`, `persist_findings`, `append_adjudication`, `get_review`.

- [ ] **Step 1: Write RED persistence/concurrency tests**

Prove stable IDs such as `OX-000001`, `OX-000001-A001`, `OX-000001-RV001`; immutable JSON cannot be overwritten; JSONL history appends in order; a malformed/torn trailing line is reported/ignored conservatively rather than treated as valid state; provider messages and adjudication are separate; state reconstructs from identity/events; and two threads racing initial transmission yield exactly one successful claim.

Retry tests require the prior attempt to be `NOT_SENT`, `REJECTED`, or `OUTCOME_UNKNOWN`, require an explicit renewed-approval flag from the service, preserve the same manifest digest, allocate a new attempt ID, and never replace prior attempt evidence.

- [ ] **Step 2: Run RED**

```bash
pytest tests/ox/test_evidence.py -v
```

- [ ] **Step 3: Implement durable writes and locks**

For immutable JSON: same-directory temp file, write, `flush()`, `os.fsync()`, `os.replace()`. For JSONL: hold review lock, append one canonical line, `flush()`, `os.fsync()`. Wrap filesystem/serialization failures as sanitized `OXEvidenceError`.

Maintain one ID-allocation lock plus lazily-created per-review `threading.Lock`s. Allocate IDs by scanning existing evidence names under the allocation lock so process restart remains monotonic.

`claim_initial_transmission()` requires current state `PREPARED`, rechecks manifest digest, appends one durable `TRANSMISSION_INTENT` event that both claims the transition and identifies the attempt, then returns the attempt. `claim_retry_transmission()` requires an eligible failed/unknown prior attempt plus renewed approval and appends a new intent; it never silently retries.

- [ ] **Step 4: GREEN and commit**

```bash
ruff check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
pytest tests/ox/test_evidence.py -v
git add src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git commit -m "feat: add append-only OX evidence store"
```

---

### Task 5: Narrow Vercel/Z.AI client and one-attempt transport semantics

**Files:**
- Create: `src/byte_mcp/ox/client.py`
- Create: `tests/ox/test_client.py`

**Interfaces:**
- Produces `OXClient.complete(messages, *, json_mode: bool, attempt_id: str) -> ProviderResult`.
- Only this module imports/uses `httpx` for outbound OX traffic.

- [ ] **Step 1: Write RED `httpx.MockTransport` request-shape tests**

Assert every request contains:

```python
assert body["model"] == "zai/glm-5.3-flash"
assert body["stream"] is False
assert body["max_tokens"] == 16_384
assert body["providerOptions"] == {"gateway": {"only": ["zai"]}}
```

Formal review mode also includes `"response_format": {"type": "json_object"}`. Authorization exists only on the actual HTTP request. A sentinel secret must not appear in client `repr`, result serialization, safe error strings, or provider metadata.

- [ ] **Step 2: Write RED error/outcome tests**

401 -> `OXAuthenticationError`; 403 -> `OXPermissionError`; context-limit 4xx -> `OXContextLimitError`; other 4xx -> `OXRequestError`; 429 -> `OXRateLimitError` unless safe error code unambiguously means quota, then `OXQuotaError`; 5xx -> `OXProviderUnavailableError`.

`ConnectError`, `ConnectTimeout`, `PoolTimeout` carry `attempt_outcome="not_sent"`. `WriteTimeout`, `ReadTimeout`, `ReadError`, `WriteError`, `RemoteProtocolError` carry `attempt_outcome="outcome_unknown"`. No exception path retries.

- [ ] **Step 3: Run RED**

```bash
pytest tests/ox/test_client.py -v
```

- [ ] **Step 4: Implement one synchronous non-streaming request**

Use:

```python
httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
```

POST once to the fixed gateway URL. Construct `Authorization: Bearer <key>` only inside `complete()`. Parse one assistant choice plus safe response ID/model/usage and preserve raw JSON for evidence. Structural success-response defects raise `OXProtocolError`. Never persist headers or auto-retry.

- [ ] **Step 5: GREEN and commit**

```bash
ruff check src/byte_mcp/ox/client.py tests/ox/test_client.py
pytest tests/ox/test_client.py -v
git add src/byte_mcp/ox/client.py tests/ox/test_client.py
git commit -m "feat: add fixed OX gateway client"
```

---

### Task 6: OX protocol, strict findings, and initial review prepare/transmit/retry

**Files:**
- Create: `src/byte_mcp/ox/protocol.py`
- Create: `src/byte_mcp/ox/service.py`
- Create: `tests/ox/test_protocol.py`
- Create: `tests/ox/test_review_service.py`

**Interfaces:**
- Produces `build_initial_messages(bundle)`, `parse_findings(content, review_id)`.
- Produces `OXReviewService.prepare_review(...)`, `.transmit_review(review_id)`, `.retry_review(review_id, *, renewed_approval: bool)`.

- [ ] **Step 1: Write RED finding-schema tests**

Require top-level:

```json
{"protocol_version":"ox-findings-v1","findings":[...]}
```

Each finding requires `category`, `severity`, `confidence`, `location`, `claim`, `evidence`, `reproduction`, `expected_behavior`, `observed_or_predicted_behavior`, `disproof_condition`, `recommended_investigation`. Validate confidence `0..1`, known severity, field types, and deterministic local IDs `OX-000001-F001` in returned-array order. Raw provider content is never rewritten.

- [ ] **Step 2: Write RED prepare/transmit security tests**

Use `FailIfCalledClient.complete()` that raises `AssertionError`. Prove prepare, invalid repo/commit/scope, missing verification, oversized bundle, and evidence-persistence failure never reach it.

With a recording client, prove initial transmit sends the exact persisted digest once; wrong digest/state fails; the transmission API accepts only `review_id`, so it cannot redefine scope; concurrent transmit calls yield one client call; and retry after any unsuccessful/unknown attempt cannot send until `renewed_approval=True`.

- [ ] **Step 3: Run RED**

```bash
pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -v
```

- [ ] **Step 4: Implement validator messages and strict parse**

System mandate: OX is an independent validator, not implementation authority; make falsifiable claims; state uncertainty instead of inventing evidence; include a disproof condition; return `ox-findings-v1`. User message is generated solely from persisted prepared packet/objective.

- [ ] **Step 5: Implement exact transmission ordering**

`prepare_review()` builds/persists packet and returns a proposal with review ID, repo/subsystem, commits, objective, artifact count/bytes, digest, model/provider, `transmitted=False`.

`transmit_review()` loads prepared evidence, re-verifies manifest/target, calls `claim_initial_transmission()` before network access, calls client exactly once, persists raw response before parsing, appends exact assistant message, persists findings or `FINDINGS_INVALID`, records attempt outcome/usage/lifecycle, then returns. A malformed finding response raises `OXFindingValidationError` only after raw response is durable so a continuation can request resubmission.

Provider call errors are converted into durable attempt outcomes: `not_sent`/`rejected` -> review `FAILED`; ambiguous delivery -> `OUTCOME_UNKNOWN`.

`retry_review()` uses the exact persisted packet/history, requires renewed approval, obtains a new claim/attempt ID, and makes exactly one new client call.

- [ ] **Step 6: GREEN and commit**

```bash
ruff check src/byte_mcp/ox/protocol.py src/byte_mcp/ox/service.py tests/ox/test_protocol.py tests/ox/test_review_service.py
pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -v
git add src/byte_mcp/ox/protocol.py src/byte_mcp/ox/service.py tests/ox/test_protocol.py tests/ox/test_review_service.py
git commit -m "feat: add OX review protocol"
```

---

### Task 7: Continuation, local adjudication, blind/targeted revalidation, and explicit continuation retry

**Files:**
- Modify: `src/byte_mcp/ox/protocol.py`
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_review_followup.py`

**Interfaces:**
- Produces `continue_message(review_id, message)`, `retry_continuation(review_id, attempt_id, renewed_approval)`, `adjudicate(review_id, events)`.
- Produces `prepare_revalidation(...)`, `transmit_blind_revalidation(revalidation_id)`, `retry_revalidation(revalidation_id, renewed_approval)`, `run_targeted_revalidation(revalidation_id, finding_ids)`.

- [ ] **Step 1: Write RED continuation/adjudication tests**

Prove one message call -> one provider call; exact provider-native role order; replay may resend only previously approved original bundle/context; continuation never invokes repository reader/bundle builder for new artifacts; adjudication makes zero provider calls and appends separate events; only known finding IDs and valid status transitions are accepted.

For ambiguous continuation failure, persist the attempted user message/attempt identity without pretending an assistant reply exists. Retry references the exact prior attempt, accepts no replacement message, requires renewed approval because stateless replay may resend repository content, and makes one new call.

- [ ] **Step 2: Write RED revalidation tests**

Preparation against the new remediation commit makes zero network calls and creates a new manifest. Blind approval sends that exact manifest in a fresh thread with no original findings/adjudication/remediation narrative. Targeted completeness is blocked until blind success and may add only selected original finding/adjudication metadata plus the same already-approved remediation bundle. Retry after failed/unknown blind attempt requires renewed approval and cannot redefine target/scope.

- [ ] **Step 3: Run RED**

```bash
pytest tests/ox/test_review_followup.py -v
```

- [ ] **Step 4: Implement follow-up flows**

Persist the user continuation turn before attempting the call, with attempt identity. On success persist raw response then assistant turn. On ambiguous outcome retain the unresolved attempt; retry replays the exact persisted attempted turn/history without creating a second different user message.

Adjudication event requires `finding_id`, `status`, `evidence`, `reasoning_summary`; optional `remediation_commit`. Store append-only and do not rewrite OX output.

Blind revalidation reuses repository/subsystem identity but builds from fresh exact commits/verification and requires a new human-approved manifest. Targeted completeness uses the successful blind revalidation bundle plus selected existing finding/adjudication evidence only.

- [ ] **Step 5: GREEN and commit**

```bash
ruff check src/byte_mcp/ox tests/ox/test_review_followup.py
pytest tests/ox -v
git add src/byte_mcp/ox tests/ox/test_review_followup.py
git commit -m "feat: add OX follow-up and revalidation"
```

---

### Task 8: Optional runtime and exactly four MCP tools

**Files:**
- Create: `src/byte_mcp/ox/runtime.py`
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/ox/test_runtime.py`
- Create: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- Produces `OXRuntime.initialize(settings: OXSettings, audit: AuditLog) -> OXRuntime` and `.require_service() -> OXReviewService`.
- New public tools exactly `ox_review`, `ox_continue`, `ox_revalidate`, `ox_get_review`.

- [ ] **Step 1: Write RED runtime-isolation tests now that all dependencies exist**

Missing key -> `DISABLED`; malformed/missing registry, evidence-root overlap, or local config error -> `MISCONFIGURED`; valid config/key -> `AVAILABLE` with constructed service. No state performs network I/O. `main()` still initializes required `FileService` before bind and may initialize OX without preventing bind when disabled/misconfigured.

- [ ] **Step 2: Write RED tool/annotation/signature tests**

Use:

```python
OX_EXTERNAL_ACTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
```

`ox_get_review` uses existing `READ_ONLY`; the other three use `OX_EXTERNAL_ACTION` because their most consequential modes create evidence and/or transmit externally.

Expose these signatures:

```python
def ox_review(
    repository: str | None = None,
    subsystem: str | None = None,
    target_commit: str | None = None,
    base_commit: str | None = None,
    objective: str | None = None,
    verification: list[dict[str, Any]] | None = None,
    review_id: str | None = None,
    approve: bool = False,
    retry: bool = False,
) -> dict[str, Any]: ...


def ox_continue(
    review_id: str,
    mode: str = "message",
    message: str | None = None,
    adjudications: list[dict[str, Any]] | None = None,
    retry_attempt_id: str | None = None,
    approve_retry: bool = False,
) -> dict[str, Any]: ...


def ox_revalidate(
    review_id: str,
    revalidation_id: str | None = None,
    target_commit: str | None = None,
    base_commit: str | None = None,
    verification: list[dict[str, Any]] | None = None,
    approve: bool = False,
    retry: bool = False,
    targeted: bool = False,
    finding_ids: list[str] | None = None,
) -> dict[str, Any]: ...


def ox_get_review(review_id: str, view: str = "summary") -> dict[str, Any]: ...
```

Strict mode rules: initial prepare has no `review_id`; approval/retry has `review_id` and no bundle-defining fields; retry requires `approve=True`; continuation `message`, `adjudicate`, and retry modes are mutually exclusive; continuation retry requires `retry_attempt_id` + `approve_retry=True` and no replacement message; revalidation prepare/approve/retry/targeted are mutually exclusive; retrieval view is one of `summary`, `findings`, `thread`, `manifest`, `adjudication`, `attempts`, `revalidation`.

- [ ] **Step 3: Implement runtime and server wiring**

Keep existing `service()` unchanged. Add separate lazy `_ox_runtime`. `main()` calls `service()` first, then initializes OX runtime locally, then binds. OX initialization failures are captured as disabled/misconfigured runtime state rather than raised through core startup. `require_service()` raises sanitized `OXUnavailableError` for non-available state.

Pass `service().audit` into `OXReviewService` so OX summary operations share the existing Byte-MCP audit file without duplicating audit infrastructure.

- [ ] **Step 4: Preserve audit/evidence ordering**

OX evidence `TRANSMISSION_INTENT` remains the pre-network fail-closed provenance boundary. After provider outcome/response evidence is durable, append a normal Byte-MCP audit summary (`action`, review ID, phase, manifest hash, outcome) containing no source/provider payload/key. If this post-provider audit write fails, return `AuditError` while preserving the durable OX evidence; never claim the external action did not happen.

- [ ] **Step 5: GREEN and commit**

```bash
python -m compileall -q src tests
ruff check .
pytest tests/test_server.py tests/ox/test_runtime.py tests/ox/test_mcp_surface.py -v
pytest -q
pip check
git add src/byte_mcp/ox/runtime.py src/byte_mcp/server.py tests/test_server.py tests/ox/test_runtime.py tests/ox/test_mcp_surface.py
git commit -m "feat: expose OX validation MCP tools"
```

---

### Task 9: Adversarial security gate, docs, CI, and live-canary readiness

**Files:**
- Create: `tests/ox/test_security_invariants.py`
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Create: `docs/OX-VALIDATION.md`
- Modify: `CHANGELOG.md`
- Modify: `config/ox-repositories.example.json` only if implemented paths differ from the planned paths.

- [ ] **Step 1: Write adversarial RED tests before final hardening**

With a network client that increments a counter and fails if reached, parameterize: unknown repo, non-exact commit, missing subsystem, missing mandatory verification, oversized bundle, evidence-root overlap, manifest mismatch, approval attempting scope redefinition, duplicate concurrent approval, unapproved retry, unapproved revalidation, continuation attachment/scope attempt, and retry after `OUTCOME_UNKNOWN` without renewed approval. Every forbidden case leaves network count `0`.

Recursively scan temporary evidence plus serialized MCP returns and assert a sentinel gateway secret never appears.

- [ ] **Step 2: Repair every mechanizable RED finding and run focused GREEN**

```bash
pytest tests/ox/test_security_invariants.py -v
```

No mechanizable security bypass is accepted as documentation-only.

- [ ] **Step 3: Write operator documentation**

`docs/OX-VALIDATION.md` must document: copy example registry to ignored `config/ox-repositories.local.json`; use absolute local repo paths; keep key only in environment; restart Byte-MCP to inherit it; prepare then inspect digest/count/bytes; obtain Nolan approval before approve/retry; continuation replay semantics; `OUTCOME_UNKNOWN`; evidence-root location; disabled/misconfigured behavior; fixed Vercel -> Z.AI route; no execution; and Vercel/Z.AI as external processors.

Update README with four tools/two-phase flow, SECURITY with outbound trust boundary and single-process/no-retry/no-fallback constraints, and CHANGELOG under Unreleased.

- [ ] **Step 4: Run full deterministic gate**

```bash
python -m compileall -q src tests
ruff check .
pytest -q
pip check
```

Expected: all zero exits; no real provider call.

- [ ] **Step 5: Commit and verify exact-head CI on Windows and Ubuntu**

```bash
git add tests/ox/test_security_invariants.py README.md docs/SECURITY.md docs/OX-VALIDATION.md CHANGELOG.md config/ox-repositories.example.json
git commit -m "docs: finalize OX validation security and operations"
```

Verify GitHub Actions for this exact head, not an older run. Both OS jobs must pass install, compile, lint, tests, and dependency check.

- [ ] **Step 6: Credential/history hygiene**

Search the implementation branch/history for `AI_GATEWAY_API_KEY` and sentinel test secrets. Confirm no real credential/evidence is committed and evidence root is outside all reviewed repos.

---

### Task 10: Live canary, dogfood review, remediation, and final acceptance

**Files:**
- No production changes merely to run the canary.
- Modify production/tests/docs only when justified by verified live behavior or confirmed OX findings.

- [ ] **Step 1: Review current Vercel/Z.AI data-handling terms before private repository transmission**

The first live canary remains deliberately non-sensitive regardless.

- [ ] **Step 2: Create a tiny separate non-sensitive local Git canary repo and allowlist it**

Use a committed trivial source/test pair, alias `ox-canary`, and a deterministic subsystem containing both. Keep credentials out of the repo.

- [ ] **Step 3: Prepare canary and inspect zero-transmission proposal**

Call `ox_review` prepare with exact commit + small verification record. Confirm `transmitted=false`, fixed model/provider, exact manifest digest, artifact count, and bytes.

- [ ] **Step 4: After Nolan approves the exact proposal, transmit once**

Verify one real Vercel request reaches `zai/glm-5.3-flash` with `only=["zai"]`; raw response/evidence and usage are durable; structured findings either validate or fail explicitly without losing raw response.

- [ ] **Step 5: Exercise one continuation and one local adjudication**

Verify message mode makes one provider call with native history and adjudication mode makes zero provider calls.

- [ ] **Step 6: Smoke-test existing Byte-MCP local tools after live OX use**

Run `list_roots`, one allowed `search`, and one allowed `fetch`; behavior/security remains unchanged.

- [ ] **Step 7: Dogfood the committed `byte-mcp/ox-validation` subsystem**

Prepare from exact implementation commit/base. Nolan approves exact manifest before private code transmission. OX reviews it independently.

- [ ] **Step 8: Adjudicate every OX finding against repository evidence**

Record `CONFIRMED`, `DISPROVED`, or `DEFERRED/UNRESOLVED` with concise evidence rationale. Failure to reproduce alone is not disproof.

- [ ] **Step 9: Repair every confirmed defect using RED -> GREEN TDD, then full gate**

```bash
python -m compileall -q src tests
ruff check .
pytest -q
pip check
```

Commit remediation only after GREEN.

- [ ] **Step 10: Prepare/approve blind revalidation, then targeted completeness**

Use the exact remediation commit. Nolan approves the new manifest. Blind pass uses fresh OX context; targeted pass uses only the already-approved remediation bundle plus selected finding/adjudication evidence.

- [ ] **Step 11: Verify final exact-head Windows/Ubuntu CI and issue Byte technical recommendation**

V1 is complete only after final deterministic/CI evidence, OX revalidation, Byte adjudication, and Nolan final acceptance.

---

## Self-review result

- Spec Sections 1–23 map to Tasks 1–10.
- Runtime construction occurs only after registry, evidence, client, protocol, and service implementations exist; no forward service dependency remains in Task 1.
- Bundle tests contain no network/client dependency.
- Initial-review, continuation, and revalidation retry paths are explicit within the same four MCP tools and require renewed approval when repository context can be resent.
- Tool signatures cannot redefine a prepared bundle during approval/retry.
- `FileService` remains unchanged except for sharing its existing `AuditLog` instance at server orchestration time.
- No task adds provider abstraction, repository execution, arbitrary file selection, streaming, auto-retry, background workers, or a database.
- Real credits are touched only after deterministic and exact-head CI gates are green.
