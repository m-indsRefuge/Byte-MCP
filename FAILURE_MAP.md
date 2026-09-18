# NVIDIA N05 Failure Map

This document is the living failure-engineering map for the governed NVIDIA platform in Byte-MCP.

## Scope and invariants

The NVIDIA platform has two deliberately different execution surfaces:

- `nvidia_query`: routine governed inference through friendly model aliases.
- `nvidia_review`: evidence-heavy formal review with PREPARE, exact request identity, human approval, one provider request, and append-only evidence.
- `nvidia_get_review`: provider-free local evidence retrieval.

Global invariants:

- No automatic retry.
- No automatic fallback.
- No dynamic `/v1/models` discovery in governed query or review execution.
- No arbitrary provider model IDs on public MCP surfaces.
- No provider substitution.
- Credentials are acquired only at the settings/transmit boundary.
- Prompt text, response text, credentials, authorization headers, and raw provider bodies are excluded from routine query audit records.
- A provider-started review without a trustworthy terminal event is never retransmitted automatically.
- A failure never authorizes a second provider request.

## Failure matrix

| ID | Failure boundary | Observable state | First diagnostics | Safe recovery | Do not | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | `CREDENTIAL_UNAVAILABLE` | Local failure before provider execution; `provider_started=false`. | Confirm hosted NVIDIA credential configuration through the settings boundary. | Configure/correct the hosted credential, then make a new explicit invocation. | Do not use `NGC_API_KEY` as a hosted fallback. Do not persist the credential. | `tests/nvidia/test_settings.py`, `tests/nvidia/test_query_service.py`, `tests/nvidia/test_n02_security_invariants.py` |
| F02 | `AUTHENTICATION_FAILED` | Provider rejects authentication/permission; request is rejected. | Check credential validity and account/model entitlement. | Correct authentication or entitlement, then explicitly invoke again. | Do not retry automatically. Do not expose provider prose or headers. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_errors_platform.py` |
| F03 | `RATE_LIMITED` | Typed rate-limit failure after one request attempt. | Confirm provider rate-limit status and request timing outside the harness. | Wait or resolve quota/rate conditions, then make a fresh explicit invocation. | Do not back off and retry inside Byte-MCP. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_errors_platform.py` |
| F04 | `PROVIDER_REJECTED` | Provider rejection that is not safely classified as a local validation failure. | Inspect safe status/error classification; keep raw provider prose out of logs. | Correct the request/account condition and explicitly invoke again. | Do not silently substitute a model or endpoint. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_chat_response.py` |
| F05 | `TRANSPORT_FAILED` / NOT_SENT | Connect or pool failure where transmission is classified `NOT_SENT`. | Inspect safe transport failure kind and network reachability. | Correct transport conditions, then start a fresh explicit invocation. | Do not auto-retry. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_n01_security_invariants.py` |
| F06 | `TRANSPORT_FAILED` / OUTCOME_UNKNOWN | Failure after transmission may have begun; provider outcome is ambiguous. | Inspect `ProviderAttemptOutcome` and transport observation metadata. | Query calls require a fresh explicit invocation. Formal review remains blocked by evidence/replay rules when provider start is recorded without a terminal event. | Do not replay the same formal review attempt. | `tests/nvidia/test_chat_execution.py`, `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_review_service_transmit.py` |
| F07 | `RESPONSE_INVALID` | Provider started, but response structure, identity, or required content is invalid. | Check model identity, request SHA binding, payload SHA binding, and bounded response parser. | Treat result as unusable; investigate parser/provider behavior before a fresh explicit call. | Do not return partially trusted content. | `tests/nvidia/test_chat_response.py`, `tests/nvidia/test_query_service.py` |
| F08 | `RESPONSE_TOO_LARGE` | Provider response exceeds the governed query bound. | Compare response size with `MAX_QUERY_RESPONSE_CHARS`. | Tighten the request or model output expectation, then explicitly invoke again. | Do not bypass the bound or persist the oversized body in audit. | `tests/nvidia/test_query_service.py`, `tests/nvidia/test_chat_response.py` |
| F09 | `MODEL_NOT_ALLOWED` | Unknown alias or raw provider model ID rejected locally. | Check the frozen friendly-alias registry. | Use an allowed friendly alias. | Do not accept arbitrary provider IDs. | `tests/nvidia/test_models.py`, `tests/nvidia/test_query_protocol.py`, `tests/nvidia/test_n04_governed_model_selection.py` |
| F10 | `MODEL_NOT_ENABLED` | Known model is disabled for the requested surface. | Inspect governed model definition and per-surface enablement. | Enable only through a reviewed registry change and qualification cycle. | Do not override enablement from the MCP request. | `tests/nvidia/test_models.py`, `tests/nvidia/test_errors_platform.py` |
| F11 | Registry mismatch | Model registry validation or qualification fails closed. | Run registry validation and offline qualification. | Correct the frozen registry definition, then rerun offline qualification. | Do not continue with a partially valid registry. | `tests/nvidia/test_models.py`, `tests/nvidia/test_qualification.py` |
| F12 | Dynamic discovery regression | Governed execution starts consulting `/v1/models` or catalog discovery. | Run N01/platform structural invariants and N05 offline qualification. | Remove discovery from governed execution and restore the frozen registry boundary. | Do not dynamically choose production model identity. | `tests/nvidia/test_n01_security_invariants.py`, `tests/nvidia/test_platform_security_invariants.py`, `tests/nvidia/test_query_service.py` |
| F13 | Retry/fallback regression | Loop, retry, fallback, or substitution machinery appears in governed query/transport code. | Run AST-based security invariants and N05 offline qualification. | Remove the machinery; preserve one explicit attempt per invocation. | Do not mask failures with a second provider request. | `tests/nvidia/test_n01_security_invariants.py`, `tests/nvidia/test_query_service.py`, `tests/nvidia/test_platform_security_invariants.py` |
| F14 | Audit persistence failure | Query result cannot be safely audited; executor has already run at most once. | Inspect local audit path/permissions and the query audit recorder. | Repair audit persistence before the next explicit invocation. | Do not reinvoke the provider to repair an audit failure. | `tests/nvidia/test_query_audit.py`, `tests/test_audit.py` |
| F15 | Audit privacy regression | Prompt, system prompt, response, credential, or authorization material appears in audit. | Inspect raw audit JSONL and metadata schema. | Remove unsafe fields and rotate any compromised secret if applicable. | Do not store raw query/response content in routine query audit. | `tests/nvidia/test_query_audit.py`, `tests/nvidia/test_n02_security_invariants.py` |
| F16 | Review evidence corruption | Manifest/event/evidence content is malformed, missing, or hash-inconsistent. | Load review evidence locally and verify immutable identities/hashes. | Repair only through a new governed review lifecycle when necessary; preserve original evidence. | Do not rewrite append-only evidence to make it pass. | `tests/nvidia/test_review_evidence.py`, `tests/nvidia/test_review_service_prepare.py` |
| F17 | Ambiguous review provider start | Provider start exists without a trustworthy terminal event. | Inspect review events for `provider_started_at` and terminal outcome. | Investigate manually; create a new review only under a new explicit lifecycle if justified. | Do not retransmit the same review attempt. | `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_review_service_transmit.py` |
| F18 | Review request/manifest mismatch | Approval hash, manifest identity, request body, model identity, or packet hash does not match immutable evidence. | Compare expected request SHA-256 and persisted manifest/request identities. | Prepare a new correct review if the intended request changed. | Do not mutate or approve around a hash mismatch. | `tests/nvidia/test_review_protocol.py`, `tests/nvidia/test_review_service_transmit.py`, `tests/nvidia/test_n04_immutable_model_identity.py` |
| F19 | Credential-boundary regression | Code outside settings/transmit starts naming or loading the hosted credential. | Run N02 credential-access invariant. | Move credential acquisition back to the settings/transmit boundary. | Do not inspect the credential in readiness, PREPARE, retrieval, or qualification paths. | `tests/nvidia/test_n02_security_invariants.py`, `tests/nvidia/test_qualification.py` |
| F20 | MCP surface regression | Extra NVIDIA tools, provider controls, static NVIDIA imports, or raw provider IDs appear publicly. | Inspect exact MCP tool set/signatures and server import AST. | Restore the three-tool governed surface and lazy import boundary. | Do not expose endpoint, API key, retry, fallback, temperature, token, seed, or raw model-ID controls. | `tests/nvidia/test_query_mcp.py`, `tests/nvidia/test_review_mcp.py`, `tests/nvidia/test_platform_security_invariants.py`, `tests/test_nvidia_runtime_integration.py` |
| F21 | Hosted request dialect drift | Provider starts but rejects an otherwise bounded governed request because a model-specific request field has changed or become unsupported. | Compare the canonical request body with the current provider model contract; inspect safe HTTP status and typed audit metadata. | Update only the frozen model-specific dialect, add canonical-body regression tests, rerun provider-free qualification, then require fresh live authorization. | Do not retry the rejected request, guess provider fields, dynamically discover a replacement model, or silently substitute providers. | `tests/nvidia/test_models.py`, `tests/nvidia/test_query_protocol.py`, `tests/nvidia/test_review_protocol.py`, `tests/nvidia/test_query_audit.py` |

