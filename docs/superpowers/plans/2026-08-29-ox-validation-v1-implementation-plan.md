# Byte-MCP OX Validation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated OX / GLM-5.3-Flash external-validation capability to the existing Byte-MCP server, with deterministic committed-state review bundles, digest-bound human approval, append-only evidence, fixed Z.AI-only Vercel routing, multi-turn review/adjudication, and blind/targeted revalidation.

**Architecture:** Keep the existing `FileService` and local MCP tools intact. Add an isolated `byte_mcp.ox` package with an optional runtime lifecycle, immutable Git-object reader, deterministic bundle builder, append-only evidence store, narrow HTTP client, and one orchestration service exposed through exactly four MCP tools. OX uses Vercel AI Gateway only as transport to fixed `zai/glm-5.3-flash`, with `providerOptions.gateway.only=["zai"]` and no fallback, retries, streaming, execution, or repository mutation.

**Tech Stack:** Python 3.12; FastMCP from `mcp[cli]==1.28.1`; `dulwich>=1.2.13,<2` for read-only Git-object access; stable `httpx>=0.28.1,<1` for direct Vercel REST calls; stdlib dataclasses/JSON/SHA-256/threading/filesystem primitives; pytest; ruff; GitHub Actions on Windows and Ubuntu.

**Spec:** `docs/superpowers/specs/2026-08-29-ox-integration-design.md`

## Global Constraints

- OX remains part of the existing Byte-MCP server; do not create another server, tunnel, or repository.
- The implementation is intentionally OX-specific. Do not add provider/model abstraction or a generic AI gateway layer.
- Fixed provider route: `https://ai-gateway.vercel.sh/v1/chat/completions`, model `zai/glm-5.3-flash`, `providerOptions.gateway.only=["zai"]`.
- `AI_GATEWAY_API_KEY` is environment-only and must never be committed, persisted, logged, returned, or interpolated into exceptions.
- Existing `list_roots`, `list_directory`, `search`, and `fetch` behavior must remain functional when OX is disabled or misconfigured.
- Reviews target allowlisted local Git repositories and exact committed SHAs only; public OX tools never accept arbitrary filesystem paths.
- No supported OX path may execute repository code, Git subprocesses, tests, builds, shells, package managers, or arbitrary subprocesses.
- Preparation never performs a network call. Repository transmission requires a second digest-bound approved invocation.
- New repository content cannot be added through `ox_continue`; scope expansion requires a new prepared/approved bundle.
- Evidence is stored outside every reviewed repository and canonical history is append-only.
- V1 is single-process for a given evidence root; per-review mutation/state transitions and ID allocation must be concurrency-safe in-process.
- Each outbound operation yields at most one provider response and there are no automatic retries.
- Automated tests never use Nolan's real API key or real Vercel/Z.AI credits.
- Provider responses are not reported as successfully evidenced until required response/attempt evidence has been durably persisted.
- Existing CI compile, lint, test, and dependency-integrity gates must remain green on Windows and Ubuntu.

## Locked file structure

Create these focused OX modules:

- `src/byte_mcp/ox/__init__.py` — package exports only.
- `src/byte_mcp/ox/models.py` — enums/dataclasses and serialization-safe domain contracts.
- `src/byte_mcp/ox/settings.py` — OX-only environment/config loading and platform evidence-root defaults.
- `src/byte_mcp/ox/runtime.py` — optional `AVAILABLE` / `DISABLED` / `MISCONFIGURED` lifecycle.
- `src/byte_mcp/ox/repositories.py` — repository registry parsing plus read-only Dulwich commit/tree/blob/diff access.
- `src/byte_mcp/ox/bundles.py` — deterministic subsystem expansion, verification normalization, packet/manifest hashing, and size enforcement.
- `src/byte_mcp/ox/evidence.py` — append-only JSON/JSONL evidence, atomic immutable writes, IDs, locks, transitions, threads, responses, findings, adjudication.
- `src/byte_mcp/ox/protocol.py` — OX system prompts, provider-native messages, strict finding schema parsing/validation, blind/targeted message construction.
- `src/byte_mcp/ox/client.py` — the only HTTP-capable module; fixed Vercel/Z.AI request shape and error/outcome mapping.
- `src/byte_mcp/ox/service.py` — high-level `prepare/transmit/continue/adjudicate/revalidate/get` orchestration.

Create OX tests under `tests/ox/`, plus shared deterministic Git fixtures in `tests/ox/helpers.py`. Do not fold OX implementation into existing `src/byte_mcp/service.py`.

---

### Task 1: OX domain contracts, settings, optional runtime, and dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `src/byte_mcp/errors.py`
- Create: `src/byte_mcp/ox/__init__.py`
- Create: `src/byte_mcp/ox/models.py`
- Create: `src/byte_mcp/ox/settings.py`
- Create: `src/byte_mcp/ox/runtime.py`
- Create: `config/ox-repositories.example.json`
- Create: `tests/ox/__init__.py`
- Create: `tests/ox/test_settings_runtime.py`
- Create: `tests/ox/test_models.py`

