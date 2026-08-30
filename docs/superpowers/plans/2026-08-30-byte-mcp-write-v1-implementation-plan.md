# Byte-MCP Write V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled, transactional engineering write authority for `AIProjects` so Byte can scaffold repositories and modify project text/code while preserving operator-controlled policy, read-before-write concurrency, recovery, rollback, auditing, and strict project containment.

**Architecture:** Keep the existing `FileService` and four read tools as the read-only baseline. Add a separate `byte_mcp.write` subsystem with operator policy, write-specific path resolution, immutable prepared transaction evidence, protected staging/recovery state, durable JSON journals, OS-backed per-project writer locks, deterministic commit/rollback/reconciliation, and exactly three public mutation tools: `prepare_mutation`, `commit_mutation`, and `get_mutation_status`.

**Tech Stack:** Python `>=3.12,<3.14`; `mcp[cli]==1.28.1`; Python stdlib only for Write V1 (`dataclasses`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `shutil`, `stat`, `tempfile`, `uuid`, Windows `msvcrt`, POSIX `fcntl`); pytest; ruff; existing Pester launcher suite; existing Windows/Ubuntu CI. No database, ORM, shell dependency, Git library, or new runtime package is added for Write V1.

**Spec:** `docs/superpowers/specs/2026-08-30-byte-mcp-write-v1-design.md`

## Global Constraints

- Writable root alias: exactly `projects`, resolving to `%USERPROFILE%\AIProjects` in the accepted remote profile.
- `AIProjects/Byte-MCP` is protected from MCP mutation authority, case-insensitively.
- Operator policy, journals, staged content, locks, recovery objects, and recovery-required markers live outside every approved Byte filesystem root.
- Missing policy means write authority disabled. An existing malformed, unsupported, or internally inconsistent policy never enables writes.
- Byte may create new top-level projects and complete text/code repository scaffolds beneath `AIProjects`.
- Every transaction targets exactly one top-level project.
- Cross-project move/rename is denied.
- Every existing-file mutation, including move and recover-delete, requires the exact SHA-256 previously read by Byte.
- Existing-directory move/recover-delete binds a deterministic directory digest computed during preparation and rechecked at commit; the caller does not need a separate directory-digest read tool.
- Binary/opaque file mutation is denied. Directory mutation is denied if the bounded tree contains unsafe, secret-denied, linked/reparse, hard-linked, or non-UTF-8 file content.
- All mutations use prepare -> commit. There is no low-level MCP bypass.
- Byte may commit its own valid prepared transactions.
- Existing-state mutations create verified recovery material before live mutation starts.
- Delete is recoverable. Permanent purge is absent from the MCP tool surface.
- Duplicate commit calls are idempotent from durable journal state.
- After ambiguous commit transport, status is authoritative before any retry.
- Unprovable rollback/reconciliation sets the affected project to `RECOVERY_REQUIRED`; reads remain available and further writes are denied.
- Existing read authority is not broadened to implement writes.
- No shell, process, registry, Git command, GitHub mutation, arbitrary HTTP, or computer-use authority is added.
- Primary live deployment is Windows; platform-neutral Python tests remain green on Ubuntu CI.

## Locked V1 Policy Defaults

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

These values are policy defaults, not permanent engine constants. Future relaxation requires an operator-controlled policy revision; Byte cannot rewrite its own policy.

## Locked File Structure

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

`src/byte_mcp/service.py` remains the read service. Write logic does not migrate into it.

---

### Task 1: Policy, settings, errors, and deterministic test fixtures

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
- `Settings.write_policy_file: Path | None = None`
- `Settings.write_state_dir: Path | None = None`
- `WritePolicy.load(path: Path) -> WritePolicy`
- `WritePolicy.fingerprint -> str`
- `load_optional_write_policy(path: Path) -> WritePolicy | None`
- Errors: `WriteError`, `WriteConfigurationError`, `WritePolicyError`, `WritePathError`, `WriteConflictError`, `WriteStaleStateError`, `WritePatchError`, `WriteTransactionError`, `WriteExpiredError`, `WriteLockError`, `WriteIntegrityError`, `WriteRollbackError`, `WriteRecoveryRequiredError`, `WriteLimitError`.

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
    path.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(WriteConfigurationError, match="schema_version"):
        WritePolicy.load(path)


def test_policy_fingerprint_changes_when_authority_changes(write_policy_file: Path) -> None:
    original = WritePolicy.load(write_policy_file)
    raw = write_policy_file.read_text(encoding="utf-8")
    write_policy_file.write_text(raw.replace('"max_operations": 200', '"max_operations": 199'), encoding="utf-8")
    changed = WritePolicy.load(write_policy_file)
    assert original.fingerprint != changed.fingerprint
```

Add `tests/test_settings.py` tests proving `Settings.load()` uses `~/.byte-mcp/write/policy.json` and `~/.byte-mcp/write/state` unless environment overrides are supplied. Existing direct `Settings(...)` test construction must continue to work because the two new fields have `None` defaults.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_policy.py tests/test_settings.py -v
```

Expected: import/attribute failures for the new write contracts.

- [ ] **Step 3: Add concrete write errors**

```python
class WriteError(ByteMCPError):
    """Base error for expected controlled-write failures."""


class WriteConfigurationError(WriteError):
    """Raised when operator write configuration is invalid."""


class WritePolicyError(WriteError):
    """Raised when the active policy denies a requested mutation."""


class WritePathError(WriteError):
    """Raised when a mutation path violates write containment rules."""
```

Add the remaining named subclasses with one responsibility each. Exceptions never retain file bodies, patch bodies, secrets, or private absolute paths.

