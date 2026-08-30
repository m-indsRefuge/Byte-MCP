# Byte-MCP Write V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled, transactional engineering write authority for `AIProjects` so Byte can scaffold repositories and modify project text/code while preserving operator-controlled policy, read-before-write concurrency, recovery, rollback, auditing, and strict project containment.

**Architecture:** Preserve the existing `FileService` and four read tools as the read-only baseline. Add a separate `byte_mcp.write` subsystem built around operator policy, write-specific path resolution, immutable prepared manifests, protected private staging/recovery state, durable JSON journals, per-project writer locks, deterministic commit/rollback/reconciliation, and exactly three public MCP mutation tools: `prepare_mutation`, `commit_mutation`, and `get_mutation_status`.

**Tech Stack:** Python `>=3.12,<3.14`; `mcp[cli]==1.28.1`; Python stdlib only for the write engine (`dataclasses`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `shutil`, `tempfile`, `uuid`); pytest; ruff; existing Pester launcher suite; existing Windows/Ubuntu CI. Do not add a database, ORM, shell dependency, Git library, or new runtime package for Write V1.

**Spec:** `docs/superpowers/specs/2026-08-30-byte-mcp-write-v1-design.md`

## Global Constraints

- The only writable root alias in Write V1 is `projects`, resolving to `%USERPROFILE%\AIProjects` in the accepted remote profile.
- `AIProjects/Byte-MCP` is always protected from MCP write authority in Write V1.
- Operator policy, transaction journals, staged content, locks, and recovery material live outside every Byte-readable/writable root.
- Missing write policy means writes are disabled; malformed, unsupported, or internally inconsistent policy is a configuration failure and must never enable writes.
- Byte may create new top-level projects beneath `AIProjects` and scaffold complete repository trees.
- Every transaction is scoped to exactly one top-level project.
- Cross-project move/rename is denied.
- Existing-file modification requires the exact SHA-256 of the version previously read.
- Existing-directory move/delete requires a deterministic directory manifest digest.
- Write V1 accepts UTF-8 text/code content only; binary/opaque content is denied.
- Every mutation uses prepare -> commit; there is no direct MCP write/delete/move bypass.
- Byte may commit its own valid prepared transactions.
- Existing-state mutations create recovery material before live mutation.
- Delete is recoverable; permanent purge is absent from the MCP surface.
- A duplicate `commit_mutation(transaction_id)` must never duplicate filesystem effects.
- An ambiguous transport result after commit must be resolved with `get_mutation_status` before any retry.
- If rollback/reconciliation cannot prove trusted state, the project enters `RECOVERY_REQUIRED` and further writes are denied while reads remain available.
- Existing `list_roots`, `list_directory`, `search`, and `fetch` authority must not be broadened to implement writes.
- No shell, process control, registry mutation, Git command execution, GitHub mutation, general HTTP, or computer-use authority is added.
- Python remains `>=3.12,<3.14`; MCP remains `mcp[cli]==1.28.1`.
- Primary live deployment is Windows; all Python write tests that are not Windows-specific must remain green on Ubuntu CI.

## Locked V1 Policy Defaults

The operator-created Write V1 policy uses these concrete defaults so tests and rollout have deterministic ceilings:

```json
{
  "schema_version": 1,
  "enabled": true,
  "root_alias": "projects",
  "protected_projects": ["Byte-MCP"],
  "allow_new_projects": true,
  "allow_cross_project_moves": false,
  "allow_binary_writes": false,
  "snapshot_existing": true,
  "delete_mode": "recoverable",
  "allow_permanent_delete": false,
  "require_prepare_commit": true,
  "allow_self_commit": true,
  "max_operations": 200,
  "max_file_bytes": 1000000,
  "max_staged_bytes": 20000000,
  "max_directory_entries": 20000,
  "max_directory_bytes": 250000000,
  "max_patch_bytes": 1000000,
  "transaction_ttl_seconds": 900,
  "recovery_retention_days": 30,
  "recovery_max_bytes": 2147483648
}
```

These are policy values, not hard architectural ceilings. A future operator-controlled policy version may deliberately change them; Byte cannot.

## Locked File Structure

Create:

```text
src/byte_mcp/write/
├── __init__.py
├── policy.py
├── paths.py
├── operations.py
├── manifest.py
├── staging.py
├── recovery.py
├── journal.py
├── locking.py
├── transaction.py
└── service.py

tests/write/
├── __init__.py
├── conftest.py
├── test_policy.py
├── test_paths.py
├── test_manifest.py
├── test_staging.py
├── test_recovery.py
├── test_journal.py
├── test_locking.py
├── test_prepare.py
├── test_commit.py
├── test_rollback.py
├── test_reconciliation.py
├── test_service.py
├── test_mcp_surface.py
├── test_security_invariants.py
└── test_write_v1_e2e.py
```

Do not move write logic into `src/byte_mcp/service.py`; that file remains the read service.

---

### Task 1: Write configuration, policy, private state paths, errors, and shared fixtures

**Files:**
- Modify: `src/byte_mcp/settings.py`
- Modify: `src/byte_mcp/errors.py`
- Create: `src/byte_mcp/write/__init__.py`
- Create: `src/byte_mcp/write/policy.py`
- Create: `config/write-policy.example.json`
- Create: `tests/write/__init__.py`
- Create: `tests/write/conftest.py`
- Create: `tests/write/test_policy.py`
- Modify: `tests/test_settings.py`

**Interfaces:**
- `Settings.write_policy_file: Path`
- `Settings.write_state_dir: Path`
- `WritePolicy.load(path: Path) -> WritePolicy`
- `load_optional_write_policy(path: Path) -> WritePolicy | None`
- Errors: `WriteError`, `WriteConfigurationError`, `WritePolicyError`, `WritePathError`, `WriteConflictError`, `WriteStaleStateError`, `WritePatchError`, `WriteTransactionError`, `WriteExpiredError`, `WriteLockError`, `WriteIntegrityError`, `WriteRollbackError`, `WriteRecoveryRequiredError`.
- Shared fixture `write_env` builds a temporary `projects` root plus private state outside that root.