**Interfaces:**
- Produces: `OXSettings.load(repo_root: Path) -> OXSettings`
- Produces: `OXRuntime.initialize(repo_root: Path) -> OXRuntime`
- Produces: `OXRuntime.require_service() -> OXReviewService` via a deferred import/factory so runtime construction does not create an import cycle.
- Produces enums: `OXAvailability`, `ReviewState`, `AttemptOutcome`, `FindingStatus`.
- Produces immutable dataclasses used later: `VerificationRecord`, `Finding`, `AdjudicationEvent`, `ProviderUsage`, `ProviderResult`.
- Produces OX-domain exceptions as subclasses of `ByteMCPError`.

- [ ] **Step 1: Add RED tests for settings separation and availability states**

Create tests that explicitly cover absent credential, valid local configuration, malformed repository config, evidence-root-inside-reviewed-repo rejection, and secret-safe representation:

```python
from pathlib import Path

from byte_mcp.ox.runtime import OXAvailability, OXRuntime
from byte_mcp.ox.settings import OXSettings


def test_missing_gateway_key_disables_only_ox(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    settings = OXSettings.load(tmp_path)
    runtime = OXRuntime.initialize(settings)
    assert runtime.availability is OXAvailability.DISABLED
    assert runtime.service is None


def test_settings_repr_never_contains_gateway_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "SENTINEL-SECRET")
    settings = OXSettings.load(tmp_path)
    assert "SENTINEL-SECRET" not in repr(settings)
```

Add a test that `config/ox-repositories.local.json` is ignored by Git and the example file is committed/readable.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
pytest tests/ox/test_settings_runtime.py tests/ox/test_models.py -v
```

Expected: collection/import failures because `byte_mcp.ox` contracts do not exist yet.

- [ ] **Step 3: Add direct dependencies and domain errors**

Update runtime dependencies to include:

```toml
"dulwich>=1.2.13,<2",
"httpx>=0.28.1,<1",
```

Add `config/ox-repositories.local.json` to `.gitignore`.

Add these errors in `src/byte_mcp/errors.py`, all directly subclassing `ByteMCPError` unless a more specific OX base is useful without changing catch semantics:

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

- [ ] **Step 4: Implement exact OX settings defaults**

`OXSettings` is a frozen slotted dataclass containing:

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

Load `BYTE_MCP_OX_REPOSITORIES_FILE` with default `config/ox-repositories.local.json`. Load `BYTE_MCP_OX_EVIDENCE_DIR` if explicitly configured; otherwise use `%LOCALAPPDATA%/Byte-MCP/ox` on Windows, `$XDG_DATA_HOME/byte-mcp/ox` when set on Unix, or `~/.local/share/byte-mcp/ox` otherwise. `AI_GATEWAY_API_KEY` may be absent; strip it and treat empty as absent. Bound `BYTE_MCP_OX_MAX_BUNDLE_BYTES` to `16_384..16_000_000` and `BYTE_MCP_OX_MAX_OUTPUT_TOKENS` to `1_024..65_536`.

Override `__repr__` so it reports credential presence only, never value.

- [ ] **Step 5: Implement runtime state and model contracts**

Use:

```python
class OXAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISCONFIGURED = "misconfigured"

class ReviewState(StrEnum):
    PREPARED = "prepared"
    TRANSMITTING = "transmitting"
    REVIEWED = "reviewed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    REVALIDATION_PREPARED = "revalidation_prepared"
    REVALIDATION_TRANSMITTING = "revalidation_transmitting"
    BLIND_REVALIDATED = "blind_revalidated"
    REVALIDATED = "revalidated"

class AttemptOutcome(StrEnum):
    NOT_SENT = "not_sent"
    REJECTED = "rejected"
    COMPLETED = "completed"
    OUTCOME_UNKNOWN = "outcome_unknown"
```

`OXRuntime.initialize(settings)` must return `DISABLED` when the key is absent; return `MISCONFIGURED` with a sanitized reason when local OX config cannot be validated; and return `AVAILABLE` with a constructed service only when key/config/evidence boundaries pass. Do not perform network I/O in initialization.

- [ ] **Step 6: Add a committed repository-config example**

`config/ox-repositories.example.json` must use an absolute-path placeholder and define an initial `byte-mcp` / `ox-validation` subsystem using directory roots rather than hand-selected review-time files:

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
          "boundary_files": [
            "src/byte_mcp/server.py",
            "src/byte_mcp/errors.py",
            "src/byte_mcp/settings.py"
          ],
          "context_files": [
            "pyproject.toml",
            "docs/superpowers/specs/2026-08-29-ox-integration-design.md"
          ]
        }
      }
    }
  }
}
```

- [ ] **Step 7: Run Task 1 GREEN gate**

Run:

```bash
python -m compileall -q src tests
ruff check .
pytest tests/ox/test_settings_runtime.py tests/ox/test_models.py -v
pip check
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 1**

```bash
git add pyproject.toml .gitignore config/ox-repositories.example.json src/byte_mcp/errors.py src/byte_mcp/ox tests/ox
git commit -m "feat: add OX validation foundation"
```

---

### Task 2: Immutable Git repository reader and deterministic subsystem registry

**Files:**
- Create: `src/byte_mcp/ox/repositories.py`
- Create: `tests/ox/helpers.py`
- Create: `tests/ox/test_repositories.py`

**Interfaces:**
- Consumes: `OXSettings`, `OXRepositoryError`, `OXScopeError`.
- Produces: `RepositoryRegistry.load(path: Path) -> RepositoryRegistry`.
- Produces: `RepositoryRegistry.get(alias: str) -> RepositoryDefinition`.
- Produces: `GitRepository.open(definition: RepositoryDefinition) -> GitRepository`.
- Produces: `resolve_commit(commit: str) -> bytes`, `read_file(commit: str, logical_path: str) -> bytes`, `iter_root_files(commit: str, root: str) -> tuple[GitArtifact, ...]`, `repository_tree(commit: str) -> tuple[TreeEntryRecord, ...]`, `diff(base_commit: str, target_commit: str) -> bytes`.

- [ ] **Step 1: Write RED tests using an in-process Dulwich fixture**

`tests/ox/helpers.py` must create a temporary repository without shelling out:

```python
from dulwich.objects import Blob
from dulwich.porcelain import add, commit, init


def make_repo(tmp_path, files: dict[str, str]) -> tuple[Path, str]:
    repo_path = tmp_path / "repo"
    init(repo_path)
    for relative, content in files.items():
        path = repo_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    add(repo_path)
    sha = commit(repo_path, message=b"fixture", author=b"Test <test@example.com>")
    return repo_path, sha.decode("ascii")
```

Tests must prove: unknown alias fails; non-Git path fails; exact commit reads are independent of later working-tree edits; directory roots recurse deterministically in POSIX path order; a missing required root fails; symlink/submodule entries in required scope are rejected rather than followed/omitted; and base-to-target diff is generated from Git trees, not working tree.

- [ ] **Step 2: Run repository tests and verify RED**

```bash
pytest tests/ox/test_repositories.py -v
```

Expected: import/missing implementation failures.

- [ ] **Step 3: Implement registry parsing and validation**

Define frozen dataclasses:

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

Require repository aliases and subsystem IDs to match `^[a-z][a-z0-9_-]{0,63}$`. Require absolute repository paths. Resolve them strictly and reject duplicates. Canonicalize logical Git paths to forward-slash relative paths; reject empty paths, `..`, absolute paths, backslash traversal, NUL, and drive-qualified input.

- [ ] **Step 4: Implement immutable Dulwich reads**

Open repositories with `dulwich.repo.Repo`. Resolve only exact 40-hex commit IDs for V1; reject branches/tags/abbreviations at the public service boundary. Fetch `Commit.tree`, then walk blobs through `repo.object_store.iter_tree_contents(tree_id)`.

Treat only regular-file modes `0o100644` and `0o100755` as review artifacts. Reject symlink mode `0o120000` and submodule mode `0o160000` when a required root/file matches them. Never resolve their payload into the filesystem.

Generate diffs with `dulwich.patch.write_tree_diff(BytesIO(), repo.object_store, base.tree, target.tree, diff_binary=False)` and UTF-8 decode with replacement solely for the transmitted textual diff artifact; preserve the raw bytes/hash independently.

- [ ] **Step 5: Run Task 2 GREEN gate**

```bash
ruff check src/byte_mcp/ox/repositories.py tests/ox/test_repositories.py tests/ox/helpers.py
pytest tests/ox/test_repositories.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/byte_mcp/ox/repositories.py tests/ox/helpers.py tests/ox/test_repositories.py
git commit -m "feat: add immutable OX repository reader"
```

---

### Task 3: Deterministic review bundles, verification evidence, and manifest binding

**Files:**
- Create: `src/byte_mcp/ox/bundles.py`
- Create: `tests/ox/test_bundles.py`

**Interfaces:**
- Consumes: `GitRepository`, `SubsystemDefinition`, `VerificationRecord`, `OXSettings.max_bundle_bytes`.
- Produces: `BundleArtifact`, `ReviewManifest`, `PreparedBundle` dataclasses.
- Produces: `BundleBuilder.prepare(repository_alias, subsystem_id, base_commit, target_commit, objective, verification) -> PreparedBundle`.
- Produces: canonical `sha256_json(value: object) -> str` using UTF-8, `ensure_ascii=False`, `sort_keys=True`, separators `(",", ":")`.

- [ ] **Step 1: Write RED tests for deterministic completeness and hashing**

Tests must prove that source/test roots recursively include every regular blob, boundary/context files are mandatory, duplicate paths appearing in multiple categories are represented once with all categories or a deterministic precedence rule, ordering is stable, target commit contents ignore dirty working-tree edits, subsystem-definition hash changes when the definition changes, verification stdout/stderr hashes are stable, exact same inputs yield exact same manifest hash, and `max_bundle_bytes + 1` fails without dropping any artifact.

Use an explicit size assertion:

```python
with pytest.raises(OXBundleError, match="exceeds"):
    builder.prepare(...)
assert fake_client.calls == []
```

The fake-client assertion is repeated later at service level; bundle construction itself must have no client dependency.

- [ ] **Step 2: Run bundle tests and verify RED**

```bash
pytest tests/ox/test_bundles.py -v
```

- [ ] **Step 3: Implement canonical artifacts and manifest**

Use immutable structures equivalent to:

```python
@dataclass(frozen=True, slots=True)
class BundleArtifact:
    logical_path: str
    categories: tuple[str, ...]
    content: bytes
    byte_length: int
    sha256: str