- [ ] **Step 4: Extend `Settings.load()` without breaking read tests**

```python
write_policy_file=_resolve_config_path(
    repo_root,
    "BYTE_MCP_WRITE_POLICY_FILE",
    "~/.byte-mcp/write/policy.json",
),
write_state_dir=_resolve_config_path(
    repo_root,
    "BYTE_MCP_WRITE_STATE_DIR",
    "~/.byte-mcp/write/state",
),
```

The dataclass fields themselves default to `None` for legacy unit-test construction; `Settings.load()` always supplies real paths.

- [ ] **Step 5: Implement strict `WritePolicy` and canonical fingerprint**

`WritePolicy.load()` requires exactly the locked V1 keys, `schema_version == 1`, `enabled is True`, `root_alias == "projects"`, protected project `Byte-MCP`, recoverable delete, no permanent delete/cross-project/binary authority, and positive bounded numeric limits. Unknown keys are rejected.

```python
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

The fingerprint, not schema version alone, is bound to prepared transactions so operator policy drift invalidates commit.

- [ ] **Step 6: Add complete shared fixtures**

```python
import json
from types import SimpleNamespace

import pytest


V1_POLICY = {
    "schema_version": 1,
    "enabled": True,
    "root_alias": "projects",
    "protected_projects": ["Byte-MCP"],
    "allow_new_projects": True,
    "allow_cross_project_moves": False,
    "allow_binary_writes": False,
    "snapshot_existing": True,
    "delete_mode": "recoverable",
    "allow_permanent_delete": False,
    "require_prepare_commit": True,
    "allow_self_commit": True,
    "max_operations": 200,
    "max_file_bytes": 1_000_000,
    "max_staged_bytes": 20_000_000,
    "max_directory_entries": 20_000,
    "max_directory_bytes": 250_000_000,
    "max_patch_bytes": 1_000_000,
    "transaction_ttl_seconds": 900,
    "recovery_retention_days": 30,
    "recovery_max_bytes": 2_147_483_648,
}


@pytest.fixture
def write_env(tmp_path):
    projects = tmp_path / "AIProjects"
    private = tmp_path / "private-write"
    state_dir = private / "state"
    projects.mkdir()
    state_dir.mkdir(parents=True)
    policy_file = private / "policy.json"
    policy_file.write_text(json.dumps(V1_POLICY), encoding="utf-8")
    assert private.resolve() != projects.resolve()
    assert projects.resolve() not in private.resolve().parents
    return SimpleNamespace(
        projects=projects,
        private=private,
        state_dir=state_dir,
        policy_file=policy_file,
    )


@pytest.fixture
def write_policy_file(write_env):
    return write_env.policy_file
```

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/settings.py src/byte_mcp/errors.py src/byte_mcp/write tests/write tests/test_settings.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_policy.py tests/test_settings.py -v
git add src/byte_mcp/settings.py src/byte_mcp/errors.py src/byte_mcp/write config/write-policy.example.json tests/write tests/test_settings.py
git commit -m "feat: add Write V1 policy foundation"
```

---

### Task 2: Write path authority, Windows aliases, hard links, and reparse denial

**Files:**
- Create: `src/byte_mcp/write/paths.py`
- Create: `tests/write/test_paths.py`

**Interfaces:**
- `ResolvedWritePath(root_alias, project, project_relative, root_relative, absolute, exists)`
- `resolve_write_path(projects_root: Path, raw_path: str, protected_projects: tuple[str, ...], allow_missing_leaf: bool) -> ResolvedWritePath`
- `assert_safe_existing_entry(path: Path) -> None`

- [ ] **Step 1: Write RED path tests**

Cover normal existing/missing targets, new top-level project, empty/root-only path, absolute path, backslash path, `..`, colon/ADS syntax, Windows invalid characters, secret names/suffixes, `.git`, protected `Byte-MCP` in mixed case, `CON`, `nul.txt`, trailing space/dot, case-insensitive sibling collision, symlink/junction, generic Windows reparse point when detectable, and hard-linked existing files.

```python
def test_denies_hard_linked_file(write_env) -> None:
    outside = write_env.private / "outside.txt"
    outside.write_text("sentinel", encoding="utf-8")
    project = write_env.projects / "demo"
    project.mkdir()
    linked = project / "linked.txt"
    try:
        linked.hardlink_to(outside)
    except OSError:
        pytest.skip("hard links unavailable")
    with pytest.raises(WritePathError, match="hard link"):
        assert_safe_existing_entry(linked)
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_paths.py -v
```

- [ ] **Step 3: Implement lexical contract**

Public mutation paths use forward slashes. Reject backslashes and Windows-invalid segment characters `< > : " | ? *`, control characters, dot/parent segments, empty segments, trailing dot/space, and case-insensitive reserved device basenames `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9` even with suffixes.

Use `PurePosixPath` for lexical parsing so behavior is deterministic on Windows and Ubuntu.

- [ ] **Step 4: Implement existing-entry safety checks**

```text
if symlink or junction -> deny
if Windows FILE_ATTRIBUTE_REPARSE_POINT is present -> deny
if regular file and st_nlink != 1 -> deny
if inspection fails -> deny
```

Reuse `is_denied_relative()` for secret policy. Do not change `resolve_under_root()`.

- [ ] **Step 5: Implement existing-ancestor containment and case-collision check**