- [ ] **Step 1: Write RED settings/policy tests**

```python
from pathlib import Path

import pytest

from byte_mcp.errors import WriteConfigurationError
from byte_mcp.write.policy import WritePolicy, load_optional_write_policy


def test_missing_policy_disables_writes(tmp_path: Path) -> None:
    assert load_optional_write_policy(tmp_path / "missing.json") is None


def test_policy_rejects_unsupported_version(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text('{"schema_version": 2}', encoding="utf-8")
    with pytest.raises(WriteConfigurationError, match="schema_version"):
        WritePolicy.load(path)


def test_v1_policy_cannot_enable_self_write(write_policy_file: Path) -> None:
    policy = WritePolicy.load(write_policy_file)
    assert policy.root_alias == "projects"
    assert "Byte-MCP" in policy.protected_projects
    assert policy.allow_permanent_delete is False
    assert policy.allow_cross_project_moves is False
```

Add `tests/test_settings.py` coverage proving `Settings.load()` resolves `BYTE_MCP_WRITE_POLICY_FILE` and `BYTE_MCP_WRITE_STATE_DIR` as absolute paths without requiring them to exist.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_policy.py tests/test_settings.py -v
```

Expected: import/attribute failures because write policy/settings do not yet exist.

- [ ] **Step 3: Add concrete write errors**

Append subclasses to `src/byte_mcp/errors.py`, all inheriting from `WriteError`, and `WriteError` inheriting from `ByteMCPError`. Do not store file contents, patch bodies, or private paths on exceptions.

- [ ] **Step 4: Extend `Settings` with protected paths**

Add fields:

```python
write_policy_file: Path
write_state_dir: Path
```

and load them from:

```text
BYTE_MCP_WRITE_POLICY_FILE
BYTE_MCP_WRITE_STATE_DIR
```

Default development paths may be repo-relative for tests, but the launcher task later overrides both into `%USERPROFILE%\.byte-mcp\write\...` for accepted deployment.

- [ ] **Step 5: Implement strict immutable `WritePolicy`**

```python
@dataclass(frozen=True, slots=True)
class WritePolicy:
    schema_version: int
    enabled: bool
    root_alias: str
    protected_projects: tuple[str, ...]
    allow_new_projects: bool
    allow_cross_project_moves: bool
    allow_binary_writes: bool
    snapshot_existing: bool
    delete_mode: str
    allow_permanent_delete: bool
    require_prepare_commit: bool
    allow_self_commit: bool
    max_operations: int
    max_file_bytes: int
    max_staged_bytes: int
    max_directory_entries: int
    max_directory_bytes: int
    max_patch_bytes: int
    transaction_ttl_seconds: int
    recovery_retention_days: int
    recovery_max_bytes: int
```

`WritePolicy.load()` must require all V1 keys, reject unknown keys, require `schema_version == 1`, require `enabled is True`, require `root_alias == "projects"`, require `Byte-MCP` in protected projects, require the locked V1 booleans/modes above, and bound every numeric value to a positive defensive range. `load_optional_write_policy()` returns `None` only when the file is absent; invalid existing files raise `WriteConfigurationError`.

- [ ] **Step 6: Add the exact example policy and shared fixture**

`tests/write/conftest.py` creates:

```python
@pytest.fixture
def write_env(tmp_path: Path):
    projects = tmp_path / "AIProjects"
    private = tmp_path / "private-byte-mcp-write"
    projects.mkdir()
    private.mkdir()
    # write exact V1 policy JSON under private, roots map points only to projects
    ...
```

The fixture must assert `private.resolve()` is not beneath `projects.resolve()` before yielding.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/settings.py src/byte_mcp/errors.py src/byte_mcp/write tests/write tests/test_settings.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_policy.py tests/test_settings.py -v
git add src/byte_mcp/settings.py src/byte_mcp/errors.py src/byte_mcp/write config/write-policy.example.json tests/write tests/test_settings.py
git commit -m "feat: add Write V1 policy foundation"
```

---

### Task 2: Write-specific path resolver and project authority

**Files:**
- Create: `src/byte_mcp/write/paths.py`
- Create: `tests/write/test_paths.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ResolvedWritePath:
    root_alias: str
    project: str
    project_relative: str
    root_relative: str
    absolute: Path
    exists: bool


def resolve_write_path(
    projects_root: Path,
    raw_path: str,
    *,
    protected_projects: tuple[str, ...],
    allow_missing_leaf: bool,
) -> ResolvedWritePath: ...
```

- [ ] **Step 1: Write RED authority/path tests**

Cover normal existing paths, a missing creation target, new top-level project path, absolute path, `..`, `.env`, `.git`, secret/key suffixes, write to `Byte-MCP`, `CON`, `nul.txt`, `name.`, `name `, symlink/junction ancestor, and case-insensitive collision.

Representative tests:

```python
def test_denies_byte_mcp_project(write_env) -> None:
    target = write_env.projects / "Byte-MCP"
    target.mkdir()
    with pytest.raises(WritePathError, match="protected project"):
        resolve_write_path(
            write_env.projects,
            "Byte-MCP/src/server.py",
            protected_projects=("Byte-MCP",),
            allow_missing_leaf=True,
        )


def test_accepts_missing_child_under_safe_root(write_env) -> None:
    resolved = resolve_write_path(
        write_env.projects,
        "new-repo/src/app.py",
        protected_projects=("Byte-MCP",),
        allow_missing_leaf=True,
    )
    assert resolved.project == "new-repo"
    assert resolved.root_relative == "new-repo/src/app.py"
    assert resolved.exists is False
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_paths.py -v
```

- [ ] **Step 3: Implement lexical Windows-safe validation**

Reject empty project name; separators that create empty path segments; dot/parent segments; trailing space/dot; control characters; and case-insensitive reserved basenames `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9` even when they have suffixes.

