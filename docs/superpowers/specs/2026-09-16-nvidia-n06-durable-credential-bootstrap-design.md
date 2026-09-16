# NVIDIA-06 Durable Credential Bootstrap — Design Specification

**Date:** 2026-09-16
**Status:** Approved design, pending implementation plan
**Project:** Byte-MCP / NVIDIA governed platform
**Production baseline:** `a1a9bdbad6ba3990226ae01f622f11a5a799879a`
**Target platform:** Windows 11 / PowerShell 7 / Byte-MCP local runtime
**Provider execution during implementation/setup:** forbidden until a separately authorized post-promotion canary

## 1. Purpose

NVIDIA-06 converts the currently proven but ephemeral NVIDIA credential bootstrap into a durable production credential path for Byte-MCP.

The current NVIDIA query path is live-qualified end to end, but the credential exists only in the running Byte-MCP daemon after an operator-session bootstrap. Restarting Byte-MCP or Windows removes that inherited process credential and returns NVIDIA operations to `CREDENTIAL_UNAVAILABLE`.

NVIDIA-06 must make NVIDIA capability survive ordinary daemon and machine restarts without weakening the existing credential boundary.

The design uses Windows Data Protection API (DPAPI), scoped to the current Windows user, to protect the NVIDIA API key at rest. The Byte-MCP launcher decrypts the credential only during startup, injects it into the child daemon's process environment, then clears its own plaintext/process-scope copy.

The NVIDIA application layer remains unchanged: it continues to consume only `NVIDIA_API_KEY` through the existing settings/transmit boundary.

## 2. Goals

NVIDIA-06 must provide all of the following:

1. Durable encrypted storage for the NVIDIA hosted API credential.
2. Automatic Byte-MCP daemon credential inheritance on normal startup.
3. No plaintext credential file.
4. No credential in Git, tracked configuration, ChatGPT, MCP schemas, audit logs, command-line arguments, User environment variables, or Machine environment variables.
5. Explicit setup, replacement, validation, and removal commands.
6. Graceful Byte-MCP startup when the credential is absent or unusable.
7. Clear status receipts that reveal only safe metadata.
8. Provider-free setup, testing, qualification, promotion, and restart validation.
9. A separately authorized single live NVIDIA canary only after durable credential qualification has passed.
10. Failure-aware documentation and regression tests covering important credential failure boundaries.

## 3. Non-goals

NVIDIA-06 does not:

- change `nvidia_query`, `nvidia_review`, or `nvidia_get_review` public MCP signatures;
- change the frozen model registry;
- add automatic retry, fallback, model substitution, or provider discovery;
- persist the credential in a `.env` file;
- persist the credential in Windows User or Machine environment variables;
- send the credential to ChatGPT or the MCP client;
- store the plaintext credential in source files, receipts, logs, audit JSONL, test fixtures, shell history, or command-line arguments;
- introduce a multi-user or service-account secret-management platform;
- add cloud secret storage;
- make NVIDIA a mandatory dependency for Byte-MCP startup;
- perform a provider request during credential setup or validation.

## 4. Security model

### 4.1 Protected-at-rest credential

The encrypted credential is stored outside the repository under:

`%USERPROFILE%\.byte-mcp\secrets\nvidia-api-key.dpapi`

Protection uses Windows DPAPI with `DataProtectionScope.CurrentUser`.

Consequences:

- the encrypted blob is bound to the current Windows user context;
- copying the blob to another user account is not a supported migration path;
- copying the blob to another machine is not a supported migration path;
- loss of the Windows user profile / DPAPI master-key material may make the blob unrecoverable;
- credential rotation is the recovery mechanism when decryption can no longer succeed.

### 4.2 Plaintext lifetime

Plaintext may exist only:

1. in the secure input conversion boundary during credential setup;
2. briefly in the credential-management process during DPAPI protect/unprotect;
3. in the launcher process while `NVIDIA_API_KEY` is injected for child creation;
4. in the Byte-MCP daemon process after inheritance.