Canonicalize projects root once. Walk each existing ancestor, re-check link/reparse safety, and prove its canonical path remains beneath root. For a missing child beneath an existing parent, enumerate siblings and reject casefold collisions. Protected project comparison is case-insensitive.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/paths.py tests/write/test_paths.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_paths.py tests/test_security.py -v
git add src/byte_mcp/write/paths.py tests/write/test_paths.py
git commit -m "feat: add write path authority"
```

---

### Task 3: Operation contracts, structured patches, and whole-manifest validation

**Files:**
- Create: `src/byte_mcp/write/operations.py`
- Create: `src/byte_mcp/write/manifest.py`
- Create: `tests/write/test_manifest.py`

**Interfaces:**
- `OperationKind`: `create_directory`, `create_text_file`, `replace_text_file`, `patch_text_file`, `move`, `recover_delete`, `restore_recovery_item`.
- `TextEdit(expected_text: str, replacement_text: str)`.
- Request `MutationOperation` fields: kind, path, destination, content, expected_sha256, edits, recovery_id.
- `MutationManifest(project, ordered_operations, manifest_sha256)`.
- Directory digests are prepared evidence, not caller-supplied request fields.

- [ ] **Step 1: Write RED schema tests**

```text
create_directory: path only
create_text_file: path + content
replace_text_file: path + content + expected_sha256
patch_text_file: path + non-empty edits + expected_sha256
move: path + destination; expected_sha256 required later if source resolves to file
recover_delete: path; expected_sha256 required later if source resolves to file
restore_recovery_item: recovery_id + destination
```

Reject unknown fields, malformed `RCV-` IDs, malformed SHA strings, NUL text, per-file byte overflow, and total patch input above `max_patch_bytes` where patch input is the UTF-8 byte sum of every expected/replacement fragment.

- [ ] **Step 2: Write RED structured-patch tests**

Each expected fragment must occur exactly once in the original text. Matched ranges must not overlap. Apply replacements from greatest byte/text offset to least so offsets remain stable.

```python
def test_patch_rejects_ambiguous_fragment() -> None:
    source = "x = 1\nx = 1\n"
    edit = TextEdit(expected_text="x = 1", replacement_text="x = 2")
    with pytest.raises(WritePatchError, match="exactly once"):
        apply_text_edits(source, (edit,))
```

- [ ] **Step 3: Write RED manifest conflict tests**

Reject duplicate targets, source/destination cycles, delete-parent plus child mutation, occupied planned destination, two top-level projects, cross-project move, operation-count overflow, and a created file whose missing parent is not present as a `create_directory` operation. A top-level `create_directory` may establish a new project.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_manifest.py -v
```

- [ ] **Step 5: Implement canonical fingerprint without persisting content**

Compute `manifest_sha256` over the full normalized in-memory request, including content/patches, using canonical JSON. The durable journal later stores only the fingerprint plus safe operation metadata and staged blob IDs; it never stores content or patch bodies.

- [ ] **Step 6: Implement deterministic dependency order**

```text
create parent directories before child entries
install new/replacement/patch files after parents exist
move only after its destination parent exists
recover-delete after independent writes/moves
restore after destination parent exists
reject dependency cycles
```

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/operations.py src/byte_mcp/write/manifest.py tests/write/test_manifest.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_manifest.py -v
git add src/byte_mcp/write/operations.py src/byte_mcp/write/manifest.py tests/write/test_manifest.py
git commit -m "feat: add mutation manifest contracts"
```

---

### Task 4: UTF-8 profiles, same-pass snapshots, directory digests, staging, and recovery retention

**Files:**
- Create: `src/byte_mcp/write/staging.py`
- Create: `src/byte_mcp/write/recovery.py`
- Create: `tests/write/test_staging.py`
- Create: `tests/write/test_recovery.py`

**Interfaces:**
- `TextFileProfile(has_utf8_bom: bool, newline: str | None)`.
- `read_utf8_profile(data: bytes) -> tuple[str, TextFileProfile]`.
- `encode_with_profile(text: str, profile: TextFileProfile) -> bytes`.
- `directory_manifest(path: Path, max_entries: int, max_bytes: int, require_text: bool) -> DirectoryManifest`.
- `RecoveryStore.snapshot_file(...)`, `snapshot_directory(...)`, `verify(...)`, `materialize(...)`.
- `RecoveryStore.prune(now, policy, protected_recovery_ids: frozenset[str]) -> PruneReport`.

- [ ] **Step 1: Write RED UTF-8/profile tests**

Prove plain UTF-8 and UTF-8 BOM are accepted; invalid UTF-8 and NUL bytes are denied. Existing single-convention CRLF/LF/CR is detected. Whole-file replacement normalizes caller newlines to the existing single convention; mixed-newline source leaves caller replacement newline bytes unchanged. Existing BOM state is preserved. New files use UTF-8 without BOM and preserve caller newline characters.

- [ ] **Step 2: Write RED stable file snapshot tests**

Snapshot one open source handle while hashing copied bytes. Compare hash with required `expected_sha256`; verify `fstat` identity/size/mtime before and after copy is stable. A changed source fails preparation rather than producing a mismatched recovery object.

- [ ] **Step 3: Write RED directory manifest/snapshot tests**

Canonical rows contain relative path, type, byte count, and file SHA; sort by `(casefold(path), path)`. Reject secret-denied entries, symlink/junction/reparse entries, hard-linked files, non-UTF-8 files when `require_text=True`, and configured tree limits. Snapshot directory with the same safe walker, then recompute the live manifest and require it to equal the copied snapshot digest before preparation can continue.

- [ ] **Step 4: Write RED recovery integrity/retention tests**

Recovery metadata includes opaque `RCV-<uuid4>`, root-relative source, source hash/digest, mode bits, timestamps required for restoration, byte count, transaction ID, and creation time. Tampering fails verification. Pruning never removes protected IDs; age-expired unprotected items are removed first, then oldest eligible items until store size is within `recovery_max_bytes`. If protected items alone exceed the ceiling, return a limit condition instead of deleting them.

- [ ] **Step 5: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_staging.py tests/write/test_recovery.py -v
```