Reuse `is_denied_relative()` and `is_link_or_junction()` from `src/byte_mcp/security.py`; do not weaken `resolve_under_root()`.

- [ ] **Step 4: Implement existing-ancestor containment**

Walk from canonical projects root through every existing ancestor. Fail if any existing ancestor is a link/junction or cannot be inspected. Canonicalize the deepest existing ancestor and prove it remains under canonical projects root. Missing tail segments are accepted only after lexical checks.

- [ ] **Step 5: Enforce case-insensitive collision detection**

When a parent exists, enumerate names and reject a requested new child whose `.casefold()` matches an existing sibling but whose exact name differs.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/paths.py tests/write/test_paths.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_paths.py tests/test_security.py -v
git add src/byte_mcp/write/paths.py tests/write/test_paths.py
git commit -m "feat: add write path authority"
```

---

### Task 3: Typed operations, structured text patches, and manifest validation

**Files:**
- Create: `src/byte_mcp/write/operations.py`
- Create: `src/byte_mcp/write/manifest.py`
- Create: `tests/write/test_manifest.py`

**Interfaces:**

```python
class OperationKind(StrEnum):
    CREATE_DIRECTORY = "create_directory"
    CREATE_TEXT_FILE = "create_text_file"
    REPLACE_TEXT_FILE = "replace_text_file"
    PATCH_TEXT_FILE = "patch_text_file"
    MOVE = "move"
    RECOVER_DELETE = "recover_delete"
    RESTORE_RECOVERY_ITEM = "restore_recovery_item"


@dataclass(frozen=True, slots=True)
class TextEdit:
    expected_text: str
    replacement_text: str


@dataclass(frozen=True, slots=True)
class MutationOperation:
    kind: OperationKind
    path: str | None = None
    destination: str | None = None
    content: str | None = None
    expected_sha256: str | None = None
    expected_directory_digest: str | None = None
    edits: tuple[TextEdit, ...] = ()
    recovery_id: str | None = None
```

`parse_manifest(payload: Mapping[str, object], policy: WritePolicy) -> MutationManifest` produces one canonical project-scoped immutable manifest.

- [ ] **Step 1: Write RED operation-schema tests**

Require:
- create file: path + content, no expected hash;
- replace: path + content + 64-lowercase-hex expected SHA;
- patch: path + non-empty edits + expected SHA;
- move: source + destination + either file SHA or directory digest;
- recover delete: path + file SHA or directory digest;
- restore: recovery ID + destination;
- no unknown operation fields.

Reject NUL characters in text inputs and any UTF-8 encoded content above policy limit.

- [ ] **Step 2: Write RED structured patch tests**

Use an exact-match patch contract: each `TextEdit.expected_text` must occur exactly once in the original staged text, all matched ranges must be non-overlapping, and replacements are applied from highest offset to lowest. Zero matches, multiple matches, or overlaps raise `WritePatchError`.

```python
def test_patch_rejects_ambiguous_fragment() -> None:
    with pytest.raises(WritePatchError, match="exactly once"):
        apply_text_edits("x = 1\nx = 1\n", (TextEdit("x = 1", "x = 2"),))
```

- [ ] **Step 3: Write RED manifest-conflict tests**

Reject duplicate targets, delete-parent + child-modify, move-to-created-destination, source/destination cycles, cross-project moves, more than `max_operations`, and manifests spanning two projects. Require explicit `create_directory` operations for missing parent directories of created files.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_manifest.py -v
```

- [ ] **Step 5: Implement parsers and canonical manifest**

`MutationManifest` stores ordered immutable operations plus `project`, canonical JSON representation, and `manifest_sha256`. Canonical JSON uses sorted keys and compact separators. Never include private absolute paths.

- [ ] **Step 6: Implement deterministic dependency ordering**

The manifest computes commit order rather than trusting caller order: parent directories before child creates, content writes before independent moves, and recover deletes after other writes unless dependency analysis requires otherwise. Cycles are rejected.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/operations.py src/byte_mcp/write/manifest.py tests/write/test_manifest.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_manifest.py -v
git add src/byte_mcp/write/operations.py src/byte_mcp/write/manifest.py tests/write/test_manifest.py
git commit -m "feat: add mutation manifest contracts"
```

---

### Task 4: Staging, file hashes, directory digests, and protected recovery objects

**Files:**
- Create: `src/byte_mcp/write/staging.py`
- Create: `src/byte_mcp/write/recovery.py`
- Create: `tests/write/test_staging.py`
- Create: `tests/write/test_recovery.py`

**Interfaces:**

```python
def sha256_file(path: Path) -> str: ...
def directory_manifest(path: Path, *, max_entries: int, max_bytes: int) -> DirectoryManifest: ...
def stage_text(transaction_dir: Path, operation_id: str, text: str) -> StagedBlob: ...

class RecoveryStore:
    def snapshot_file(self, transaction_id: str, source: Path, root_relative: str) -> RecoveryItem: ...
    def snapshot_directory(self, transaction_id: str, source: Path, root_relative: str, *, max_entries: int, max_bytes: int) -> RecoveryItem: ...
    def verify(self, recovery_id: str) -> RecoveryItem: ...
    def materialize(self, recovery_id: str, destination: Path) -> None: ...
```

- [ ] **Step 1: Write RED staging integrity tests**

Prove UTF-8 staging uses no implicit cp1252 fallback, returns exact staged SHA-256/byte count, rejects NUL/oversize, and detects a staged blob modified after preparation.

- [ ] **Step 2: Write RED directory-digest tests**

Digest input is canonical rows of normalized relative path, type (`file`/`directory`), file byte count, and file SHA-256. Sort by casefolded path then exact path. Reject links/junctions and configured tree limits.

- [ ] **Step 3: Write RED recovery tests**

Snapshots must preserve prior bytes, root-relative metadata, source SHA/directory digest, timestamp, and opaque `RCV-<uuid4>` ID. `verify()` fails when stored bytes or metadata no longer match recorded digest.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_staging.py tests/write/test_recovery.py -v
```