The launcher must remove `Env:NVIDIA_API_KEY` from its own process immediately after the daemon has been started.

Credential-management code must not print the value, any prefix, suffix, hash, length, encoded form, or encrypted bytes.

### 4.3 Persistent environment invariants

At all times:

- `NVIDIA_API_KEY` User environment variable = absent.
- `NVIDIA_API_KEY` Machine environment variable = absent.

NVIDIA-06 scripts must never call `SetEnvironmentVariable(..., "User")` or `SetEnvironmentVariable(..., "Machine")` for the credential.

### 4.4 Repository invariants

No protected blob is stored inside the repository.

Tracked files must contain no NVIDIA credential literal. Static tests must reject obvious hosted-key material such as `nvapi-...` in tracked source/test/docs paths, except deliberately synthetic non-secret patterns that cannot be mistaken for a usable credential.

## 5. Architecture

NVIDIA-06 introduces a narrow Windows-launcher credential subsystem.

```text
Operator
  |
  | Setup-NvidiaCredential.ps1
  v
SecureString input
  |
  v
Launcher.Nvidia.ps1
  |
  | DPAPI CurrentUser
  v
~\.byte-mcp\secrets\nvidia-api-key.dpapi
  |
  | startup
  v
Start-ByteMCP.ps1
  |
  | decrypt locally
  | set process-scope NVIDIA_API_KEY
  | spawn daemon
  | clear launcher process variable
  v
Byte-MCP daemon
  |
  | existing settings/transmit boundary
  v
NVIDIA hosted API
```

The new credential subsystem belongs to the launcher layer. NVIDIA Python execution code must not learn how DPAPI works and must not read the protected blob directly.

## 6. File-level design

### 6.1 Create `scripts/Launcher.Nvidia.ps1`

This is the only reusable implementation module for NVIDIA credential persistence.

It owns:

- protected credential path resolution;
- DPAPI protection;
- DPAPI unprotection;
- safe file creation/replacement;
- ACL hardening/validation;
- temporary process-scope injection;
- process-scope cleanup;
- safe credential-store status.

Required internal functions:

- `Get-NvidiaCredentialPath`
- `Protect-NvidiaCredential`
- `Unprotect-NvidiaCredential`
- `Test-NvidiaCredentialStore`
- `Import-NvidiaCredentialForChildProcess`
- `Clear-NvidiaCredentialFromCurrentProcess`

The implementation may add narrowly scoped helper functions for atomic file replacement, ACL inspection, byte zeroing, and SecureString conversion when required.

The module must not:

- contact NVIDIA;
- import provider clients;
- invoke MCP provider tools;
- call OX or Wolfram;
- print credential content;
- create User/Machine environment variables.

### 6.2 Create `scripts/Setup-NvidiaCredential.ps1`

Purpose: initial credential enrollment and explicit rotation.

Default behavior:

- fail if a protected credential already exists;
- require `-Replace` to rotate an existing credential;
- obtain the API key via `Read-Host -AsSecureString`;
- protect with DPAPI CurrentUser;
- write through a temporary file in the same secrets directory;
- validate decryption before replacement becomes final;
- atomically replace the protected blob;
- validate file ACL;
- leave the currently running daemon untouched;
- report `DAEMON_RESTART_REQUIRED=YES`;
- make zero provider requests.

No API key may be accepted as a normal command-line parameter.

### 6.3 Create `scripts/Test-NvidiaCredential.ps1`

Purpose: provider-free health test of the durable credential store.

It verifies:

- protected blob exists;
- blob is non-empty;
- DPAPI decryption succeeds;
- decrypted credential is non-empty;
- User environment variable absent;
- Machine environment variable absent;
- credential ACL acceptable;
- no tracked-file mutation;
- no provider call.

It must not print any secret-derived metadata beyond presence/health.

### 6.4 Create `scripts/Remove-NvidiaCredential.ps1`

Purpose: explicit removal.

Default behavior:

- remove only the protected NVIDIA credential blob;
- do not modify User/Machine environment variables other than verifying they remain absent;
- do not modify other Byte-MCP secrets;
- do not contact NVIDIA;
- do not restart Byte-MCP automatically;
- report that an already-running daemon may retain its inherited credential until restarted;
- report `DAEMON_RESTART_REQUIRED=YES` when a live daemon may still contain the old credential.

Removal should be idempotent: absence of the credential file is a safe terminal state.

### 6.5 Modify `scripts/Start-ByteMCP.ps1`

Startup gains a credential-preparation stage before daemon creation.

Behavior:

1. dot-source `Launcher.Nvidia.ps1`;
2. inspect credential-store state;
3. when valid, decrypt and set process-scoped `NVIDIA_API_KEY`;
4. launch the Byte-MCP daemon using the established launcher path;
5. always clear the launcher's process-scoped `NVIDIA_API_KEY` after child creation;
6. clear/zero temporary plaintext variables where feasible;
7. continue normal startup health checks.

If the credential is missing:

- Byte-MCP still starts;
- launcher reports a safe NVIDIA credential state of unavailable;
- NVIDIA operations later fail with existing `CREDENTIAL_UNAVAILABLE`.

If the credential is present but corrupt / undecryptable / ACL-invalid:

- default fail-safe behavior is **not to inject the credential**;
- Byte-MCP still starts unless an existing launcher policy makes startup impossible for unrelated reasons;
- launcher emits a safe warning/status;
- NVIDIA remains unavailable until the credential is repaired.

NVIDIA-06 must not make optional provider credentials a readiness requirement for the whole MCP server.

### 6.6 Modify launcher common code only if necessary

`Launcher.Common.ps1` may be changed only where an existing shared lifecycle hook is the correct integration point.

Do not place NVIDIA cryptography or provider-specific secret logic into shared launcher code unless it is genuinely generic and necessary.

### 6.7 Tests

Add focused Windows/PowerShell credential tests under the repository's established launcher test structure. If no suitable launcher test directory exists, create:

`tests/launcher/`

with NVIDIA-specific tests isolated from provider execution.

At minimum cover:

- initial protected-store creation;
- setup refuses overwrite without `-Replace`;
- replacement succeeds atomically;
- removal succeeds;
- repeated removal is safe;
- corrupted blob is rejected;
- wrong/unavailable DPAPI identity is surfaced safely where testable;
- missing blob does not prevent Byte-MCP startup;
- launcher injects credential only into child startup environment;
- launcher parent process is cleared afterward;
- User env remains absent;
- Machine env remains absent;
- no provider/network code exists in credential scripts;
- no command-line API-key parameter exists;
- no credential appears in receipts/log output;
- credential path is outside repository;
- startup still exposes exact 8-tool production MCP surface;
- NVIDIA Python credential boundary is unchanged.

## 7. Protected file format

The file is an opaque DPAPI ciphertext blob.

It does not need an application-level JSON envelope in V1.

Reasoning:

- DPAPI already authenticates/decrypts the protected payload for the bound user;
- a versioned JSON wrapper would add parsing surface and could accidentally encourage metadata persistence;
- the storage contract is intentionally one secret / one file / one purpose.

If future migration requires format versioning, add it in a later design.

## 8. ACL policy

The secrets directory and NVIDIA credential file must not intentionally grant broad write access.

The implementation must inspect the resulting Windows ACL and reject obviously unsafe states.

Minimum policy:

- current user retains required access;
- SYSTEM / Administrators inheritance may remain when supplied by the Windows profile hierarchy;
- broad principals such as `Everyone` must not have write/full-control access;
- the implementation must not attempt brittle wholesale ACL replacement when inherited profile ACLs are already safe.

ACL validation must be deterministic enough for tests but conservative enough not to damage the user's profile permissions.

## 9. Atomic update policy

Setup/rotation must not overwrite the only valid credential in-place before the replacement has been verified.

Required sequence:

1. obtain new credential;
2. DPAPI-protect it;
3. write protected bytes to a unique temporary file in the same directory;
4. validate the temporary file by decrypting it;
5. validate ACL;
6. atomically replace/move into the final path;
7. validate the final file again;
8. remove temporary artifacts.

If any pre-replacement step fails, preserve the existing credential unchanged.

## 10. Startup failure semantics

Credential status is separate from server readiness.

Safe states:

- `AVAILABLE`: protected store valid and injected into daemon startup.
- `ABSENT`: protected store missing; daemon starts without NVIDIA.
- `INVALID`: protected store exists but cannot be safely used; daemon starts without NVIDIA and reports safe diagnostic status.

No credential state automatically causes a provider call.

No credential failure authorizes a retry or model substitution.

## 11. Receipts and logging

Safe receipt fields may include:

- credential store path category (not secret content);
- store exists yes/no;
- protection scope `CurrentUser`;
- decryption probe PASS/FAIL;
- ACL validation PASS/FAIL;
- User env absent/present;
- Machine env absent/present;
- daemon restart required yes/no;
- daemon credential injection performed yes/no;
- provider calls = 0.

Forbidden:

- API key;
- API key substring;
- API key length;
- API key hash;
- ciphertext/base64 ciphertext;
- SecureString serialization;
- authorization headers;
- raw exception text if it can contain sensitive data.

## 12. Failure engineering

Extend `FAILURE_MAP.md` with NVIDIA-06 credential boundaries. Exact IDs should continue after the current map's last assigned ID.

Required boundaries:

### Protected credential missing

Observable: NVIDIA durable store absent.

Recovery: run setup; restart Byte-MCP.

Do not: fall back to plaintext persistence.

### Protected credential corrupt / DPAPI decrypt failure

Observable: protected store exists but cannot be decrypted under current user context.

Recovery: rotate/re-enroll credential.

Do not: dump ciphertext/plaintext or weaken scope.

### Unsafe credential-file ACL

Observable: ACL validation fails.

Recovery: repair/recreate protected store under safe profile permissions.

Do not: continue injecting a credential from an unsafe store.

### Atomic replacement failure

Observable: rotation fails before final replacement.

Recovery: retain old credential and investigate local filesystem/ACL conditions.

Do not: delete the known-good credential preemptively.

### Launcher injection failure

Observable: valid protected store exists but daemon is launched without inherited credential.

Recovery: inspect launcher inheritance and restart path.

Do not: persist User/Machine environment values as a workaround.

### Stale daemon credential after rotation/removal

Observable: disk state has changed but existing daemon still holds previously inherited credential.

Recovery: controlled Byte-MCP restart.

Do not: assume file rotation/removal revokes credentials from a running process.

### Wrong Windows identity / profile

Observable: DPAPI-protected store cannot be decrypted in a different Windows user context.

Recovery: enroll a credential under the intended runtime account.

Do not: copy or weaken DPAPI protection to share secrets between users.

## 13. Qualification contract

NVIDIA-06 qualification is provider-free.

Before any live canary:

1. all credential unit/integration tests pass;
2. exact production MCP surface remains 8 tools;
3. exact NVIDIA surface remains 3 tools;
4. NVIDIA Python provider path remains unchanged except where explicitly approved;
5. User env absent;
6. Machine env absent;
7. source tree secret scan passes;
8. credential-management scripts contain no provider/network invocation;
9. setup/replace/test/remove exercises consume zero provider calls;
10. daemon restart using the durable store succeeds;
11. parent launcher process credential is cleared;
12. runtime worktree clean;
13. `FAILURE_MAP.md` updated;
14. full NVIDIA regression passes;
15. supported broad regression passes;
16. Ruff / compile / diff checks pass;
17. provider-free promotion succeeds;
18. a subsequent controlled restart requires no manual API-key entry and still reports durable credential availability.

Only after those gates pass may the operator separately authorize exactly one NVIDIA live canary.

## 14. Live qualification canary

The live canary is a separate milestone from credential setup.

Requirements:

- fresh explicit operator authorization;
- exactly one `nvidia_query` call;
- alias `lightning`;
- no retries;
- no fallback;
- no substitution;
- no formal review;
- safe non-project prompt;
- one terminal outcome;
- audit/receipt captured;
- no second request regardless of result.

Passing the canary qualifies the durable credential path, not the provider generally beyond the already-established NVIDIA query qualification.

## 15. Rotation procedure

1. run `Setup-NvidiaCredential.ps1 -Replace`;
2. verify provider-free store receipt;
3. perform controlled Byte-MCP restart;
4. confirm launcher reports durable credential injection;
5. optionally perform a separately authorized canary if rotation itself requires live validation.

Rotation never silently sends a provider request.

## 16. Removal procedure

1. run `Remove-NvidiaCredential.ps1`;
2. verify protected file absent;
3. controlled restart Byte-MCP;
4. confirm server remains READY;
5. confirm NVIDIA path returns local `CREDENTIAL_UNAVAILABLE` only if explicitly invoked later.

Removal itself performs zero provider calls.

## 17. Recovery and rollback

NVIDIA-06 source changes follow the normal governed promotion model:

- implement in an isolated source/worktree;
- qualify provider-free;
- commit;
- promote exact commit;
- retain exact predecessor commit;
- automatic rollback on failed runtime promotion when safe.

Credential-data rollback differs from source rollback:

- source rollback must never restore or copy plaintext credentials;
- credential rotation failure preserves the prior encrypted blob until replacement is verified;
- removing NVIDIA-06 source code does not delete the encrypted credential automatically;
- credential removal is always an explicit operator action.

## 18. Acceptance criteria

NVIDIA-06 is complete only when all of the following are demonstrated:

```text
DPAPI_PROTECTED_CREDENTIAL=PASS
DPAPI_SCOPE=CURRENT_USER
PLAINTEXT_SECRET_FILE=NONE
SOURCE_SECRET_SCAN=PASS

NVIDIA_API_KEY_USER=ABSENT
NVIDIA_API_KEY_MACHINE=ABSENT

SETUP_PROVIDER_CALLS=0
ROTATION_PROVIDER_CALLS=0
TEST_PROVIDER_CALLS=0
REMOVAL_PROVIDER_CALLS=0

BYTE_MCP_START_WITHOUT_CREDENTIAL=PASS
BYTE_MCP_START_WITH_DURABLE_CREDENTIAL=PASS

DAEMON_CREDENTIAL_INHERITANCE=PASS
LAUNCHER_PARENT_CREDENTIAL_CLEARED=PASS

RESTART_WITHOUT_MANUAL_KEY_ENTRY=PASS
PRODUCTION_MCP_TOOL_COUNT=8
NVIDIA_MCP_TOOL_COUNT=3
RUNTIME_WORKTREE_CLEAN=PASS

FAILURE_MAP_UPDATED=PASS
NVIDIA_REGRESSION=PASS
SUPPORTED_BROAD_REGRESSION=PASS
STATIC_GATES=PASS
PROVIDER_FREE_PROMOTION=PASS
```

A final separately authorized single Lightning canary must then demonstrate the durable startup path end to end.

## 19. Design decisions frozen for implementation

The following decisions are intentionally frozen:

- DPAPI `CurrentUser`, not Credential Manager.
- Protected file outside repository at `%USERPROFILE%\.byte-mcp\secrets\nvidia-api-key.dpapi`.
- One opaque protected blob, no JSON envelope in V1.
- Setup via secure interactive prompt only.
- Rotation requires explicit `-Replace`.
- Setup/rotation/removal do not restart Byte-MCP automatically.
- Start-ByteMCP performs automatic safe credential injection.
- Missing/invalid NVIDIA credential does not block Byte-MCP server startup.
- No User/Machine environment persistence.
- No provider request during setup or provider-free qualification.
- Existing NVIDIA Python credential/settings boundary remains the consumer contract.
- Live validation requires a new explicit single-request authorization after provider-free qualification.