- [ ] **Step 6: Implement protected storage with atomic metadata/blob writes**

```text
write_state_dir/staging/TX-<uuid>/OP-<index>.blob
write_state_dir/recovery/RCV-<uuid>/metadata.json
write_state_dir/recovery/RCV-<uuid>/payload
```

Create sibling temp files, flush, `os.fsync`, then `os.replace`. Stored metadata is digest-bound. Public results expose IDs/hashes only, never private absolute paths.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/staging.py src/byte_mcp/write/recovery.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_staging.py tests/write/test_recovery.py -v
git add src/byte_mcp/write/staging.py src/byte_mcp/write/recovery.py tests/write/test_staging.py tests/write/test_recovery.py
git commit -m "feat: add write staging and recovery"
```

---

### Task 5: Durable journal and OS-backed per-project writer lock

**Files:**
- Create: `src/byte_mcp/write/journal.py`
- Create: `src/byte_mcp/write/locking.py`
- Create: `tests/write/test_journal.py`
- Create: `tests/write/test_locking.py`

**Interfaces:**
- `TransactionStatus`: `REQUESTED`, `VALIDATING`, `PREPARED`, `COMMITTING`, `COMMITTED`, `REJECTED`, `EXPIRED`, `ROLLING_BACK`, `ROLLED_BACK`, `FAILED`.
- `ProjectWriteState`: `NORMAL`, `RECOVERY_REQUIRED`.
- `TransactionJournal.create/read/transition/append_step/incomplete`.
- `ProjectWriteLock.acquire(project, transaction_id) -> HeldProjectWriteLock`.

- [ ] **Step 1: Write RED journal lifecycle tests**

Prove legal transitions, stale expected-state rejection, atomic JSON replacement, invalid/torn journal -> `WriteIntegrityError`, durable final result persistence, and random IDs `TX-<uuid4>`.

- [ ] **Step 2: Write RED cross-process lock tests**

Spawn a helper Python subprocess that acquires project `demo` and waits. Parent acquisition of `demo` must raise `WriteLockError`; acquisition of `other` succeeds. Kill helper process and prove a new process can acquire `demo` without deleting a stale lock by guesswork.

- [ ] **Step 3: Implement platform OS locking**

```text
Windows: open/create lock metadata file, ensure at least one byte, use msvcrt.locking(fd, LK_NBLCK, 1)
POSIX: open/create lock metadata file, use fcntl.flock(fd, LOCK_EX | LOCK_NB)
```

Hold the file handle for the entire commit/reconciliation critical section. After acquiring the kernel lock, write safe metadata `{project, transaction_id, pid, owner_token}` and flush. Release only the held object/token, unlock, then close. A process crash releases the kernel lock automatically; an old metadata file is not ownership evidence.

- [ ] **Step 4: Run RED/GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_journal.py tests/write/test_locking.py -v
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/journal.py src/byte_mcp/write/locking.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_journal.py tests/write/test_locking.py -v
git add src/byte_mcp/write/journal.py src/byte_mcp/write/locking.py tests/write/test_journal.py tests/write/test_locking.py
git commit -m "feat: add durable write journal and locks"
```

---

### Task 6: Prepare transaction orchestration

**Files:**
- Create: `src/byte_mcp/write/transaction.py`
- Create: `tests/write/test_prepare.py`

**Interfaces:**
- `TransactionEngine.prepare(payload) -> PreparedTransactionResult`.
- `TransactionEngine.status(transaction_id) -> TransactionStatusResult`.
- `PreparedOperation` stores safe source identity (`source_sha256` or computed `source_directory_digest`), staged blob ID/hash, recovery ID, normalized paths, and operation kind.

- [ ] **Step 1: Write RED successful prepare test**

Prepare a transaction that replaces one existing text file and creates a new nested file. Assert status `PREPARED`, project, policy fingerprint/version, manifest hash, old SHA, new staged SHA, recovery ID, expiry timestamp, and unchanged live tree.

- [ ] **Step 2: Write RED source-identity rules**

For existing file replace/patch/move/delete, missing or wrong `expected_sha256` is denied. For directory move/delete, the request has no digest field; preparation computes a bounded text-safe directory digest and stores it as prepared evidence. Binary file move/delete is denied, as is a directory tree containing binary/secret/linked/hard-linked content.

- [ ] **Step 3: Write RED policy/store/expiry tests**

Reject two-project manifests, protected paths, unsafe new parents, staged-byte overflow, recovery-store overflow after safe pruning, project `RECOVERY_REQUIRED`, and expired prepared transactions.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_prepare.py -v
```

- [ ] **Step 5: Implement exact prepare pipeline**

```text
load optional policy; absent -> WritePolicyError disabled
require Settings write paths and prove private state outside every approved root
compute policy fingerprint
prune only eligible recovery items using protected IDs from nonterminal journals
parse/canonicalize one-project manifest
resolve every path and whole-manifest dependency
for each existing file: verify required caller SHA, create same-pass recovery snapshot, decode snapshot as UTF-8 text
for each existing directory: create bounded safe snapshot + computed directory digest
stage create/replace/patch bytes; patch source comes from verified snapshot bytes
verify all stage/recovery digests and total limits
persist content-free PREPARED journal with policy/manifest fingerprints and expiry
return safe evidence
```

Preparation never mutates `AIProjects`.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py tests/write/test_prepare.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_prepare.py -v
git add src/byte_mcp/write/transaction.py tests/write/test_prepare.py
git commit -m "feat: prepare write transactions"
```