- [ ] **Step 5: Implement content-addressed protected storage**

Use private state paths such as:

```text
write_state_dir/
  staging/<TX-ID>/<operation-id>.blob
  recovery/<RCV-ID>/metadata.json
  recovery/<RCV-ID>/payload...
```

Write files via sibling temporary file + flush + `os.fsync()` + `os.replace()` before returning metadata. Do not expose these absolute paths in public objects.

- [ ] **Step 6: Implement retention eligibility without automatic purge**

Provide `RecoveryStore.retention_candidates(now)` that excludes recovery items referenced by `PREPARED`, `COMMITTING`, `ROLLING_BACK`, `FAILED`, or `RECOVERY_REQUIRED` transactions. Write V1 does not expose purge through MCP; actual operator cleanup can be a later maintenance action.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/staging.py src/byte_mcp/write/recovery.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_staging.py tests/write/test_recovery.py -v
git add src/byte_mcp/write/staging.py src/byte_mcp/write/recovery.py tests/write/test_staging.py tests/write/test_recovery.py
git commit -m "feat: add write staging and recovery store"
```

---

### Task 5: Durable transaction journal and per-project writer lock

**Files:**
- Create: `src/byte_mcp/write/journal.py`
- Create: `src/byte_mcp/write/locking.py`
- Create: `tests/write/test_journal.py`
- Create: `tests/write/test_locking.py`

**Interfaces:**

```python
class TransactionStatus(StrEnum):
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    PREPARED = "PREPARED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

class TransactionJournal:
    def create(self, record: TransactionRecord) -> None: ...
    def read(self, transaction_id: str) -> TransactionRecord: ...
    def transition(self, transaction_id: str, expected: TransactionStatus, target: TransactionStatus, **updates: object) -> TransactionRecord: ...
    def append_step(self, transaction_id: str, step: JournalStep) -> TransactionRecord: ...
    def incomplete(self) -> list[TransactionRecord]: ...
```

`ProjectWriteLock.acquire(project: str, transaction_id: str)` uses an exclusive lock file under private state and releases only its own token.

- [ ] **Step 1: Write RED lifecycle tests**

Prove allowed transitions, rejection of stale expected-state transitions, atomic JSON replacement, torn/invalid journal -> `WriteIntegrityError`, and transaction IDs of form `TX-<uuid4>`.

- [ ] **Step 2: Write RED commit idempotency-state tests**

Prove durable `COMMITTED` and `ROLLED_BACK` records are readable after a fresh journal object is constructed; this state is the source of truth for duplicate commit responses.

- [ ] **Step 3: Write RED locking tests**

Two transactions cannot acquire the same project lock; different projects can. A lock records project, transaction ID, PID, and random owner token. Release with wrong token fails. Tests must not infer ownership from executable name.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_journal.py tests/write/test_locking.py -v
```

- [ ] **Step 5: Implement atomic journal persistence**

One JSON file per transaction under `write_state_dir/transactions`. Persist full safe manifest metadata, hashes, timestamps, recovery IDs, operation pre/post evidence, and progress markers; never persist source text or patch bodies in the journal.

- [ ] **Step 6: Implement exclusive project lock files**

Use `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` for cross-process exclusion. Stale lock cleanup is not automatic here; reconciliation in Task 9 decides when a lock can be safely removed.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/journal.py src/byte_mcp/write/locking.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_journal.py tests/write/test_locking.py -v
git add src/byte_mcp/write/journal.py src/byte_mcp/write/locking.py tests/write/test_journal.py tests/write/test_locking.py
git commit -m "feat: add write transaction journal"
```

---

### Task 6: Prepare transaction orchestration

**Files:**
- Create: `src/byte_mcp/write/transaction.py`
- Create: `tests/write/test_prepare.py`

**Interfaces:**

```python
class TransactionEngine:
    def prepare(self, payload: Mapping[str, object]) -> PreparedTransactionResult: ...
    def commit(self, transaction_id: str) -> CommitResult: ...
    def status(self, transaction_id: str) -> TransactionStatusResult: ...
    def reconcile_incomplete(self) -> ReconciliationReport: ...
```

Task 6 implements `prepare()` and read-only `status()` only; commit remains deliberately unimplemented until RED commit tests exist.

- [ ] **Step 1: Write RED full-prepare test**

Create an existing UTF-8 file, fetch its SHA in test setup, then prepare a replace + create transaction. Assert:

```text
status PREPARED
project correct
manifest hash present
old SHA recorded
new staged SHA recorded
recovery ID created for existing file
live project unchanged
expiry = prepared_at + policy TTL
```

- [ ] **Step 2: Write RED stale/invalid preparation tests**

Reject wrong old SHA, missing parent directory not created in manifest, binary existing file, oversize staged bytes, cross-project manifest, protected project, secret path, and project currently marked `RECOVERY_REQUIRED`.

- [ ] **Step 3: Write RED transaction-expiry status test**

With injected clock beyond TTL, `status()` persists `EXPIRED` for a still-`PREPARED` transaction and commit will later reject it.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_prepare.py -v
```

- [ ] **Step 5: Implement prepare pipeline**

Exact order:

```text
load/validate current policy
parse and normalize manifest
resolve every path/project
validate whole-manifest conflicts and limits
read source hashes/directory digests
strictly decode existing text when content mutation requested
stage created/replaced/patched result text
snapshot every existing-state mutation
persist immutable PREPARED journal record
return safe prepared evidence
```

Preparation must not create, replace, move, or delete anything under `AIProjects`.

- [ ] **Step 6: Implement safe public result objects**