## Failure propagation rules

Local validation failures must terminate before credential loading and before any provider attempt. Provider and transport failures must retain the safest available attempt classification without inventing certainty. Routine query audit records only safe operational metadata. Formal review failures are additionally constrained by immutable evidence and replay protection.

A query failure never causes a second provider call inside the same invocation. A review failure never consumes a second provider request unless a completely new, explicitly authorized review lifecycle is created under the review contract.

## First-response diagnostic order

1. Confirm whether failure was local or provider-started.
2. Confirm friendly model alias and governed model maturity.
3. Confirm request identity/hash when available.
4. Check typed failure code.
5. Check safe transport attempt outcome when applicable.
6. Check audit/evidence persistence.
7. For formal review, inspect provider-start and terminal evidence before considering any further action.
8. Run `scripts/nvidia_n05_offline_qualification.py` after code changes affecting NVIDIA governance.

## Recovery principles

- Prefer local correction over provider experimentation.
- Treat `OUTCOME_UNKNOWN` as ambiguous, not as a failed request that can safely be replayed.
- Preserve append-only evidence.
- Never solve a failure by weakening model governance, credential isolation, response bounds, audit privacy, or exact request identity.
- Any future automatic retry, fallback, model routing, or discovery feature requires a new design and explicit approval; it is not a repair.
## NVIDIA-06 durable credential bootstrap

