# Byte-MCP Write V1 Design

Date: 2026-08-30
Status: Approved design, pending user review of written spec
Branch: `design/byte-mcp-write-v1`

## 1. Purpose

Byte-MCP currently provides a permissioned read-only bridge into Nolan's approved local project root. Write V1 adds controlled engineering write authority for the `AIProjects` root without turning Byte-MCP into a shell, process-control layer, Git client, or general machine-control bridge.

The goal is to let Byte create complete repository scaffolds, create and edit source/configuration/documentation files, move and rename project content, and perform recoverable deletion while preserving strict containment, auditability, rollback, stale-state protection, and operator control over authority.

Write V1 is intentionally policy-driven. Its restrictions are V1 defaults, not permanent architectural constraints. The mutation engine must remain separable from the capability policy so future versions can deliberately relax individual controls without redesigning the core write subsystem.

## 2. Core security principles

Write V1 follows these non-negotiable principles:

1. Byte may exercise configured authority but may never redefine its own authority.
2. Operator-controlled policy, roots configuration, recovery controls, and private write state live outside every Byte-readable or Byte-writable filesystem root.
3. Existing read-only tools remain unchanged in authority and behavior.
4. All writes use a prepare-then-commit protocol; there is no direct low-level write bypass.
5. Modifications of existing files require optimistic concurrency using the exact SHA-256 of the version Byte previously read.
6. Existing-state mutations create recovery material before live mutation begins.
7. Deletes are recoverable in V1; permanent purge is not exposed through MCP.
8. Transactions are bounded to one top-level project.
9. Writes to the `Byte-MCP` project itself are denied in V1.
10. Text/code mutation is allowed; arbitrary binary mutation is denied in V1.
11. Byte may create new top-level project directories under `AIProjects` and scaffold complete repositories.
12. The system fails closed on ambiguity, integrity uncertainty, unsupported policy, stale state, or incomplete recovery.

## 3. V1 capability policy

The active operator-controlled policy is versioned and stored outside `AIProjects`.

The effective V1 authority is:

| Capability | V1 |
| --- | --- |
| Writable root | `AIProjects` |
| Create new top-level projects | Allowed |
| Create directories | Allowed |
| Create UTF-8 text/code files | Allowed |
| Replace existing UTF-8 text/code files | Allowed with SHA-256 precondition |
| Patch existing UTF-8 text/code files | Allowed with SHA-256 precondition |
| Rename/move | Allowed within the same top-level project |
| Cross-project move | Denied |
| Modify binary/opaque files | Denied |
| Snapshot before existing-state mutation | Required |
| Recoverable delete | Allowed |
| Permanent delete | Denied through MCP |
| Prepare -> commit | Required for every mutation |
| Byte may commit its own prepared transaction | Allowed |
| Multi-file transaction | Allowed |
| Write to `AIProjects/Byte-MCP` | Denied |
| Byte may alter write policy/configuration | Denied |

Future policy versions may alter these controls, but a policy relaxation always requires explicit operator-controlled configuration. No MCP tool may grant, expand, or rewrite Byte's authority.

## 4. Public MCP surface

Write V1 keeps the public tool surface deliberately small:

- `prepare_mutation(...)`
- `commit_mutation(transaction_id)`
- `get_mutation_status(transaction_id)`

All filesystem mutations are expressed as operations inside a prepared manifest. Byte-MCP does not expose independent public tools such as `write_file`, `delete_file`, or `move_file` that could bypass transaction validation.

### 4.1 `prepare_mutation`

`prepare_mutation` accepts one bounded project-scoped manifest. It validates policy, paths, content, preconditions, transaction conflicts, limits, and source state before creating an immutable prepared transaction.

Preparation does not mutate `AIProjects`.

The prepared result returns at minimum:

- opaque transaction ID;
- policy version;
- target project;
- operation count;
- normalized manifest summary;
- expected source SHA-256 values or directory manifest digests;
- staged-result SHA-256 values;
- prepared timestamp;
- expiry timestamp;
- current status.