`PreparedTransactionResult` and `TransactionStatusResult` return only transaction ID, policy version, project, operation summaries, source/result hashes/digests, recovery IDs, timestamps, and status. No private paths or file bodies.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py tests/write/test_prepare.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_prepare.py -v
git add src/byte_mcp/write/transaction.py tests/write/test_prepare.py
git commit -m "feat: prepare write transactions"
```

---

### Task 7: Commit engine for directory/file creation and text replacement/patching

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Create: `tests/write/test_commit.py`
- Create: `tests/write/test_rollback.py`

**Interfaces:**
- Completes `TransactionEngine.commit(transaction_id)` for `create_directory`, `create_text_file`, `replace_text_file`, and `patch_text_file`.
- Internal `_install_staged_file(staged: Path, destination: Path, *, must_exist: bool) -> None` uses a temporary sibling in the destination directory followed by `os.replace`.

- [ ] **Step 1: Write RED successful commit test**

Prepare a transaction that creates nested directories, creates one file, replaces one file, and patches one file. Commit and assert exact resulting bytes/hashes, `COMMITTED`, recovery IDs, and no leftover target-side temp files.

- [ ] **Step 2: Write RED revalidation-after-lock test**

Prepare against SHA A, modify source externally to SHA B, then commit. Assert `WriteStaleStateError`, live B content remains untouched, and no staged content is installed.

- [ ] **Step 3: Write RED idempotent duplicate-commit test**

Call commit twice on the same transaction. Second result must equal durable first result and filesystem mtimes/content must show no second mutation.

- [ ] **Step 4: Write RED rollback fault matrix**

Inject an exception after each live mutation position in a four-operation transaction. For every injection point assert the final live tree equals the exact pre-transaction tree and journal ends `ROLLED_BACK`. Include newly created files/directories and replaced files.

- [ ] **Step 5: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py -v
```

- [ ] **Step 6: Implement commit preflight under lock**

Commit must:

```text
read durable PREPARED record
return durable result immediately if already COMMITTED/ROLLED_BACK
reject EXPIRED/RECOVERY_REQUIRED/invalid status
reload current operator policy and require same policy version/effective authority
acquire project lock
re-read every source/destination
recheck SHA/directory digest/staging digest
persist COMMITTING before first live effect
```

- [ ] **Step 7: Implement file installation and rollback evidence**

Before each effect, journal expected pre-state and expected post-state. After the effect, verify the expected post hash and append a durable applied marker. Rollback uses recovery snapshots for modified files and removes only paths proven to have been created by this transaction.

- [ ] **Step 8: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py tests/write/test_commit.py tests/write/test_rollback.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py -v
git add src/byte_mcp/write/transaction.py tests/write/test_commit.py tests/write/test_rollback.py
git commit -m "feat: commit transactional text writes"
```

---

### Task 8: Same-project move, recoverable delete, and recovery restoration

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Modify: `src/byte_mcp/write/recovery.py`
- Modify: `tests/write/test_commit.py`
- Modify: `tests/write/test_rollback.py`
- Modify: `tests/write/test_recovery.py`

**Interfaces:**
- Commit support for `move`, `recover_delete`, `restore_recovery_item`.

- [ ] **Step 1: Write RED same-project move tests**

Prove file and directory moves succeed only with matching SHA/directory digest and absent destination. Cross-project move, occupied destination, stale source identity, and move of `Byte-MCP` remain denied.

- [ ] **Step 2: Write RED recover-delete tests**

Delete a file and non-empty directory. Live path disappears, recovery item remains integrity-valid, transaction returns recovery IDs, and no permanent-delete operation exists.

- [ ] **Step 3: Write RED restore tests**

Restore a recovery item into an absent allowed destination using prepare -> commit. Collision with existing destination is denied. Restoration does not consume/delete the recovery item.

- [ ] **Step 4: Extend rollback fault matrix**

Inject failures after move and after live deletion. Assert exact original paths/content are restored from durable evidence.

- [ ] **Step 5: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py tests/write/test_recovery.py -v
```

- [ ] **Step 6: Implement operations**

For same-volume project move, use `os.replace(source, destination)` only after destination absence and source identity are reverified. For recover-delete, rely on the already verified private snapshot then remove the live file/directory; do not send it to OS recycle bin. Restore materializes verified recovery bytes/tree into an absent destination through target-side temporary files/directories where practical.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py src/byte_mcp/write/recovery.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py tests/write/test_recovery.py -v
git add src/byte_mcp/write/transaction.py src/byte_mcp/write/recovery.py tests/write
git commit -m "feat: add recoverable project mutations"
```

---

### Task 9: Crash reconciliation and `RECOVERY_REQUIRED`

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Modify: `src/byte_mcp/write/journal.py`
- Modify: `src/byte_mcp/write/locking.py`
- Create: `tests/write/test_reconciliation.py`

**Interfaces:**
- `TransactionEngine.reconcile_incomplete() -> ReconciliationReport`
- Per-project marker/state query `project_write_state(project) -> NORMAL | RECOVERY_REQUIRED`.

- [ ] **Step 1: Write RED restart-reconciliation matrix**

Construct durable journals representing interruption before first effect, after each operation effect but before its applied marker, after applied marker, during rollback, and after final filesystem state but before `COMMITTED`. Recreate `TransactionEngine` and assert deterministic reconciliation.

- [ ] **Step 2: Write RED uncertain-state test**

Corrupt/remove required recovery material for an interrupted replacement. Reconciliation must not guess; mark project `RECOVERY_REQUIRED`, preserve evidence, and deny new prepare/commit for that project.

- [ ] **Step 3: Write RED stale-lock handling test**

A stale lock may be removed only after reconciliation proves no active trusted commit owns it. A lock belonging to a still-running/incomplete transaction is not silently deleted.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_reconciliation.py tests/write/test_locking.py -v
```

- [ ] **Step 5: Implement startup reconciliation**

For each `COMMITTING`/`ROLLING_BACK` journal, compare live state to recorded pre/post evidence. Prefer completing verified rollback unless the journal already proves every requested post-state and final verification can be completed safely. Persist every reconciliation decision before unlocking the project.

- [ ] **Step 6: Implement protected project state**