@dataclass(frozen=True, slots=True)
class ReviewManifest:
    protocol_version: str
    repository_alias: str
    subsystem_id: str
    subsystem_version: int
    subsystem_sha256: str
    base_commit: str | None
    target_commit: str
    artifacts: tuple[ManifestEntry, ...]
    verification: tuple[VerificationManifestEntry, ...]
    total_bytes: int
    manifest_sha256: str
```

Use protocol version `ox-review-v1`. Compute the manifest digest from the canonical manifest payload with `manifest_sha256` omitted, then return a new immutable manifest containing that digest.

- [ ] **Step 4: Implement deterministic packet content**

The prepared packet must contain repository identity, exact base/target commits, subsystem definition, bounded deterministic tree listing, exact diff artifact when base exists, all scoped source/tests/boundary/context files, verification evidence, and manifest. Decode source text for provider payload with UTF-8 strict first and UTF-8 replacement only as an explicitly marked encoding fallback; never change the raw SHA-256.

No summarization, ranking, fuzzy selection, truncation, or provider-aware pruning is allowed.

- [ ] **Step 5: Run Task 3 GREEN gate**

```bash
ruff check src/byte_mcp/ox/bundles.py tests/ox/test_bundles.py
pytest tests/ox/test_repositories.py tests/ox/test_bundles.py -v
```

- [ ] **Step 6: Commit Task 3**

```bash
git add src/byte_mcp/ox/bundles.py tests/ox/test_bundles.py
git commit -m "feat: build deterministic OX review bundles"
```

---

### Task 4: Append-only evidence store, durable transitions, and duplicate-approval protection

**Files:**
- Create: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_evidence.py`

**Interfaces:**
- Consumes: prepared bundles/models and `OXEvidenceError`.
- Produces: `EvidenceStore(root: Path)`.
- Produces: `allocate_review_id() -> str`, `persist_prepared_review(...)`, `claim_transmission(review_id, manifest_sha256) -> ProviderAttempt`, `record_attempt_outcome(...)`, `append_thread_message(...)`, `persist_provider_response(...)`, `persist_findings(...)`, `append_adjudication(...)`, `allocate_revalidation_id(review_id) -> str`, `get_review(...) -> ReviewSnapshot`.

- [ ] **Step 1: Write RED evidence tests**

Cover exact IDs (`OX-000001`, `OX-000001-F001`, `OX-000001-RV001`), atomic immutable JSON creation, fsync-backed JSONL append, malformed/torn trailing JSONL tolerance on reads without silently treating the corrupt record as valid, evidence-root containment, append-only provider messages, separate adjudication stream, and reconstruction of review state from immutable identity plus events.

Add a concurrency test with two threads racing `claim_transmission` against one prepared review. Exactly one must receive an attempt and the other must receive `OXApprovalError`; a fake network counter stays at one when service-level coverage is added.

- [ ] **Step 2: Run evidence tests and verify RED**

```bash
pytest tests/ox/test_evidence.py -v
```

- [ ] **Step 3: Implement atomic immutable writes**

Use a same-directory temporary file, `flush()`, `os.fsync()`, then `os.replace()` for immutable JSON materialization. Reject overwrite attempts for canonical immutable files such as `review.json`, prepared bundle artifacts, and `manifest.json`.

Use JSON serialization with `ensure_ascii=False`, `sort_keys=True`, and `default=str`; wrap filesystem/serialization failures as `OXEvidenceError` with sanitized messages.

- [ ] **Step 4: Implement append-only lifecycle events and per-review locking**

Maintain one allocation lock and a `dict[str, threading.Lock]` protected by a lock for review-level mutation. Allocate IDs by scanning existing review directories under the allocation lock so restart preserves monotonic identity.

Represent transition events explicitly, for example:

```json
{"event":"TRANSMISSION_INTENT","attempt_id":"OX-000001-A001","manifest_sha256":"...","state":"transmitting","timestamp_utc":"..."}
```

`claim_transmission()` must acquire the review lock, reconstruct current state, require exactly `PREPARED`, verify the expected manifest digest, allocate/persist the attempt identity and transmission-intent event, and only then return the attempt object. This method is the concurrency barrier used by the service before calling the client.

- [ ] **Step 5: Run Task 4 GREEN gate**

```bash
ruff check src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
pytest tests/ox/test_evidence.py -v
```

- [ ] **Step 6: Commit Task 4**

```bash
git add src/byte_mcp/ox/evidence.py tests/ox/test_evidence.py
git commit -m "feat: add append-only OX evidence store"
```

---

### Task 5: Fixed Vercel/Z.AI OX client and transport outcome semantics

**Files:**
- Create: `src/byte_mcp/ox/client.py`
- Create: `tests/ox/test_client.py`

**Interfaces:**
- Consumes: `OXSettings`, `ProviderResult`, OX provider errors.
- Produces: `OXClient.complete(messages: Sequence[Mapping[str, object]], *, json_mode: bool, attempt_id: str) -> ProviderResult`.
- Network endpoint is hardcoded from settings default but not user-selectable through MCP.

- [ ] **Step 1: Write RED request-shape tests with `httpx.MockTransport`**

Capture the outbound request and assert:

```python
assert body["model"] == "zai/glm-5.3-flash"
assert body["stream"] is False
assert body["max_tokens"] == 16_384
assert body["providerOptions"] == {"gateway": {"only": ["zai"]}}
```

For formal review calls assert:

```python
assert body["response_format"] == {"type": "json_object"}
```

Also assert Authorization is present on the actual HTTP request but the sentinel secret never appears in `repr(client)`, returned `ProviderResult`, raised exception strings, safe provider metadata, or any serialization helper.

- [ ] **Step 2: Add RED transport/error classification tests**

Map HTTP 401 to `OXAuthenticationError`, 403 to `OXPermissionError`, 429 to `OXRateLimitError` unless the safe provider code/body unambiguously identifies quota (then `OXQuotaError`), context-limit responses to `OXContextLimitError`, other 4xx to `OXRequestError`, and 5xx to `OXProviderUnavailableError`.

Classify `httpx.ConnectError`, `ConnectTimeout`, and `PoolTimeout` as `NOT_SENT`. Classify `WriteTimeout`, `ReadTimeout`, `ReadError`, `WriteError`, and `RemoteProtocolError` as `OUTCOME_UNKNOWN` because the request may have reached the gateway/provider. Do not retry any class automatically.

- [ ] **Step 3: Run client tests and verify RED**

```bash
pytest tests/ox/test_client.py -v
```

- [ ] **Step 4: Implement the narrow synchronous client**

Use one `httpx.Client` with explicit limits:

```python
httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
```

POST only to `https://ai-gateway.vercel.sh/v1/chat/completions`. Build headers inside `complete()` immediately before `post()`. Never persist headers. Use one request only and `stream=false`.

Extract the first assistant choice content, safe response ID/model/usage fields, and preserve the raw JSON response as data returned to the service for evidence persistence. Reject structurally invalid success responses as `OXProtocolError`.

- [ ] **Step 5: Run Task 5 GREEN gate**

```bash
ruff check src/byte_mcp/ox/client.py tests/ox/test_client.py
pytest tests/ox/test_client.py -v
```

- [ ] **Step 6: Commit Task 5**

```bash
git add src/byte_mcp/ox/client.py tests/ox/test_client.py
git commit -m "feat: add fixed OX gateway client"
```

---

### Task 6: OX protocol, strict findings, and new-review prepare/approve lifecycle

**Files:**
- Create: `src/byte_mcp/ox/protocol.py`
- Create: `src/byte_mcp/ox/service.py`
- Create: `tests/ox/test_protocol.py`
- Create: `tests/ox/test_review_service.py`

**Interfaces:**
- Consumes: `BundleBuilder`, `EvidenceStore`, `OXClient`, models/errors.
- Produces: `build_initial_messages(bundle: PreparedBundle) -> tuple[dict[str, object], ...]`.
- Produces: `parse_findings(content: str, review_id: str) -> tuple[Finding, ...]`.
- Produces: `OXReviewService.prepare_review(...) -> Mapping[str, object]`.
- Produces: `OXReviewService.transmit_review(review_id: str) -> Mapping[str, object]`.

- [ ] **Step 1: Write RED finding-schema tests**

Require top-level JSON object:

```json
{"protocol_version":"ox-findings-v1","findings":[...]}
```

Each finding must contain `category`, `severity`, `confidence`, `location`, `claim`, `evidence`, `reproduction`, `expected_behavior`, `observed_or_predicted_behavior`, `disproof_condition`, and `recommended_investigation`. OX-supplied finding keys may be normalized only into stable local IDs `OX-000001-F001` in deterministic array order; the raw provider content remains untouched in evidence.

Reject missing fields, wrong types, NaN confidence, confidence outside `0..1`, unknown severity, duplicate local IDs, and non-object findings with `OXFindingValidationError`.

- [ ] **Step 2: Write RED service security tests**

Use a `FailIfCalledClient`:

```python
class FailIfCalledClient:
    def complete(self, *args, **kwargs):
        raise AssertionError("network boundary reached")
```

Prove `prepare_review()` persists a complete PREPARED record and never calls the client. Prove invalid repo, invalid commit, missing verification, oversized bundle, and evidence persistence failure all stop before the network boundary.

Use a recording fake client for approval tests. Prove exact manifest is sent once, wrong digest/state cannot send, `approve` cannot redefine any bundle-producing fields because transmission takes only `review_id`, and two concurrent transmit calls produce exactly one client call.

- [ ] **Step 3: Run protocol/service tests and verify RED**

```bash
pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -v
```

- [ ] **Step 4: Implement the validator mandate and packet message**

The system message must state that OX is an independent external code validator, not an implementation authority; findings must be falsifiable; absence of evidence should produce uncertainty rather than invention; each finding must include a disproof condition; and output must satisfy `ox-findings-v1` JSON.

The initial user message serializes only the already-prepared packet and review objective. Do not add unstored repository content during message construction.

- [ ] **Step 5: Implement prepare and transmit ordering**

`prepare_review()` must validate supplied verification entries, resolve immutable Git state, build/persist the full bundle and manifest, then return a bounded proposal containing `review_id`, repository, subsystem, base/target commits, objective, artifact count, total bytes, `manifest_sha256`, model/provider, and `transmitted=False`.

`transmit_review(review_id)` must:

1. load the persisted prepared object;
2. recompute/verify its manifest digest and target commit identity;
3. atomically call `claim_transmission()` to persist `TRANSMISSION_INTENT` before network access;
4. call `OXClient.complete(..., json_mode=True)` exactly once;
5. persist raw provider response before parsing findings;
6. append exact assistant message;
7. parse/persist findings or append `FINDINGS_INVALID` then raise `OXFindingValidationError` while leaving the raw response recoverable;
8. record usage/outcome and review lifecycle event;
9. return only after required evidence is durable.

No hidden retry is allowed.

- [ ] **Step 6: Run Task 6 GREEN gate**

```bash
ruff check src/byte_mcp/ox/protocol.py src/byte_mcp/ox/service.py tests/ox/test_protocol.py tests/ox/test_review_service.py
pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -v
```

- [ ] **Step 7: Commit Task 6**

```bash
git add src/byte_mcp/ox/protocol.py src/byte_mcp/ox/service.py tests/ox/test_protocol.py tests/ox/test_review_service.py
git commit -m "feat: add OX review protocol"
```

---

### Task 7: Continuation, local adjudication, blind revalidation, and targeted completeness

**Files:**
- Modify: `src/byte_mcp/ox/protocol.py`
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/ox/evidence.py`
- Create: `tests/ox/test_review_followup.py`

**Interfaces:**
- Produces: `OXReviewService.continue_message(review_id: str, message: str) -> Mapping[str, object]`.
- Produces: `OXReviewService.adjudicate(review_id: str, events: Sequence[Mapping[str, object]]) -> Mapping[str, object]`.
- Produces: `OXReviewService.prepare_revalidation(review_id, target_commit, base_commit, verification) -> Mapping[str, object]`.
- Produces: `OXReviewService.transmit_blind_revalidation(revalidation_id: str) -> Mapping[str, object]`.
- Produces: `OXReviewService.run_targeted_revalidation(revalidation_id: str, finding_ids: Sequence[str]) -> Mapping[str, object]`.

- [ ] **Step 1: Write RED continuation tests**

Prove provider-native role order is preserved; one `continue_message` call makes exactly one client call; replay may include the original already-approved bundle but cannot access repository reader/bundle builder for new artifacts; empty messages fail; and an `OUTCOME_UNKNOWN` retry is not silently sent.

- [ ] **Step 2: Write RED adjudication tests**

Accept only known finding IDs and valid `FindingStatus` transitions. Require each event to contain `finding_id`, `status`, `evidence`, and `reasoning_summary`; allow `remediation_commit` when relevant. Adjudication performs zero network calls and appends rather than rewriting prior events/OX output.

- [ ] **Step 3: Write RED revalidation tests**

Prove the first revalidation invocation prepares against a new exact commit with zero network calls; approval transmits the exact new manifest; blind revalidation messages contain no original finding text/adjudication/remediation narrative; targeted completeness is unavailable before a successful blind pass; targeted completeness may add only selected original finding/adjudication metadata plus the same already-approved remediation bundle; and adding a repository path outside that bundle is impossible through the interface.

- [ ] **Step 4: Run follow-up tests and verify RED**

```bash
pytest tests/ox/test_review_followup.py -v
```

- [ ] **Step 5: Implement continuation and adjudication**

Build continuation messages only from persisted thread history plus the new Byte text message. Never call `BundleBuilder` from `continue_message()`.

For adjudication, validate finding existence and state transitions, append `AdjudicationEvent`, and return updated local status with `provider_called=False`.

- [ ] **Step 6: Implement revalidation flows**

Blind preparation reuses the original repository/subsystem definition but requires caller-supplied exact remediation target/base commit and fresh verification evidence. It creates `OX-<review>-RVnnn` evidence and a new manifest requiring human approval.

Blind transmission creates a fresh thread beginning with the validator mandate and remediation bundle only. Targeted completeness is a later explicit provider call using the successful blind revalidation thread/bundle plus selected original finding records and Byte adjudication/remediation evidence; it cannot add new repository artifacts.

- [ ] **Step 7: Run Task 7 GREEN gate**

```bash
ruff check src/byte_mcp/ox tests/ox/test_review_followup.py
pytest tests/ox -v
```

- [ ] **Step 8: Commit Task 7**

```bash
git add src/byte_mcp/ox tests/ox/test_review_followup.py
git commit -m "feat: add OX review follow-up and revalidation"
```

---

### Task 8: Four MCP tools, optional lifecycle integration, truthful annotations, and audit boundary

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/ox/test_mcp_surface.py`

**Interfaces:**
- Existing tools unchanged: `list_roots`, `list_directory`, `search`, `fetch`.
- New public tools exactly: `ox_review`, `ox_continue`, `ox_revalidate`, `ox_get_review`.
- `ox_runtime() -> OXRuntime` is independent from existing `service() -> FileService`.

- [ ] **Step 1: Write RED startup-isolation tests**

Extend `tests/test_server.py` so `main()` still constructs required `FileService` before bind, initializes OX runtime without making a provider call, and binds even when OX is `DISABLED` or `MISCONFIGURED`.

Prove existing local tools still call `FileService` when `AI_GATEWAY_API_KEY` is absent.

- [ ] **Step 2: Write RED MCP surface/annotation tests**

Assert the registered OX tool names are exactly four. Use a static external-action annotation:

```python
OX_EXTERNAL_ACTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
```

Use existing `READ_ONLY` for `ox_get_review`. Because `ox_continue` can send externally in message mode, its static annotation must use `OX_EXTERNAL_ACTION` even though adjudication mode itself is local-only.

- [ ] **Step 3: Define exact MCP signatures**

Use flat, phase-safe signatures:

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
) -> dict[str, Any]: ...


def ox_continue(
    review_id: str,
    mode: str = "message",
    message: str | None = None,
    adjudications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]: ...


def ox_revalidate(
    review_id: str,
    revalidation_id: str | None = None,
    target_commit: str | None = None,
    base_commit: str | None = None,
    verification: list[dict[str, Any]] | None = None,
    approve: bool = False,
    targeted: bool = False,
    finding_ids: list[str] | None = None,
) -> dict[str, Any]: ...


def ox_get_review(
    review_id: str,
    view: str = "summary",
) -> dict[str, Any]: ...
```

Validation rules are strict: `ox_review` with `review_id` accepts no repository/bundle fields; `approve=True` requires an existing prepared ID; `ox_continue` modes are exactly `message` or `adjudicate` and their fields are mutually exclusive; `ox_revalidate` preparation, blind approval, and targeted mode are mutually exclusive; `ox_get_review` view is one of `summary`, `findings`, `thread`, `manifest`, `adjudication`, `attempts`, `revalidation`.

- [ ] **Step 4: Integrate normal Byte-MCP audit events**

OX operations write summary audit records only, never source/provider payloads or secrets. Examples:

```python
audit.record("ox_review", review_id=review_id, phase="prepare", manifest_sha256=digest)
audit.record("ox_review", review_id=review_id, phase="transmit", outcome="allowed")
```

If required Byte-MCP audit persistence fails before an outbound action, fail closed before network transmission. For post-provider audit failure, preserve the already-durable OX response/evidence and return `AuditError` without falsely claiming the provider action did not occur.

- [ ] **Step 5: Run Task 8 GREEN gate**

```bash
python -m compileall -q src tests
ruff check .
pytest tests/test_server.py tests/ox/test_mcp_surface.py -v
pytest -q
pip check
```

Expected: the full existing and OX suites pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add src/byte_mcp/server.py tests/test_server.py tests/ox/test_mcp_surface.py
git commit -m "feat: expose OX validation MCP tools"
```

---

### Task 9: Adversarial security regression, documentation, CI, and live-canary readiness

**Files:**
- Create: `tests/ox/test_security_invariants.py`
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Create: `docs/OX-VALIDATION.md`
- Modify: `CHANGELOG.md`
- Modify: `config/ox-repositories.example.json` only if the final implemented file paths differ from the planned paths.

**Interfaces:**
- No new public tool surface.
- Produces operator documentation for local OX configuration, approval lifecycle, evidence location, live canary, and dogfood review.

- [ ] **Step 1: Write adversarial RED tests before final hardening**

Use a client whose `complete()` increments a counter and fails if called unexpectedly. Parameterize forbidden paths: unknown repository, non-40-hex commit, missing subsystem, missing required evidence, bundle too large, manifest mismatch, approval call that attempts to redefine scope, evidence-root-inside-repository, malformed evidence, duplicate concurrent approval, unapproved revalidation, continuation with attempted attachments, and retry after `OUTCOME_UNKNOWN` without renewed approval. Every case must leave the network count at zero.

Add secret-scanning assertions that recursively read the temporary evidence root and serialized MCP return values and verify a sentinel `AI_GATEWAY_API_KEY` value is absent.

- [ ] **Step 2: Run adversarial tests and repair any RED findings**

```bash
pytest tests/ox/test_security_invariants.py -v
```

Expected after hardening: all pass; no safety bypass is accepted as a documentation-only issue if it can be mechanized.

- [ ] **Step 3: Document the operator contract**

`docs/OX-VALIDATION.md` must contain these concrete setup steps:

1. copy `config/ox-repositories.example.json` to ignored `config/ox-repositories.local.json` and replace the repository path with the absolute local path;
2. ensure `AI_GATEWAY_API_KEY` exists as a user/process environment variable and never place it in the JSON file;
3. restart Byte-MCP so the process inherits the environment variable;
4. call `ox_review` prepare first and inspect `manifest_sha256`/artifact count/bytes;
5. require Nolan's explicit approval before calling approval phase;
6. explain that continuations may replay previously approved context but cannot add repository files;
7. explain `OUTCOME_UNKNOWN` and renewed approval before a repository resend;
8. explain evidence lives outside the repository and how to locate the configured/default evidence root;
9. explain OX-disabled behavior and that existing Byte tools stay functional.

Document fixed model/provider routing and Vercel/Z.AI as external processors. Do not print or demonstrate a real key.

- [ ] **Step 4: Update README, SECURITY, and CHANGELOG**

README lists the four OX tools and their two-phase behavior. `docs/SECURITY.md` records the new outbound trust boundary, no-execution rule, immutable Git-object reads, fail-closed provenance, single-process evidence limitation, no automatic retries/fallback, and external-processing approval requirement. CHANGELOG records the OX integration under Unreleased.

- [ ] **Step 5: Run the full deterministic local gate**