---

### Task 7: Commit create/replace/patch with stale-state defense, idempotency, and rollback

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Create: `tests/write/test_commit.py`
- Create: `tests/write/test_rollback.py`

**Interfaces:**
- `TransactionEngine.commit(transaction_id) -> CommitResult` for `create_directory`, `create_text_file`, `replace_text_file`, `patch_text_file`.
- Target-side installation helper copies staged bytes to a temporary sibling, preserves required mode bits for replacement, flushes/fsyncs, then `os.replace`s.

- [ ] **Step 1: Write RED successful multi-file commit test**

Create dirs + new file + replace + patch. Assert exact bytes/hashes/BOM/newline behavior, no target temp remnants, durable `COMMITTED`, resulting hashes, and recovery IDs.

- [ ] **Step 2: Write RED policy and filesystem drift tests**

After prepare, change policy without changing schema version -> commit denied by policy fingerprint mismatch. Separately change source SHA, create destination collision, replace an ancestor with link/reparse point when platform permits, or change directory contents -> commit denied before first live effect.

- [ ] **Step 3: Write RED idempotent duplicate commit test**

First call commits. Second call returns the journaled final result and does not alter content, mtime, recovery IDs, or operation counters.

- [ ] **Step 4: Write RED rollback fault matrix**

Inject an exception after each live effect in a four-operation transaction. Every case must restore byte-for-byte pre-state, restore mode metadata, remove only transaction-created entries, and end `ROLLED_BACK`. If rollback injection itself fails, journal ends `FAILED` and project is marked `RECOVERY_REQUIRED` in Task 9.

- [ ] **Step 5: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py -v
```

- [ ] **Step 6: Implement commit preflight under kernel project lock**

```text
read journal
if COMMITTED or ROLLED_BACK -> return durable result
reject EXPIRED/FAILED/invalid state
reload policy and require exact prepared fingerprint
acquire project lock
re-resolve all paths and recheck ancestor/link/hardlink/collision safety
recheck source SHA/directory digest and staged/recovery integrity
persist COMMITTING before first effect
before each effect revalidate that operation's source/destination again
```

- [ ] **Step 7: Implement journal-before-effect / verify-after-effect discipline**

Before an effect, persist expected pre/post evidence. Execute effect. Verify expected post-state hash/digest. Persist applied marker. On any failure enter `ROLLING_BACK`, undo applied effects in reverse dependency order, verify full pre-state, then persist `ROLLED_BACK`.

- [ ] **Step 8: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py tests/write/test_commit.py tests/write/test_rollback.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py -v
git add src/byte_mcp/write/transaction.py tests/write/test_commit.py tests/write/test_rollback.py
git commit -m "feat: commit transactional text writes"
```

---

### Task 8: Same-project move, recoverable delete, and recovery restore

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Modify: `src/byte_mcp/write/recovery.py`
- Modify: `tests/write/test_commit.py`
- Modify: `tests/write/test_rollback.py`
- Modify: `tests/write/test_recovery.py`

- [ ] **Step 1: Write RED move tests**

File move requires prepared file SHA and text-safe source; directory move requires prepared directory digest. Same project + absent destination succeeds. Cross-project, occupied destination, stale identity, protected project, binary file, unsafe directory tree all fail.

- [ ] **Step 2: Write RED recover-delete/restore tests**

Recover-delete of text file/safe directory removes live path only after recovery verification. Returned recovery ID remains valid. `restore_recovery_item` uses prepare -> commit, requires absent allowed destination, preserves recovered bytes/tree and mode metadata, and does not consume the recovery object.

- [ ] **Step 3: Extend rollback matrix**

Inject failure after move and after delete; restore exact source paths/content. A failure restoring recovery material marks rollback failure for Task 9.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py tests/write/test_recovery.py -v
```

- [ ] **Step 5: Implement move/delete/restore**

Use `os.replace` for same-project move only after destination absence and immediate source revalidation. Recover-delete removes live file with `unlink` or safe directory tree with a walker that rechecks prohibited entries; it never uses OS recycle bin. Restore writes verified recovery data through target-side temporary materialization before final placement.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/transaction.py src/byte_mcp/write/recovery.py tests/write
.\.venv\Scripts\python.exe -m pytest tests/write/test_commit.py tests/write/test_rollback.py tests/write/test_recovery.py -v
git add src/byte_mcp/write/transaction.py src/byte_mcp/write/recovery.py tests/write
git commit -m "feat: add recoverable project mutations"
```

---

### Task 9: Restart reconciliation and project `RECOVERY_REQUIRED`

**Files:**
- Modify: `src/byte_mcp/write/transaction.py`
- Modify: `src/byte_mcp/write/journal.py`
- Create: `tests/write/test_reconciliation.py`

**Interfaces:**
- `TransactionEngine.reconcile_incomplete() -> ReconciliationReport`.
- `project_write_state(project) -> ProjectWriteState`.
- Recovery-required marker is private state, not a project file.

- [ ] **Step 1: Write RED interruption matrix**

Seed durable journals/filesystem states for interruption before first effect, after effect before applied marker, after applied marker, during rollback, and after all final files exist but before `COMMITTED`. Construct a fresh engine and prove deterministic reconciliation.

- [ ] **Step 2: Write RED active-lock and crash-lock tests**