Persist recovery-required state under private state, not inside the project. Reads do not consult this marker; write prepare/commit does. No MCP tool clears this marker in V1.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write tests/write/test_reconciliation.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_reconciliation.py tests/write/test_locking.py -v
git add src/byte_mcp/write tests/write/test_reconciliation.py tests/write/test_locking.py
git commit -m "feat: reconcile interrupted write transactions"
```

---

### Task 10: Write service, audit evidence, safe status envelopes, and retention reporting

**Files:**
- Create: `src/byte_mcp/write/service.py`
- Modify: `src/byte_mcp/audit.py` only if a minimal helper is required; preserve existing `record()` behavior.
- Create: `tests/write/test_service.py`

**Interfaces:**

```python
class WriteService:
    def prepare_mutation(self, manifest: Mapping[str, object]) -> dict[str, object]: ...
    def commit_mutation(self, transaction_id: str) -> dict[str, object]: ...
    def get_mutation_status(self, transaction_id: str) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED audit-content tests**

Seed sentinel source/patch strings and prove audit JSONL contains transaction ID, policy version, project, operation types, relative paths, old/new hashes/digests, timestamps, outcome/error type, rollback status, and recovery IDs—but never source content, replacement content, patch fragment bodies, private state absolute paths, or credentials.

- [ ] **Step 2: Write RED failure-taxonomy tests**

Service must preserve typed distinctions for policy denial, path denial, stale hash, patch error, expiry, lock contention, integrity failure, rollback failure, and recovery-required state.

- [ ] **Step 3: Write RED status/idempotency tests**

`get_mutation_status` is observational. `commit_mutation` on `COMMITTED` returns the same durable result. Unknown transaction ID produces a typed not-found/write error without scanning arbitrary paths.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_service.py -v
```

- [ ] **Step 5: Implement narrow service adapter**

Construct from existing `Settings`, loaded roots, optional policy, `AuditLog`, journal, stores, lock manager, and transaction engine. Missing policy causes all write calls to return/raise a clear disabled-policy error while read services remain independent.

- [ ] **Step 6: Implement safe evidence response**

Commit response includes:

```text
transaction_id
status
project
policy_version
operations_completed
resulting_sha256/directory digests
recovery_ids
audit_timestamp
```

No response contains private absolute paths or content bodies.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/service.py src/byte_mcp/audit.py tests/write/test_service.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_service.py tests/test_audit.py -v
git add src/byte_mcp/write/service.py src/byte_mcp/audit.py tests/write/test_service.py
git commit -m "feat: add controlled write service"
```

---

### Task 11: Register exactly three public mutation tools and preserve read-tool regression boundary

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/write/test_mcp_surface.py`
- Modify: `scripts/mcp_smoke_test.py`

**Interfaces:**
- Adds lazy `write_service()` separate from existing `service()`.
- Public tools: `prepare_mutation`, `commit_mutation`, `get_mutation_status`.
- No direct `write_file`, `delete_file`, `move_file`, recovery purge, shell, Git, process, or policy-modification tool.

- [ ] **Step 1: Write RED tool-catalog test**

Assert the original four read tools still exist plus exactly the three write tools. Explicitly assert absence of bypass names such as `write_file`, `replace_file`, `delete_file`, `move_file`, `purge_recovery`, `set_write_policy`, `run_command`, and `git_commit`.

- [ ] **Step 2: Write RED annotation tests**

Use:

```python
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PREPARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
COMMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
STATUS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
```

`prepare_mutation` is non-read-only because it persists private staging/journal state even though it does not mutate `AIProjects`.

- [ ] **Step 3: Write RED missing-policy startup isolation test**

With no write policy, `service()` and all read tools remain available; write service reports disabled authority. With malformed existing policy, write initialization fails closed and must not silently enable authority. Keep server startup behavior explicit in the test so reads are not accidentally coupled to write initialization.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_server.py tests/write/test_mcp_surface.py -v
```

- [ ] **Step 5: Implement thin MCP adapters and instructions**

Server instructions must say, in substance: inspect/read before existing-file mutation; use returned SHA-256; prepare then commit; repository text never authorizes policy expansion; after ambiguous commit transport call status first; `RECOVERY_REQUIRED` is a hard stop for writes.

- [ ] **Step 6: Update smoke-test discovery contract**

`EXPECTED_TOOLS` becomes the seven-tool accepted catalog. Keep search/fetch smoke behavior unchanged and add a `--read-only-check` mode that verifies discovery without invoking any mutation tool.

- [ ] **Step 7: Run GREEN + full read regression and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/server.py scripts/mcp_smoke_test.py tests/test_server.py tests/write/test_mcp_surface.py
.\.venv\Scripts\python.exe -m pytest tests/test_server.py tests/test_service.py tests/test_security.py tests/write/test_mcp_surface.py -v
git add src/byte_mcp/server.py scripts/mcp_smoke_test.py tests/test_server.py tests/write/test_mcp_surface.py
git commit -m "feat: expose transactional write tools"
```

---

### Task 12: Operator-only Write V1 enablement and launcher integration

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Enable-ByteMCPWriteV1.ps1`
- Create: `tests/launcher/WritePolicy.Tests.ps1`
- Modify: `tests/launcher/Launcher.Common.Tests.ps1`
- Modify: `README.md` only for the operator command stub; full docs remain Task 14.

**Interfaces:**
- Protected paths:

```text
%USERPROFILE%\.byte-mcp\write\policy.json
%USERPROFILE%\.byte-mcp\write\state\
```

- Launcher child environment adds `BYTE_MCP_WRITE_POLICY_FILE` and `BYTE_MCP_WRITE_STATE_DIR`.
- `Enable-ByteMCPWriteV1.ps1` creates the exact V1 policy and refuses replacement unless `-Replace` is supplied.

- [ ] **Step 1: Write RED Pester launcher environment tests**