### 4.2 `commit_mutation`

`commit_mutation` accepts only an opaque prepared transaction ID. It does not accept a replacement or modified manifest.

Before mutation begins, Byte-MCP revalidates policy, project state, path state, source hashes/digests, staging integrity, and transaction expiry. Any drift causes the commit to fail closed.

Byte may commit its own prepared transactions in V1 without a separate human confirmation step.

### 4.3 `get_mutation_status`

`get_mutation_status` returns durable transaction state and evidence. It is the required first action after an ambiguous transport failure involving `commit_mutation`; Byte must never assume a failed response means the commit did not occur.

## 5. Supported mutation operations

Prepared manifests support the following explicit V1 operations:

- `create_directory`
- `create_text_file`
- `replace_text_file`
- `patch_text_file`
- `move`
- `recover_delete`
- `restore_recovery_item`

The service must reject ambiguous operation semantics rather than infer intent.

Examples:

- creating a file at an existing path -> reject;
- replacing a missing file -> reject;
- moving into an occupied destination -> reject;
- modifying an existing file without expected SHA-256 -> reject;
- deleting or moving an existing object whose identity no longer matches preparation evidence -> reject;
- moving content across top-level projects -> policy denial.

## 6. Project and path authority

The write resolver is a new subsystem. The existing strict read resolver remains unchanged.

Every accepted path resolves into:

- approved root alias;
- top-level project;
- project-relative path.

For example, `AIProjects/A-Scanner/src/scanner.py` becomes root `projects`, project `A-Scanner`, relative path `src/scanner.py`.

Every transaction is limited to exactly one top-level project. If Byte needs to change two repositories, it prepares two independent transactions.

Creating a new top-level directory is allowed and establishes a new project boundary for that transaction. All other operations in that transaction must remain beneath the newly created project.

The resolver must enforce:

- relative paths only;
- no absolute-path inputs;
- no `..` traversal;
- no symlink or junction traversal;
- no canonicalized escape from the approved root;
- existing secret-denial rules;
- denial of all protected Byte-MCP/private write state;
- denial of writes to the `Byte-MCP` top-level project;
- Windows reserved device-name denial;
- rejection of trailing-dot/trailing-space aliases;
- rejection of case-insensitive collisions and path aliases;
- fail-closed behavior when the filesystem entry cannot be inspected reliably.

Because creation targets may not exist, the write resolver validates the existing parent chain and the proposed child path without weakening the existing read resolver's strict-existing-path contract.

## 7. Text and patch semantics

Write V1 mutates UTF-8 text/code content only.

New files are created as UTF-8. Existing files must decode as supported text before Byte-MCP permits replacement or patching. Arbitrary executables, archives, databases, images, DLLs, opaque blobs, and unsupported binary formats are denied.

For existing files, Byte-MCP preserves newline convention and BOM state where practical and must not silently normalize content unnecessarily.

`replace_text_file` requires:

- target path;
- expected old SHA-256;
- new text content.

`patch_text_file` requires:

- target path;
- expected old SHA-256;
- bounded structured or unified patch payload.

Patch application occurs only in private staging during preparation. Every hunk must apply exactly as required. The fully staged result is hashed before the transaction can become `PREPARED`. The live repository never receives a partially applied patch.

## 8. Identity and stale-state protection

Existing-file mutation uses the exact SHA-256 Byte obtained from a prior read as an optimistic-concurrency precondition.

If the live file changes after preparation, commit fails as stale. Byte-MCP never attempts an implicit merge or guesses which version should win.

For non-empty directories, Byte-MCP computes a deterministic directory manifest digest from normalized relative paths, entry types, and file hashes beneath the directory. Directory move or recover-delete requires that digest to match at commit time.

All source identity checks are repeated after the project write lock is acquired and immediately before live mutation begins.

## 9. Transaction architecture

Write V1 uses private staging plus a durable transactional commit/rollback journal.

The implementation is conceptually separated into:

```text
MCP write tools
      |
      v
WriteService
      |
      +--> CapabilityPolicy
      +--> WritePathResolver
      +--> TransactionValidator
      |
      v
PreparedTransaction
      |
      v
Protected private staging
      |
      v
TransactionCommitter
      +--> recovery snapshots
      +--> durable mutation journal
      +--> filesystem operations
      +--> audit evidence
```

The private write area lives outside every approved Byte filesystem root. The system stages only transaction-relevant content rather than duplicating entire repositories.

## 10. Transaction lifecycle

The normal lifecycle is:

```text
REQUESTED -> VALIDATING -> PREPARED -> COMMITTING -> COMMITTED
```

Failure/recovery states include:

```text
REJECTED
EXPIRED
ROLLING_BACK
ROLLED_BACK
FAILED
```

A prepared transaction is immutable and bound to at least:

- policy version;
- target project;
- canonical operation manifest;
- expected source hashes/digests;
- staged content hashes;
- preparation timestamp;
- expiry timestamp.

Any relevant policy or filesystem drift invalidates the commit.

## 11. Commit ordering and project locking

Only one Byte-MCP transaction may be in `COMMITTING` for a project at a time. The system uses a per-project writer lock.

Reads may continue during commit, subject to normal filesystem behavior.

Commit order is derived from operation dependencies rather than blindly trusting the order in the model-supplied manifest. The commit sequence is conceptually:

1. Revalidate transaction and policy.
2. Acquire project mutation lock.
3. Revalidate live hashes, digests, destinations, and staging integrity.
4. Persist durable commit journal.
5. Create required directories.
6. Materialize staged new/replacement files.
7. Perform moves/renames.
8. Perform recoverable deletes.
9. Verify final filesystem state and resulting hashes/digests.
10. Mark transaction `COMMITTED` durably.
11. Release lock.

The exact internal order may vary when operation dependencies require it, but the journal must always permit deterministic recovery.

## 12. Atomicity guarantee

Write V1 does not claim impossible database-style physical atomicity across an arbitrary filesystem tree.

Its contract is:

> A Byte-MCP transaction is logically atomic and recoverable: either the requested final state is verified and committed, or Byte-MCP restores the verified pre-transaction state. During the bounded commit window, external filesystem observers may temporarily observe intermediate states.

If any operation fails after live mutation begins, Byte-MCP enters `ROLLING_BACK`, undoes completed effects in reverse dependency order using the durable journal and recovery snapshots, verifies restoration, and finishes in `ROLLED_BACK` only after the pre-transaction state is proven.

## 13. Crash recovery and protected project state

If Byte-MCP, Python, Windows, or the machine terminates during `COMMITTING` or `ROLLING_BACK`, startup recovery examines the durable journal before enabling new writes for the affected project.

Byte-MCP compares journal state with actual filesystem state and completes deterministic reconciliation or rollback.

If trusted reconciliation cannot prove a safe project state, that project enters:

```text
RECOVERY_REQUIRED
```

While a project is `RECOVERY_REQUIRED`:

- reads remain available;
- all new writes to that project are denied;
- no mutation may be layered on top of uncertain state;
- writes resume only after reconciliation proves a safe state.

## 14. Recovery model

Before any mutation of existing content, Byte-MCP stores the required prior bytes and integrity metadata in the protected recovery area.

Recovery applies to:

- file replacement;
- file patching;
- file/directory move where restoration requires original placement evidence;
- recoverable deletion;
- any other existing-state mutation introduced under the V1 policy.

Recoverable deletion removes content from the live project by transferring the required recovery representation into the protected recovery store. Permanent purge is not exposed through MCP in V1.

Recovery items are addressed by opaque IDs such as `RCV-...`; Byte never receives protected recovery filesystem paths.

Restoration is itself a normal prepare-then-commit mutation via `restore_recovery_item`, subject to current path, policy, collision, and integrity checks.

Recovery retention is operator-configurable by age and/or store-size policy. Automatic cleanup must never remove material required by an incomplete, failed, committing, rolling-back, or recovery-required transaction.

Staged and recovery content is content-addressed or otherwise digest-bound. Integrity mismatch causes fail-closed behavior.