If another process holds the kernel project lock, reconciliation reports lock contention and does not mutate. After that process terminates, a fresh engine can acquire the lock even if metadata file remains.

- [ ] **Step 3: Write RED unprovable-recovery test**

Corrupt/remove required snapshot for an interrupted replace. Engine must preserve journal evidence, mark transaction `FAILED`, mark project `RECOVERY_REQUIRED`, and reject new prepare/commit for that project. Reads are unaffected.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_reconciliation.py tests/write/test_locking.py -v
```

- [ ] **Step 5: Implement reconciliation policy**

Acquire the project kernel lock before reconciliation. Compare live state with journaled pre/post evidence. If every operation post-state is proven and final transaction verification passes, complete `COMMITTED`; otherwise prefer verified rollback. If neither final state nor pre-state can be proven, set `RECOVERY_REQUIRED` instead of guessing.

- [ ] **Step 6: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write tests/write/test_reconciliation.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_reconciliation.py tests/write/test_locking.py -v
git add src/byte_mcp/write tests/write/test_reconciliation.py tests/write/test_locking.py
git commit -m "feat: reconcile interrupted write transactions"
```

---

### Task 10: Write service, audit finalization, status recovery, and terminal cleanup

**Files:**
- Create: `src/byte_mcp/write/service.py`
- Modify: `src/byte_mcp/audit.py` only if a small safe helper is necessary; existing `record()` semantics remain.
- Create: `tests/write/test_service.py`

**Interfaces:**
- `WriteService.prepare_mutation(manifest) -> dict[str, object]`.
- `WriteService.commit_mutation(transaction_id) -> dict[str, object]`.
- `WriteService.get_mutation_status(transaction_id) -> dict[str, object]`.

- [ ] **Step 1: Write RED audit leakage/evidence tests**

Audit must contain transaction ID, policy version/fingerprint prefix or full nonsecret hash, project, operation types, root-relative paths, source/result hashes/digests, recovery IDs, timestamps, durable outcome, rollback/reconciliation status, and classified error. It must not contain source content, replacement content, patch fragments, private absolute state paths, credentials, or authorization headers.

- [ ] **Step 2: Write RED audit-failure-after-commit test**

Force final audit append to fail after filesystem/journal reach `COMMITTED`. `commit_mutation` must not roll back or replay the successful mutation. Journal records `audit_pending=true`; client receives `AuditError`. `get_mutation_status` returns durable `COMMITTED` plus `audit_status="pending"` and may retry final audit from content-free journal metadata. Once append succeeds, mark `audit_pending=false` without touching project files.

- [ ] **Step 3: Write RED failure-taxonomy/status tests**

Preserve policy/path/stale/patch/limit/expiry/lock/integrity/rollback/recovery-required distinctions. Unknown transaction ID returns typed error without filesystem search. Status is observational with respect to `AIProjects`.

- [ ] **Step 4: Write RED terminal cleanup tests**

After durable `COMMITTED`, `ROLLED_BACK`, or `EXPIRED`, staging blobs may be deleted. Cleanup failure leaves protected orphan staging data and is audited; it never changes durable transaction result. Recovery objects remain governed by retention, not staging cleanup.

- [ ] **Step 5: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_service.py -v
```

- [ ] **Step 6: Implement narrow service construction**

Load roots with existing settings. If policy file absent, keep a disabled write service. If present, require valid policy and private state paths outside every root, construct journal/stores/engine, and reconcile incomplete transactions before accepting new writes. Read `FileService` remains independent.

- [ ] **Step 7: Implement audit sequencing**

Before live commit, require an audit `write_commit_requested` append to succeed. After durable terminal state, append final safe outcome. If final append fails, preserve durable transaction result and set audit-pending as above; never make a second filesystem commit to repair audit evidence.

- [ ] **Step 8: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/write/service.py src/byte_mcp/audit.py tests/write/test_service.py
.\.venv\Scripts\python.exe -m pytest tests/write/test_service.py tests/test_audit.py -v
git add src/byte_mcp/write/service.py src/byte_mcp/audit.py tests/write/test_service.py
git commit -m "feat: add controlled write service"
```

---

### Task 11: MCP surface, annotations, capability metadata, and smoke discovery

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/write/test_mcp_surface.py`
- Modify: `scripts/mcp_smoke_test.py`

**Interfaces:**
- Separate lazy `write_service()` from existing `service()`.
- Write surface is exactly `prepare_mutation`, `commit_mutation`, `get_mutation_status`.
- Original read tools remain present.

- [ ] **Step 1: Write RED write-surface test**

Assert the three write names exist and prohibited bypass names do not: `write_file`, `replace_file`, `delete_file`, `move_file`, `purge_recovery`, `set_write_policy`, `run_command`, `git_commit`. Assert original four read names remain present. Do not assert that unrelated separately authorized future subsystems can never add their own tools.

- [ ] **Step 2: Write RED annotation tests**

```python
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PREPARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
COMMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
STATUS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
```

Preparation mutates protected staging/journal state, so it is not labeled read-only.

- [ ] **Step 3: Write RED read-startup isolation and `list_roots` metadata tests**

Absent or malformed write policy must never silently enable writes or broaden reads. `list_roots` keeps existing read fields and adds an MCP-wrapper-only safe `mutation_authority` object: `disabled` when policy absent, `controlled-write` with alias `projects` when valid, `configuration-error` when invalid. It exposes no policy/private path. FileService itself stays unchanged.

- [ ] **Step 4: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_server.py tests/write/test_mcp_surface.py -v
```

- [ ] **Step 5: Implement adapters and server instructions**