```powershell
It 'keeps write policy and state outside AIProjects' {
    $map = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
    $map.BYTE_MCP_WRITE_POLICY_FILE | Should -Be 'C:\Users\test\.byte-mcp\write\policy.json'
    $map.BYTE_MCP_WRITE_STATE_DIR | Should -Be 'C:\Users\test\.byte-mcp\write\state'
    $map.BYTE_MCP_WRITE_POLICY_FILE | Should -Not -Match 'AIProjects'
}
```

- [ ] **Step 2: Write RED operator-script tests**

Prove script exposes only `-Replace`, contains no parameter that accepts arbitrary policy JSON/path/root, writes exact locked V1 policy, refuses accidental replacement, and writes UTF-8 without secrets.

- [ ] **Step 3: Run RED**

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: new WritePolicy tests fail before implementation.

- [ ] **Step 4: Extend launcher paths/environment**

Add `WritePolicyFile` and `WriteStateDir` to `Get-ByteMcpLauncherPaths`, and the two environment variables to `Get-ByteMcpServerEnvironment`. Do not make the policy file a general launcher prerequisite: its absence intentionally means write authority disabled.

- [ ] **Step 5: Implement explicit enablement script**

`Enable-ByteMCPWriteV1.ps1` dot-sources platform/common scripts, constructs only the exact locked V1 JSON, creates `%USERPROFILE%\.byte-mcp\write`, refuses overwrite unless `-Replace`, writes through temp + move, and prints the policy path plus `PASS: Byte-MCP Write V1 policy enabled` without printing secrets/private source content.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\scripts\Check-Launcher.ps1
git add scripts/Launcher.Common.ps1 scripts/Enable-ByteMCPWriteV1.ps1 tests/launcher/WritePolicy.Tests.ps1 tests/launcher/Launcher.Common.Tests.ps1 README.md
git commit -m "feat: add operator Write V1 enablement"
```

---

### Task 13: Adversarial filesystem, limits, crash, and end-to-end deterministic gate

**Files:**
- Create: `tests/write/test_security_invariants.py`
- Create: `tests/write/test_write_v1_e2e.py`
- Expand: `tests/write/test_reconciliation.py`
- Modify: `.github/workflows/ci.yml` only if Windows-specific Python test marking requires an explicit job step; default matrix `pytest` should remain sufficient.

**Interfaces:** No new public interface unless evidence proves a missing contract. Any discovered authority/integrity defect receives a failing regression test before production repair.

- [ ] **Step 1: Add authority attack matrix**

Attempt absolute paths, parent traversal, symlink/junction escape, secret paths, reserved device names, trailing-dot/space aliases, case collisions, `Byte-MCP` self-write, cross-project move, guessed recovery IDs, private-state path text, missing SHA, stale SHA, stale directory digest, occupied destination, duplicate/conflicting operations, and unsupported permanent-delete/policy operations.

- [ ] **Step 2: Add text/binary and size attack matrix**

Try invalid UTF-8 existing files, NUL-containing proposed text, oversize file, oversize patch, operation-count overflow, total staged-byte overflow, directory entry overflow, and directory byte overflow. Every case must fail before live mutation.

- [ ] **Step 3: Add full rollback/restart failure matrix**

Inject failure at every journaled live-effect boundary across create, replace, patch, move, delete, and restore. For restart cases instantiate a fresh engine from the same private state. Assert either exact verified commit or exact verified rollback; otherwise assert `RECOVERY_REQUIRED` and write denial.

- [ ] **Step 4: Add deterministic Write V1 end-to-end test**

Run this complete temp-root flow:

```text
prepare + commit new repository scaffold
read/hash created files
prepare + commit multi-file replace/patch
external edit -> stale commit denied
same-project move succeeds
cross-project move denied
recover-delete succeeds
restore recovery item succeeds
occupied destination denied
duplicate commit returns durable result
all audit entries contain hashes/evidence but no content
```

- [ ] **Step 5: Run focused adversarial gate**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_security_invariants.py tests/write/test_reconciliation.py tests/write/test_write_v1_e2e.py -v
```

Use systematic debugging for every failure. Do not weaken a security test to make implementation pass.

- [ ] **Step 6: Run full repository gate**

```powershell
.\scripts\Check.ps1
```

This must include dependency check, compile, ruff, complete pytest suite, and launcher Pester suite.

- [ ] **Step 7: Commit only after full green evidence**

```bash
git add src tests scripts .github/workflows/ci.yml
git commit -m "test: harden Write V1 authority"
```

Omit `.github/workflows/ci.yml` if unchanged.

---

### Task 14: Documentation, exact-head CI, operator enablement, and real ChatGPT canary acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Create: `docs/WRITE-V1.md`
- Create: `docs/WRITE-V1-ACCEPTANCE.md`
- Modify: `CHANGELOG.md`

**Interfaces:** Produces the operator runbook and acceptance evidence; no new runtime authority.

- [ ] **Step 1: Document exact Write V1 authority**

Document the seven MCP tools, prepare/commit protocol, SHA requirement, text-only policy, project scoping, recoverable delete, recovery IDs, private state, `RECOVERY_REQUIRED`, no self-write, no cross-project move, and explicit non-goals (shell/process/Git/registry/binary/permanent delete/policy mutation).

- [ ] **Step 2: Document operator enablement and disablement**

Enable with:

```powershell
.\scripts\Enable-ByteMCPWriteV1.ps1
```

Disable by stopping Byte-MCP and moving/removing the operator policy file outside MCP authority; restart then exposes read tools with write calls disabled. Do not provide an MCP policy toggle.

- [ ] **Step 3: Update security document accurately**

Replace the frozen no-write statement with versioned authority language: V1.1 read-only remains historical baseline; Write V1 is separately authorized controlled mutation. State that policy/staging/recovery are outside approved roots and `Byte-MCP` is protected from self-modification.

- [ ] **Step 4: Run exact-head local gate**

```powershell
.\scripts\Check.ps1
```

Record actual Python and Pester counts from this head in the acceptance document; do not predict counts.