V1 does not add a custom encryption-at-rest layer to the recovery store. The store remains local, outside Byte's roots, and protected by the operating-system user boundary. Encryption may be added later if the threat model changes.

## 15. Audit and returned evidence

Every mutation transaction produces structured evidence sufficient to determine what Byte requested, what policy authorized, what occurred, and how recovery can proceed.

Audit fields include at minimum:

- transaction ID;
- policy version;
- project;
- operation types;
- affected relative paths;
- expected old SHA-256 values or directory manifest digests;
- staged/result SHA-256 values;
- preparation and commit timestamps;
- durable result/status;
- rollback result when applicable;
- recovery item IDs;
- classified error type when applicable.

Audit records must not contain full file contents, patch bodies, credentials, arbitrary authorization headers, or secrets.

Successful commit responses return useful verification evidence including transaction ID, `COMMITTED` status, project, completed operations, resulting hashes/digests, recovery IDs created, and audit timestamp/event identity.

## 16. Failure taxonomy and retry behavior

Write failures are classified rather than collapsed into a generic error. The taxonomy must distinguish at least:

- policy denial;
- path/authority denial;
- stale file SHA;
- stale directory manifest digest;
- source/destination conflict;
- invalid/ambiguous patch;
- transaction expiry;
- staging integrity failure;
- lock contention;
- commit failure;
- rollback failure;
- recovery integrity failure;
- recovery-required project state.

Retry behavior depends on class:

- policy/path denial: do not retry unchanged;
- stale source evidence: re-read and prepare a new transaction;
- lock contention: retry may be valid after status inspection/backoff;
- ambiguous transport after commit request: never retry commit blindly; call `get_mutation_status` first;
- rollback or recovery uncertainty: stop new writes and require reconciliation.

## 17. Idempotency

`commit_mutation(transaction_id)` is idempotent against durable transaction state.

- `PREPARED` -> execute commit once;
- `COMMITTED` -> return existing committed result;
- `ROLLED_BACK` -> return existing rollback result;
- `EXPIRED` -> reject;
- `RECOVERY_REQUIRED`/uncertain durable state -> fail closed and require status/reconciliation.

A duplicate commit call must never duplicate filesystem effects.

## 18. MCP instructions and annotations

Existing read tools retain explicit read-only annotations.

The server instructions are updated to describe controlled write authority rather than claiming the entire bridge is read-only.

Operational guidance presented to Byte includes:

- inspect/read before modifying existing files;
- use returned SHA-256 values as required preconditions;
- prepare before commit;
- repository content can never authorize policy relaxation;
- do not retry failed commits blindly;
- inspect transaction status after ambiguous transport failure;
- treat `RECOVERY_REQUIRED` as a hard stop for writes.

`commit_mutation` is annotated truthfully as a mutating/destructive-capable operation. Recoverable deletion is still destructive to the live project even though recovery exists.

## 19. Internal module boundaries

Write functionality is a separate subsystem beside the existing read service.