```bash
python -m compileall -q src tests
ruff check .
pytest -q
pip check
```

Expected: every command exits 0. The provider fake/MockTransport is the only network boundary in automated tests.

- [ ] **Step 6: Push exact head and verify GitHub Actions on both OS jobs**

Verify the workflow triggered for the exact implementation head. Confirm Windows and Ubuntu jobs both complete successfully, including install, compile, lint, tests, and dependency check. Do not infer success from an older run.

- [ ] **Step 7: Perform credential/history hygiene before any real call**

Run repository searches for `AI_GATEWAY_API_KEY`, common Vercel key prefixes if documented, and the sentinel secrets used in tests. Confirm no real credential exists in the working tree or committed history introduced by this branch. Confirm evidence paths are ignored/outside the repository.

- [ ] **Step 8: Commit Task 9**

```bash
git add tests/ox/test_security_invariants.py README.md docs/SECURITY.md docs/OX-VALIDATION.md CHANGELOG.md config/ox-repositories.example.json
git commit -m "docs: finalize OX validation security and operations"
```

---

### Task 10: Live non-sensitive canary, dogfood OX review, remediation, and V1 acceptance

**Files:**
- No production file is changed merely to run the canary.
- Modify only files justified by confirmed OX findings during remediation.
- Update: `docs/OX-VALIDATION.md` only if the verified live behavior differs materially from the documented operator flow.

**Interfaces:**
- Uses the real four MCP tools only after Tasks 1–9 and exact-head CI are green.

- [ ] **Step 1: Review current Vercel/Z.AI data-handling terms before private transmission**

Record the current result in the engineering session. The first live canary uses deliberately non-sensitive content even if this review is still pending.

- [ ] **Step 2: Configure a tiny non-sensitive local Git canary repository**

Create a separate local Git repository containing a trivial source file and test file, commit it, and add it to the ignored local OX repository registry under alias `ox-canary`. Define a deterministic subsystem including both files. Do not place credentials in that repository.

- [ ] **Step 3: Prepare the live canary with zero provider calls**

Call `ox_review` for the exact canary commit with a small verification record. Inspect returned repository, commit, artifact count, byte count, fixed model/provider, and `manifest_sha256`. Confirm `transmitted=false`.

- [ ] **Step 4: Obtain Nolan's explicit approval and transmit once**

After Nolan approves the exact canary proposal, call approval phase for that `review_id`. Verify one real request reaches `zai/glm-5.3-flash` through Vercel with Z.AI-only routing, a complete raw response is durably stored, findings validate or fail explicitly without data loss, and usage metadata is recorded.

- [ ] **Step 5: Verify live continuation and local adjudication**

Call one `ox_continue(mode="message")` turn and verify provider-native message continuity. Call one `ox_continue(mode="adjudicate")` event and verify zero provider request occurs for adjudication.

- [ ] **Step 6: Verify existing Byte-MCP local tools still work after live OX use**

Smoke-test `list_roots`, one allowed `search`, and one allowed `fetch`. Confirm OX integration has not changed their security semantics.

- [ ] **Step 7: Commit the OX implementation checkpoint and dogfood `ox-validation`**

Use the exact committed implementation SHA as the OX target and the implementation baseline as base commit. Prepare the `byte-mcp` / `ox-validation` bundle from the local registry. Nolan approves its exact manifest before private repository content is transmitted.

- [ ] **Step 8: Adjudicate every OX finding against live repository evidence**

For each finding, reproduce/check the claim and append one local adjudication status: `CONFIRMED`, `DISPROVED`, or `DEFERRED/UNRESOLVED` with concise evidence rationale. Failure to reproduce alone is not `DISPROVED`.

- [ ] **Step 9: Repair confirmed findings through TDD and rerun the full gate**

For every confirmed defect, first add the smallest regression test that reproduces it, run RED, implement the repair, run focused GREEN, then run:

```bash
python -m compileall -q src tests
ruff check .
pytest -q
pip check
```

Commit the remediation only after the deterministic gate is green.

- [ ] **Step 10: Perform blind then targeted revalidation**

Prepare the remediation commit as a new revalidation; obtain Nolan's approval for its exact new manifest; transmit blind revalidation in a fresh OX context; then run targeted completeness for each remediated/deferred finding that requires explicit closure, without adding unapproved repository artifacts.

- [ ] **Step 11: Verify final exact-head CI and issue Byte's technical recommendation**

Confirm Windows and Ubuntu CI success for the exact remediation head, review final OX/revalidation evidence, and state whether the subsystem is technically ready for Nolan's final acceptance. Do not mark V1 complete before that human acceptance.

---

## Plan self-review checklist

Before execution begins, verify this plan against the approved spec:

- Every spec requirement in Sections 1–23 maps to Tasks 1–10.
- No production task introduces provider abstraction, execution authority, arbitrary file selection, auto-retry, streaming, background workers, or a database.
- File/module boundaries preserve existing `FileService` and isolate `byte_mcp.ox`.
- The API key never crosses the `OXClient` authorization-header construction boundary.
- Preparation, approval, concurrent claim, retry, continuation, and revalidation semantics all have explicit tests before implementation.
- Live credits are touched only after deterministic and exact-head CI gates are green.
- The dogfood review/revalidation cycle occurs before V1 completion.