- [ ] **Step 5: Push implementation branch and verify exact-head CI**

Require Windows Python, Ubuntu Python, and Windows launcher jobs to complete successfully on the exact implementation SHA before live enablement.

- [ ] **Step 6: Enable Write V1 locally and restart managed stack**

Run the operator enablement script, stop the managed stack if active, start it again, and confirm launcher status `READY`. Do not expose or paste tunnel credentials.

- [ ] **Step 7: Perform real ChatGPT -> Secure MCP Tunnel canary**

Create only disposable project `AIProjects/byte-mcp-write-canary/` and prove:

```text
create complete scaffold -> succeeds
fetch/read hashes -> succeeds
multi-file transactional edit -> succeeds
stale-hash mutation -> denied
same-project move -> succeeds
cross-project move -> denied
recover-delete -> succeeds
restore recovery item -> succeeds
occupied destination -> denied
write AIProjects/Byte-MCP -> denied
absolute/outside-root write -> denied
binary/opaque mutation -> denied
modify existing file without SHA -> denied
permanent delete tool -> absent
policy/self-authority mutation tool -> absent
```

- [ ] **Step 8: Verify audit/recovery evidence**

Correlate canary transaction IDs with local JSONL audit. Verify recovery items exist privately and are not fetchable through MCP. Confirm no source/patch content was copied into audit events.

- [ ] **Step 9: Update acceptance status only from evidence**

Before live canary, label Write V1 `implementation_in_validation`. Only after all local/CI/live gates pass may docs/changelog say `accepted`.

- [ ] **Step 10: Commit evidence/docs**

```bash
git add README.md docs/SECURITY.md docs/WRITE-V1.md docs/WRITE-V1-ACCEPTANCE.md CHANGELOG.md
git commit -m "docs: record Write V1 validation"
```

---

## Write V1 Gate Mapping

**Gate A — Policy and authority:** Tasks 1–3 prove operator-controlled policy, project boundaries, protected paths, text-only schemas, and manifest conflicts.

**Gate B — Evidence and private state:** Tasks 4–5 prove staged/recovery integrity, durable journals, and project writer locks outside Byte roots.

**Gate C — Prepare:** Task 6 proves no live mutation during preparation, SHA/digest preconditions, snapshots, immutable manifest evidence, and expiry.

**Gate D — Commit/rollback:** Tasks 7–8 prove file/dir creation, replace/patch, move, recover-delete, restore, idempotency, and rollback from every tested partial position.

**Gate E — Crash recovery:** Task 9 proves restart reconciliation and fail-closed `RECOVERY_REQUIRED`.

**Gate F — MCP/audit/operator boundary:** Tasks 10–12 prove safe evidence, exactly three mutation tools, preserved read tools, correct annotations, and operator-only enablement.

**Gate G — Adversarial/full subsystem:** Task 13 proves authority attacks, limits, failure injection, full deterministic workflow, and repository-wide regression gate.

**Gate H — Live acceptance:** Task 14 requires exact-head CI and real ChatGPT/tunnel success + intentional denials before Write V1 is accepted.

---

## Self-Review Checklist and Result

### Spec coverage

- Policy-driven evolving controls and operator-only authority: Tasks 1, 12, 14.
- AIProjects-only root, new-project scaffolding, Byte-MCP self-write denial, same-project move: Tasks 2, 3, 8, 13.
- UTF-8 text-only create/replace/patch and SHA preconditions: Tasks 3, 4, 6–7.
- Deterministic directory digest: Tasks 4, 6, 8.
- Prepare -> commit and Byte self-commit: Tasks 6–8, 11.
- Multi-file transaction/dependency ordering: Tasks 3, 6–8.
- Recovery snapshots/recover-delete/restore/retention: Tasks 4, 6, 8, 10.
- Private staging and durable journal: Tasks 4–5.
- Per-project single writer: Task 5 and commit preflight in Task 7.
- Logical atomicity, rollback, crash recovery, `RECOVERY_REQUIRED`: Tasks 7–9, 13.
- Typed failure taxonomy and idempotent commit/status: Tasks 1, 5, 7, 10.
- Audit hashes/evidence without content leakage: Task 10 and adversarial Task 13.
- Exactly three mutation tools with truthful annotations: Task 11.
- Existing read subsystem unchanged in authority: Tasks 11, 13, 14.
- Operator enablement outside Byte roots: Task 12.
- Windows/Ubuntu/full regression/live canary acceptance: Tasks 13–14.
- Shell/process/Git/registry/binary/permanent-delete/policy-self-write remain absent throughout.

### Placeholder scan

The plan contains no unresolved implementation placeholders. Every task defines concrete files, interfaces, test behavior, commands, and commit gates. Exact final test counts and live canary evidence are intentionally recorded from execution rather than invented in advance.

### Type and interface consistency

- `WritePolicy` and write errors are defined in Task 1 before path/manifest/engine use.
- `ResolvedWritePath` is defined in Task 2 before manifest and prepare use.
- `OperationKind`, `TextEdit`, `MutationOperation`, and `MutationManifest` are defined in Task 3 before staging/transaction use.
- Hash/directory/recovery interfaces are defined in Task 4 before prepare/commit.
- `TransactionStatus`, journal, and project lock are defined in Task 5 before engine mutation.
- `TransactionEngine` begins in Task 6 and is extended rather than replaced in Tasks 7–9.
- `WriteService` in Task 10 is the only application interface consumed by MCP Task 11.
- Launcher Task 12 supplies the same environment variable names added to `Settings` in Task 1.
- `commit_mutation` idempotency always derives from durable journal state, never caller retry assumptions.

## Execution Handoff

At implementation start, create an isolated worktree using `superpowers:using-git-worktrees` from the branch/commit containing this approved spec and plan. Preserve RED -> GREEN TDD inside each task and the commit checkpoints above. Do not implement Write V1 directly on `main`, and do not merge or modify the separate OX subsystem merely because both projects exist in Byte-MCP.