### F22 — Protected NVIDIA credential store missing

- **Boundary:** The expected CurrentUser DPAPI credential blob at `%USERPROFILE%\.byte-mcp\secrets\nvidia-api-key.dpapi` does not exist when Byte-MCP starts.
- **Observable symptom:** `Test-NvidiaCredentialStore` reports `ABSENT`; launcher reports `NVIDIA_CREDENTIAL_STATE=ABSENT`; NVIDIA calls remain locally unavailable while the rest of Byte-MCP is allowed to start.
- **Likely causes:** Credential enrollment has never been run; the protected blob was intentionally removed; the user profile was restored without the `.byte-mcp\secrets` directory; or the launcher is running under a different profile.
- **First diagnostics:** Run `scripts\Test-NvidiaCredential.ps1`; confirm the expected path with `Get-NvidiaCredentialPath`; confirm User/Machine `NVIDIA_API_KEY` remain absent.
- **Propagation path:** Missing store → no process-scoped NVIDIA key imported → child daemon starts without NVIDIA credential → NVIDIA provider operations terminate locally at the existing credential boundary.
- **Safe recovery:** Run `scripts\Setup-NvidiaCredential.ps1` interactively under the intended Windows user, then restart the managed Byte-MCP daemon through the normal launcher path.
- **Data risk:** None from the missing blob itself; do not compensate by persisting the key in plaintext or in User/Machine environment variables.
- **Do not:** Do not fall back to `.env`, `setx`, source files, connector configuration, or a manually exported long-lived process key.
- **Related tests:** NVIDIA-06 missing-store state test; absent-store child-boundary test; persistent-environment static guards.