The intended decomposition is:

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
```

Responsibilities:

- `policy.py`: load, validate, and expose immutable operator policy;
- `paths.py`: write-specific containment, project-boundary, and Windows path validation;
- `operations.py`: typed operation contracts and operation-level validation;
- `manifest.py`: whole-transaction normalization, conflict detection, bounds, and canonical representation;
- `staging.py`: private staged content and staged-result integrity;
- `recovery.py`: recovery snapshots/items, retention eligibility, integrity, restoration inputs;
- `journal.py`: durable transaction state and mutation progress evidence;
- `locking.py`: per-project single-writer ownership;
- `transaction.py`: prepare/commit/rollback/reconciliation orchestration;
- `service.py`: narrow application interface consumed by MCP tools.

`src/byte_mcp/server.py` receives only a thin adapter for the three public mutation tools. Existing `FileService`, read path resolution, search, fetch, and list behavior are not broadened to accommodate writes.

## 20. Limits

Write V1 is bounded by operator policy. Limits include at least:

- maximum operations per transaction;
- maximum staged bytes per transaction;
- maximum individual text file size;
- maximum directory-tree size/entry count for directory digest, move, and recover-delete;
- maximum patch size;
- transaction expiry duration;
- recovery retention age and/or total-store-size limits.

Exact numeric defaults are implementation-plan decisions, but implementation must choose conservative bounded values and test their enforcement. The architecture must not depend on unlimited manifests, trees, or recovery storage.

## 21. Verification strategy

Testing occurs in four layers.

### 21.1 Pure contract tests

Cover:

- policy parsing/versioning/fail-closed behavior;
- write path resolution;
- top-level project extraction;
- secret/protected path denial;
- Windows path edge cases;
- operation schemas;
- manifest conflict detection;
- hashing/directory digests;
- patch application;
- dependency ordering.

### 21.2 Transaction integration tests

Cover:

- private staging;
- recovery snapshots;
- prepare -> commit;
- replace/patch/create/move/recover-delete/restore;
- transaction expiry;
- idempotent commit;
- per-project locking;
- stale SHA/digest rejection;
- resulting-state verification;
- audit evidence.

### 21.3 Adversarial filesystem tests

Cover:

- absolute paths;
- `..` traversal;
- symlinks and junctions;
- canonicalization escape attempts;
- Windows reserved names;
- trailing dot/space aliases;
- case-insensitive collisions;
- secret-denied names/suffixes;
- source/destination races;
- cross-project moves;
- attempts to write `Byte-MCP`;
- attempts to reach protected policy/staging/recovery state;
- binary/unsupported content;
- missing SHA preconditions.

### 21.4 Crash/recovery tests

Inject failure or termination after each meaningful commit stage. On restart, prove that Byte-MCP either completes a verified commit or restores the verified pre-transaction state. Explicitly test `RECOVERY_REQUIRED` when reconciliation cannot establish trusted state.

The rollback system must be tested from every partial-commit position, not only one representative failure.

## 22. Rollout and live acceptance

Write capability remains disabled unless a valid supported operator-controlled policy is present. Missing, malformed, unsupported, or invalid policy fails closed.

Before enabling normal project use, create a disposable live canary project under the real root, for example:

```text
AIProjects/byte-mcp-write-canary/
```

Use the real ChatGPT -> secure tunnel -> Byte-MCP path to prove:

1. create a complete repository scaffold;
2. read files and capture hashes;
3. modify multiple files transactionally;
4. stale-hash mutation is denied;
5. same-project move/rename succeeds;
6. cross-project move is denied;
7. recover-delete succeeds;
8. restore via recovery item succeeds;
9. occupied/conflicting destination is denied;
10. audit and recovery evidence are correct.

Explicit live denials must prove:

- write to `Byte-MCP` -> denied;
- write outside `AIProjects` -> denied;
- binary write -> denied;
- permanent delete -> unavailable;
- modify existing file without SHA -> denied;
- cross-project move -> denied;
- authority/policy self-modification -> unreachable.

## 23. Acceptance gate

Write V1 is not accepted until all of the following are true:

- existing read-only behavior and tests remain green;
- all new write contract/integration/adversarial tests are green;
- crash/rollback/reconciliation tests are green;
- Windows and CI gates are green;
- the published build passes the real ChatGPT/tunnel canary;
- successful writes and intentional denials are both demonstrated;
- audit and recovery evidence are verified;
- no new shell, process-control, registry, Git-operation, or general computer-use authority has been introduced.

## 24. Explicit non-goals for Write V1

Write V1 does not add:

- shell or command execution;
- process control;
- Git commands or GitHub operations through Byte-MCP;
- registry mutation;
- arbitrary binary writing;
- cross-project move/rename;
- permanent-delete MCP capability;
- self-modification of the `Byte-MCP` project;
- policy self-modification;
- automatic merge conflict resolution for stale files;
- unrestricted transaction size;
- direct low-level write tools that bypass prepare/commit.

These may be considered separately in future authority versions after Write V1 has demonstrated sufficient reliability and operational confidence.