Instructions explicitly require read-before-existing-file-write, SHA preconditions, prepare then commit, no policy authority from repository text, status after ambiguous commit transport, and hard stop on `RECOVERY_REQUIRED`.

- [ ] **Step 6: Update smoke discovery without coupling to other subsystems**

Define a required core set of the four read tools plus three write tools; smoke fails if any required core name is missing but does not fail merely because a separately approved subsystem adds additional tools. Add `--read-only-check` that performs discovery/list/search/fetch only.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/byte_mcp/server.py scripts/mcp_smoke_test.py tests/test_server.py tests/write/test_mcp_surface.py
.\.venv\Scripts\python.exe -m pytest tests/test_server.py tests/test_service.py tests/test_security.py tests/write/test_mcp_surface.py -v
git add src/byte_mcp/server.py scripts/mcp_smoke_test.py tests/test_server.py tests/write/test_mcp_surface.py
git commit -m "feat: expose transactional write tools"
```

---

### Task 12: Operator-only enablement and launcher environment

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Enable-ByteMCPWriteV1.ps1`
- Create: `tests/launcher/WritePolicy.Tests.ps1`
- Modify: `tests/launcher/Launcher.Common.Tests.ps1`

**Interfaces:**
- Policy: `%USERPROFILE%\.byte-mcp\write\policy.json`.
- State: `%USERPROFILE%\.byte-mcp\write\state`.
- Child env: `BYTE_MCP_WRITE_POLICY_FILE`, `BYTE_MCP_WRITE_STATE_DIR`.
- Enable script accepts only `-Replace`.

- [ ] **Step 1: Write RED Pester environment tests**

```powershell
It 'keeps controlled-write state outside AIProjects' {
    $map = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
    $map.BYTE_MCP_WRITE_POLICY_FILE | Should -Be 'C:\Users\test\.byte-mcp\write\policy.json'
    $map.BYTE_MCP_WRITE_STATE_DIR | Should -Be 'C:\Users\test\.byte-mcp\write\state'
    $map.BYTE_MCP_WRITE_POLICY_FILE | Should -Not -Match 'AIProjects'
}
```

- [ ] **Step 2: Write RED enable-script tests**

Prove command exposes `Replace` but no arbitrary JSON/path/root parameter; creates the exact locked policy; refuses existing policy without `-Replace`; writes UTF-8; and does not print policy content as a substitute for confirmation.

- [ ] **Step 3: Run RED**

```powershell
.\scripts\Check-Launcher.ps1
```

- [ ] **Step 4: Implement launcher paths/env and explicit policy creation**

`Get-ByteMcpLauncherPaths` exposes `WritePolicyFile`/`WriteStateDir`; `Get-ByteMcpServerEnvironment` exports both. Policy file is not a launcher prerequisite because absence intentionally disables writes. `Enable-ByteMCPWriteV1.ps1` builds only the locked JSON, writes temp -> move, refuses accidental replacement, and reports `PASS: Byte-MCP Write V1 policy enabled`. Operator restarts the managed stack after authority changes.

- [ ] **Step 5: Run GREEN and commit**

```powershell
.\scripts\Check-Launcher.ps1
git add scripts/Launcher.Common.ps1 scripts/Enable-ByteMCPWriteV1.ps1 tests/launcher/WritePolicy.Tests.ps1 tests/launcher/Launcher.Common.Tests.ps1
git commit -m "feat: add operator Write V1 enablement"
```

---

### Task 13: Adversarial/failure-injection gate and full deterministic subsystem regression

**Files:**
- Create: `tests/write/test_security_invariants.py`
- Create: `tests/write/test_write_v1_e2e.py`
- Expand: `tests/write/test_reconciliation.py`
- Modify: `.github/workflows/ci.yml` only if current matrix cannot exercise a required platform test.

- [ ] **Step 1: Add authority attack matrix**

Test absolute/backslash/parent/ADS/invalid-name paths, symlink/junction/reparse escape, hard links, secret paths, case collisions, `Byte-MCP` self-write, cross-project move, guessed recovery IDs, missing/stale SHA, stale directory digest, occupied destination, conflicting manifest operations, unsupported permanent delete, and absent policy-modification tool.

- [ ] **Step 2: Add text/binary/limit matrix**

Test invalid UTF-8, NUL, binary file move/delete, binary inside directory tree, per-file/staged/patch/operation/tree/recovery-store limits. Every denial occurs before live mutation.

- [ ] **Step 3: Add source/destination race injection**

At controlled hooks immediately before live effects, change source content, destination occupancy, ancestor type, or directory tree; operation must revalidate and stop. Document that V1 defends bounded pre-effect races but does not claim hostile same-user kernel-level race immunity beyond available cross-platform filesystem primitives.

- [ ] **Step 4: Add full rollback/restart matrix**

Inject at every journaled effect boundary for create, replace, patch, move, delete, restore, and during rollback. Fresh engine must reach exact verified commit or exact verified pre-state; otherwise project is `RECOVERY_REQUIRED`.

- [ ] **Step 5: Add deterministic end-to-end test**

```text
create repository scaffold
read/hash created files
multi-file replace/patch
external edit -> stale commit denied
same-project move succeeds
cross-project move denied
recover-delete succeeds
restore succeeds
occupied destination denied
duplicate commit returns durable result
audit contains evidence hashes but no content
```