### F23 — DPAPI decrypt failure or corrupt protected blob

- **Boundary:** The credential blob exists but cannot be decrypted with Windows DPAPI CurrentUser, or decrypts to an empty/invalid value.
- **Observable symptom:** `Test-NvidiaCredentialStore` reports `INVALID`; startup reports `NVIDIA_CREDENTIAL_STATE=INVALID`; no NVIDIA credential is injected into the child.
- **Likely causes:** Blob corruption; copied credential file from another Windows identity/profile; DPAPI user master-key loss; truncated write; manual file modification.
- **First diagnostics:** Run `scripts\Test-NvidiaCredential.ps1`; verify the launcher is running under the expected Windows identity; inspect file presence and ACL metadata without printing blob contents.
- **Propagation path:** Existing blob → DPAPI unprotect fails or produces invalid plaintext → store classified `INVALID` → stale process key cleared → daemon starts without NVIDIA credential.
- **Safe recovery:** Preserve the invalid blob long enough for local diagnosis if needed, then re-enroll with `scripts\Setup-NvidiaCredential.ps1 -Replace` only when the existing store can be safely replaced; if replacement is intentionally impossible, remove and enroll anew using the lifecycle commands.
- **Data risk:** Repeated ad-hoc conversion or copying can destroy the only protected credential artifact; plaintext recovery attempts can leak the API key.
- **Do not:** Do not print ciphertext, decrypted text, secret length, prefixes/suffixes, hashes derived from the secret, or raw exception data that contains secret material.
- **Related tests:** Corrupt-store classification test; DPAPI round-trip test; child-boundary stale-key suppression test.

### F24 — Unsafe credential-file ACL

- **Boundary:** The protected credential file grants broad write/modify/full-control rights to identities such as Everyone, Users, or Authenticated Users.
- **Observable symptom:** ACL validation rejects the store; `Test-NvidiaCredentialStore` reports `INVALID`; setup/rotation validation fails before the credential is accepted.
- **Likely causes:** Inherited permissive directory ACLs; manual permission changes; copying the blob through a location that rewrites ACLs; third-party backup/restore tooling.
- **First diagnostics:** Inspect the ACL on the protected blob and its parent directory; identify broad allow rules with write, modify, full-control, create, append, permission-change, or ownership rights.
- **Propagation path:** Unsafe ACL → credential store rejected → no credential injection → NVIDIA unavailable to the daemon while non-NVIDIA Byte-MCP startup remains possible.
- **Safe recovery:** Correct the specific unsafe ACL inheritance or explicit broad-write grant while preserving required access for the current user and legitimate inherited SYSTEM/Administrators entries; rerun the provider-free credential test.
- **Data risk:** An attacker or unrelated local user with write access could replace the ciphertext and influence which secret is injected into the daemon.
- **Do not:** Do not wholesale replace profile ACL inheritance merely to make the test pass; do not broaden access to simplify troubleshooting.
- **Related tests:** Temporary-path DPAPI/ACL round-trip; ACL static contract; lifecycle validation checks.

### F25 — Atomic credential replacement failure