- [ ] **Step 6: Run focused and full gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/write/test_security_invariants.py tests/write/test_reconciliation.py tests/write/test_write_v1_e2e.py -v
.\scripts\Check.ps1
```

Use systematic debugging for failures and write a failing regression before every repair.

- [ ] **Step 7: Commit only after full green evidence**

```bash
git add src tests scripts .github/workflows/ci.yml
git commit -m "test: harden Write V1 authority"
```

Omit `.github/workflows/ci.yml` when unchanged.

---

### Task 14: Documentation, exact-head CI, operator rollout, and real ChatGPT canary

**Files:**
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Create: `docs/WRITE-V1.md`
- Create: `docs/WRITE-V1-ACCEPTANCE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document exact authority and non-goals**

Document four read tools + three write tools, prepare/commit, SHA rules, computed directory digest, UTF-8/BOM/newline behavior, protected hard-link/reparse rules, project scope, recover-delete/restore, recovery retention, private state, audit-pending semantics, `RECOVERY_REQUIRED`, and absence of shell/process/Git/registry/binary/permanent-delete/policy-self-write authority.

- [ ] **Step 2: Document operator enable/disable**

Enable:

```powershell
.\scripts\Enable-ByteMCPWriteV1.ps1
.\scripts\Stop-ByteMCP.ps1
.\scripts\Start-ByteMCP.ps1
```

Disable by stopping Byte-MCP, moving/removing `%USERPROFILE%\.byte-mcp\write\policy.json` outside MCP authority, then restarting. No MCP toggle exists.

- [ ] **Step 3: Run exact-head local gate and record actual counts**

```powershell
.\scripts\Check.ps1
```

Do not predict test counts; record output from the implementation head.

- [ ] **Step 4: Push branch and verify exact-head CI**

Require Windows Python, Ubuntu Python, and Windows launcher jobs to succeed on the same SHA before live enablement.

- [ ] **Step 5: Perform real ChatGPT -> Secure MCP Tunnel canary**

Use only `AIProjects/byte-mcp-write-canary/` and prove:

```text
complete scaffold succeeds
read/fetch hashes succeed
multi-file transaction succeeds
stale hash denied
same-project move succeeds
cross-project move denied
recover-delete succeeds
restore succeeds
occupied destination denied
Byte-MCP self-write denied
outside-root/absolute path denied
binary mutation denied
existing file mutation without SHA denied
permanent delete tool absent
policy mutation tool absent
```

- [ ] **Step 6: Verify evidence and acceptance boundary**

Correlate transaction IDs with local audit; verify recovery objects are private/unfetchable; verify no source/patch body appears in audit. Before live success label implementation `implementation_in_validation`; only after local + CI + live success and intentional denials may docs say `accepted`.

- [ ] **Step 7: Commit evidence/docs**

```bash
git add README.md docs/SECURITY.md docs/WRITE-V1.md docs/WRITE-V1-ACCEPTANCE.md CHANGELOG.md
git commit -m "docs: record Write V1 validation"
```

---

## Gate Mapping

**Gate A — Policy/authority:** Tasks 1–3.

**Gate B — Integrity/private state:** Tasks 4–5.

**Gate C — Prepare:** Task 6.

**Gate D — Commit/rollback/recoverable operations:** Tasks 7–8.

**Gate E — Crash recovery:** Task 9.

**Gate F — Service/audit/MCP/operator boundary:** Tasks 10–12.

**Gate G — Adversarial/full subsystem:** Task 13.

**Gate H — Exact-head CI and real ChatGPT acceptance:** Task 14.

## Self-Review Result

### Spec coverage

- Operator-controlled evolving policy and self-authority denial: Tasks 1, 12, 14.
- New-project scaffolding, same-project restriction, protected Byte-MCP: Tasks 2, 3, 8, 13.
- Text-only + SHA preconditions + BOM/newline behavior: Tasks 3, 4, 6–8.
- Directory digest computed at preparation and rechecked at commit: Tasks 4, 6–8.
- Prepare -> commit, self-commit, multi-file ordering: Tasks 3, 6–8.
- Recovery snapshots, recover-delete, restore, retention: Tasks 4, 6, 8, 10.
- Durable journal and OS-backed single writer: Task 5.
- Rollback, restart reconciliation, `RECOVERY_REQUIRED`: Tasks 7–9, 13.
- Failure taxonomy, idempotency, audit/status after ambiguous outcomes: Tasks 1, 5, 7, 10.
- Exactly three write tools, preserved read surface, truthful annotations: Task 11.
- Operator-only enablement outside roots: Task 12.
- Full adversarial/CI/live acceptance: Tasks 13–14.

### Placeholder scan

No unresolved implementation placeholder markers are present. Interfaces name concrete types/functions, test snippets are executable examples, and each implementation step states the concrete algorithm or platform primitive. Final test counts and live canary evidence are intentionally recorded from execution rather than invented.

### Type/interface consistency

- Settings optional fields preserve existing direct test construction while `Settings.load()` always supplies real protected paths.
- Policy fingerprint is defined before prepare/commit uses it.
- Caller SHA is used for files; directory digest is prepared evidence, avoiding a missing read API.
- Recovery retention receives explicit protected recovery IDs instead of depending implicitly on journal internals.
- Kernel file locking prevents stale lock files from becoming false ownership evidence.
- `WriteService` is the only write application interface consumed by MCP.
- The smoke test requires the seven core read/write names without forbidding unrelated separately approved subsystem tools.
- Audit failure after durable commit cannot cause a second filesystem commit; journal status remains authoritative.

## Execution Handoff

At implementation start, create an isolated worktree using `superpowers:using-git-worktrees` from the commit containing this approved spec and plan. Preserve RED -> GREEN TDD and the commit checkpoints above. Do not implement on `main`. Do not merge or modify the separate OX subsystem as a side effect of Write V1.