- **Boundary:** Enrollment or rotation fails while writing, verifying, or atomically replacing the protected credential blob.
- **Observable symptom:** Setup/rotation throws before reporting success; temporary same-directory blob may be cleaned up; the previously valid credential must remain authoritative if failure occurs before final replacement.
- **Likely causes:** Filesystem denial; antivirus/file lock; insufficient permissions; disk or profile filesystem error; failed temporary-blob validation; `File.Replace`/move failure.
- **First diagnostics:** Confirm whether the final credential file still decrypts and validates; inspect same-directory temporary/backup artifacts without reading their contents; review filesystem/ACL errors.
- **Propagation path:** New credential protection/write → temporary verification → atomic move/replace → final verification. A failure before replacement must not invalidate the old credential; a failure after replacement requires immediate final-store validation.
- **Safe recovery:** Resolve the filesystem or ACL cause, confirm the last known valid final blob, remove abandoned temporary/backup artifacts only after identity is clear, then rerun rotation explicitly with `-Replace`.
- **Data risk:** Incorrect recovery can delete the last valid protected credential or leave an unverified replacement in service.
- **Do not:** Do not truncate or overwrite the final credential in place; do not delete the old valid blob before the new same-directory temporary blob has been protected and verified.
- **Related tests:** DPAPI rotation replacement test; same-directory temporary cleanup test; verified replacement behavior.

### F26 — Launcher credential injection or cleanup failure

- **Boundary:** The final NVIDIA launcher layer cannot import the durable credential before child creation, or fails to clear process-scoped `NVIDIA_API_KEY` after delegation.
- **Observable symptom:** NVIDIA credential state is `ABSENT`/`INVALID` unexpectedly, daemon starts without NVIDIA access, or a launcher process retains `NVIDIA_API_KEY` after the child has been created.
- **Likely causes:** Invalid/missing store; regression in `Launcher.Nvidia.ps1`; incorrect dot-source order; wrapper override lost; exception between import and cleanup; future launcher refactor bypassing the NVIDIA layer.
- **First diagnostics:** Verify `Start-ByteMCP.ps1` dot-sources `Launcher.Wolfram.ps1` before `Launcher.Nvidia.ps1`; verify the final `Start-LauncherServerProcess`/foreground wrapper resolves from NVIDIA; run the child-boundary tests provider-free.
- **Propagation path:** Launcher clears stale key → validates/imports durable key → delegates to established Wolfram child-process creator → child inherits process environment → `finally` clears parent process key.
- **Safe recovery:** Restore the final NVIDIA launcher override and `try/finally` cleanup contract; rerun focused NVIDIA-06 tests and the full NVIDIA regression with the worktree `src` pinned.
- **Data risk:** Cleanup regression can retain plaintext credential material in the launcher process; ordering regression can cause the daemon to inherit no credential or a stale credential.
- **Do not:** Do not move cleanup around the top-level foreground stack, because foreground mode blocks after child creation; do not bypass the established Wolfram launcher environment snapshot/restore path.
- **Related tests:** Final-wrapper structure tests; stale-process-key clear-before-import test; child-boundary inheritance-and-cleanup test; dot-source-order test.

### F27 — Stale daemon after credential rotation or removal

- **Boundary:** The protected credential store changes, but an already-running Byte-MCP daemon continues using the credential value inherited when that daemon process was created.
- **Observable symptom:** Setup/remove reports `DAEMON_RESTART_REQUIRED=YES`; the protected store and the running daemon disagree about which NVIDIA credential is active.
- **Likely causes:** Credential was rotated or removed without restarting the managed daemon; operator assumed DPAPI file changes are read dynamically by the Python provider layer.
- **First diagnostics:** Check when the daemon was started relative to credential setup/rotation/removal; confirm the protected-store state separately from daemon state; do not make a provider request merely to identify the stale condition.
- **Propagation path:** Daemon child inherits process environment once at creation → later protected-store mutation does not alter that child environment → old credential remains resident until daemon termination.
- **Safe recovery:** Restart the managed Byte-MCP daemon through the normal launcher after enrollment, rotation, or removal. For removal, treat the old inherited credential as active until the old daemon is stopped.
- **Data risk:** A removed or superseded key can remain usable inside an existing daemon process longer than intended.
- **Do not:** Do not claim rotation/removal is operationally complete until the old daemon has been replaced; do not attempt in-process secret mutation as a shortcut.
- **Related tests:** Lifecycle receipts requiring restart; startup child-boundary contract; provider-free restart qualification in NVIDIA-06 promotion.

### F28 — Wrong Windows identity or user profile

- **Boundary:** Byte-MCP or the credential lifecycle command runs under a Windows identity/profile different from the identity that protected the DPAPI blob.
- **Observable symptom:** Expected credential path may be absent under the new profile, or the blob exists but DPAPI CurrentUser decrypt fails and the store is classified `INVALID`.
- **Likely causes:** Scheduled task/service account mismatch; elevated shell under a different identity; copied profile data; alternate admin account; runtime launched from another user's session.
- **First diagnostics:** Confirm the effective Windows identity and `%USERPROFILE%`; compare `Get-NvidiaCredentialPath` with the profile used during enrollment; verify the blob was not copied between users.
- **Propagation path:** Different identity/profile → different credential path and/or incompatible DPAPI CurrentUser protection → no valid import → daemon starts without NVIDIA credential.
- **Safe recovery:** Run Byte-MCP and credential lifecycle operations under the intended account, or deliberately enroll a separate protected credential for the intended runtime identity using the normal setup command.
- **Data risk:** Copying the blob between identities does not make it portable and can encourage insecure plaintext migration attempts.
- **Do not:** Do not weaken DPAPI scope, change to Machine scope, or export plaintext merely to make one blob work across users.
- **Related tests:** DPAPI CurrentUser round-trip; missing/corrupt store behavior; provider-free credential validation and startup qualification.

## BEL-02 read-only proxy subsystem

### BEL-02 service unavailable
- **Boundary:** Byte-MCP -> loopback BEL-02 MCP.
- **Observable symptom:** `Bel02ProxyError` reports BEL-02 unavailable.
- **Likely causes:** BEL-02 D0 not running, wrong local port, MCP protocol failure.
- **First diagnostics:** verify `http://127.0.0.1:8012/mcp` is listening and run the BEL-02 local smoke test.
- **Propagation:** only BEL-02 proxy tools fail; Byte-MCP core and other providers must remain available.
- **Safe recovery:** start or repair BEL-02, then retry the read-only request.
- **Data risk:** none for D0 read-only calls.
- **Do not:** bypass BEL-02 by running the requested command directly on the Byte-MCP host.

### Non-loopback BEL-02 URL configured
- **Boundary:** proxy configuration.
- **Observable symptom:** proxy initialization rejects the URL.
- **Likely cause:** `BYTE_MCP_BEL02_URL` points outside loopback or contains credentials/query data.
- **First diagnostics:** inspect only the configured URL value.
- **Propagation:** BEL-02 tools unavailable; Byte-MCP core unaffected.
- **Safe recovery:** restore a loopback `/mcp` URL on a high port.
- **Data risk:** prevented by fail-closed validation.
- **Do not:** weaken loopback validation to make a remote endpoint work.

### Unauthorized BEL-02 tool requested
- **Boundary:** fixed proxy allow-list.
- **Observable symptom:** `bel02_run` or another unapproved tool is rejected.
- **Likely cause:** caller attempted generic forwarding.
- **First diagnostics:** inspect requested tool name.
- **Propagation:** request fails locally before contacting BEL-02.
- **Safe recovery:** use only `bel02_status`, `bel02_git_status`, or `bel02_git_diff`.
- **Data risk:** none.
- **Do not:** expose a caller-supplied BEL-02 tool name in this milestone.

### BEL-02 receipt exceeds Byte-MCP response bound
- **Boundary:** returned evidence size.
- **Observable symptom:** proxy rejects the receipt instead of returning partial evidence.
- **Likely cause:** unexpectedly large Git diff or malformed/verbose downstream response.
- **First diagnostics:** reproduce locally against BEL-02 and inspect scope.
- **Propagation:** one proxy call fails; no mutation occurs.
- **Safe recovery:** narrow the downstream read operation before future promotion.
- **Data risk:** no silent truncation; evidence remains untrusted until inspected.
- **Do not:** report partial output as a complete receipt.

### MCP client compatibility drift
- **Boundary:** Byte-MCP MCP SDK -> BEL-02 MCP SDK.
- **Observable symptom:** initialization/transport failure after dependency upgrade.
- **Likely cause:** Streamable HTTP API or protocol-version drift.
- **First diagnostics:** run `tests/test_bel02_proxy.py`, then the live read-only smoke test.
- **Propagation:** BEL-02 proxy tools only.
- **Safe recovery:** revalidate the pinned SDK pair before changing either side.
- **Data risk:** none for read-only D0.
- **Do not:** silently fall back to host shell or direct Docker execution.

### Nested MCP client lifecycle hang

- **Boundary:** Byte-MCP -> BEL-02 internal proxy transport.
- **Observed symptom:** `bel02_status` and `bel02_git_status` returned, then the live Byte-MCP canary hung before `bel02_git_diff` completed.
- **Isolation evidence:** direct BEL-02 MCP `bel02_git_diff` returned the expected calculator diff with exit code 0; a raw bounded HTTP/JSON-RPC MCP sequence (`initialize -> status -> git status -> git diff`) also passed completely.
- **Cause classification:** the failure is isolated to the nested MCP SDK client/session lifecycle previously used by Byte-MCP, not to BEL-02, Docker, Codex, Git, or the canary repository.
- **Safe recovery:** use the fixed loopback-only bounded HTTP/JSON-RPC MCP adapter for the three approved read-only BEL-02 tools.
- **Propagation:** only BEL-02 proxy calls are affected; Byte-MCP core and unrelated provider tools remain independent.
- **Data risk:** no mutation occurred; `bel02_run` remains unexposed.
- **Do not:** add retries around an indefinitely hanging nested client session, weaken BEL-02 containment, or upgrade the entire Byte-MCP MCP SDK merely to bypass this isolated proxy transport defect.
- **Regression tests:** stateless MCP sequence, stateful session-header forwarding, timeout normalization, protocol-error rejection, and `bel02_run` denial in `tests/test_bel02_proxy.py`.

### Runtime validation environment lacks development dependencies

- **Boundary:** BEL-02 promotion verification in the deployed Byte-MCP runtime worktree.
- **Observable symptom:** `scripts/Check.ps1` invokes the runtime `.venv` and reports `No module named pip`, `No module named ruff`, and `No module named pytest`, but can continue to launcher tests and print a repository PASS.
- **Likely cause:** the deployed runtime virtual environment contains runtime dependencies only, while `Check.ps1` assumes development tooling is installed and does not fail closed on those native-command failures in the observed Windows PowerShell path.
- **First diagnostics:** inspect `.venv\Scripts` for `pip`, `ruff`, and `pytest`; record each native command exit code rather than trusting the final banner.
- **Propagation:** Python compile/lint/test qualification is skipped or fails before execution while the launcher-only suite may still pass.
- **Safe recovery:** use the known-good development interpreter against the runtime source tree with explicit import provenance and exit-code checks; repair `Check.ps1` separately from BEL-02 promotion.
- **Data risk:** none, but a false-positive validation receipt can authorize an unsafe promotion.
- **Do not:** install ad-hoc development packages into the deployed runtime environment merely to make promotion validation green.

### Repository pytest basetemp inaccessible

- **Boundary:** pytest setup/cleanup for the runtime worktree.
- **Observable symptom:** many otherwise unrelated tests fail during setup with `PermissionError: [WinError 5] Access is denied` while pytest attempts to remove `.pytest-tmp`.
- **Known evidence:** the failures share the same configured base-temp path; this is a harness/filesystem boundary, not hundreds of independent test failures.
- **First diagnostics:** inspect the path owner, ACL, attributes, and any process retaining handles before modifying it.
- **Propagation:** pytest cannot establish a clean base temp directory, so large portions of the suite error before test bodies execute.
- **Safe recovery for qualification:** run verification with a unique external `--basetemp` while leaving the inaccessible path untouched; investigate the stale path separately.
- **Data risk:** aggressive cleanup or permission resets can affect unrelated runtime state.
- **Do not:** weaken filesystem permissions, recursively take ownership, or treat setup errors as product-code regressions without evidence.
