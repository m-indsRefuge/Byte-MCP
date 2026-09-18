# OX Clean-Room Failure Map

This is the living failure-engineering map for the clean-room OX code-review subsystem. It describes the current implementation, not archived OX V1/V2 behavior.

The primary diagnostic rule is to locate the failure relative to `send.claim` before doing anything else:

```text
no send.claim  -> provider authority was not consumed; diagnose locally
send.claim     -> never replay the same review identity
```

`FAILED` means the implementation has enough evidence to classify a definite failure. `OUTCOME_UNKNOWN` means provider delivery/result or durable evidence cannot be established safely. Ambiguity is preserved rather than converted into retry permission.

## F01 — Repository/scope escape or link/junction boundary

- **Boundary:** Repository alias or bounded path escapes the configured `projects` root, is non-normalized/absolute, or traverses a symlink/junction component.
- **Observable symptom:** `OXRepositoryError`, `OXScopeError`, or `OXBundleError` before transport; no provider request. Directly selected links/junctions fail closed; links encountered during full traversal are recorded as exclusions and not followed.
- **Likely causes:** `..`, absolute path, nested repository alias, Windows drive prefix/backslash path, missing path, link/junction, or caller assumption that OX accepts arbitrary filesystem paths.
- **First diagnostic:** Confirm the repository is a direct child of the configured `projects` root; inspect the requested logical paths; inspect `snapshot.json` only if a snapshot was already persisted.
- **Propagation:** Invalid authority/scope -> scope/snapshot termination -> no send claim -> zero provider requests.
- **Safe recovery:** Correct the alias/path and create a new explicit review invocation.
- **Evidence/data risk:** Low if failure occurs before snapshot persistence; do not disclose absolute local paths while diagnosing.
- **Do not:** Do not broaden roots, resolve through links, normalize traversal into an accepted path, or substitute an absolute path.
- **Related tests:** `tests/ox/test_scope.py::test_repository_resolution_rejects_non_direct_or_unsafe_aliases`; `tests/ox/test_scope.py::test_repository_symlink_is_rejected_when_platform_supports_it`; `tests/ox/test_scope.py::test_bounded_scope_rejects_unsafe_or_non_normalized_paths`; `tests/ox/test_scope.py::test_bounded_scope_rejects_link_or_junction_components`; `tests/ox/test_snapshot.py::test_directly_selected_link_or_junction_fails_closed`; `tests/ox/test_service.py::test_invalid_repository_is_preclaim_and_zero_transport`.

## F02 — Sensitive exclusion or provider-bound secret detection

- **Boundary:** Snapshot policy encounters a known-sensitive file/material, or the final packet/request contains a strong private-key marker or the exact active provider credential.
- **Observable symptom:** Sensitive files are excluded and recorded in `snapshot.json`; exact credential/private-key detection raises `OXBundleError` before `send.claim` and before networking.
- **Likely causes:** `.env`, key/certificate/credential file, evidence/cache/build material, binary/non-text input, or an eligible source file/objective that accidentally contains the live gateway credential/private-key marker.
- **First diagnostic:** Check `snapshot.json` exclusions by logical path/reason. If the safety scan failed, inspect the eligible repository material locally without printing the credential or raw provider-bound body.
- **Propagation:** Known-sensitive path -> excluded from snapshot. Strong provider-bound secret indicator -> prepared evidence may exist -> safety preflight stops -> no send claim -> zero provider requests.
- **Safe recovery:** Remove the accidental secret from eligible review material or choose a scope that does not contain it, then start a new explicit review.
- **Evidence/data risk:** High if operators print or copy secret material during diagnosis. Restricted packet/request evidence can contain ordinary source content and must stay local.
- **Do not:** Do not silently redact and continue, echo the credential/marker, disable the scan, or move secret files into ordinary-looking filenames to bypass exclusions.
- **Related tests:** `tests/ox/test_snapshot.py::test_snapshot_excludes_sensitive_generated_large_and_non_text_material`; `tests/ox/test_security.py::test_private_key_markers_fail_closed_without_echo`; `tests/ox/test_security.py::test_exact_credential_fails_closed_without_echo`; `tests/ox/test_security.py::test_service_blocks_exact_credential_in_frozen_source_before_send`; `tests/ox/test_security.py::test_privacy_sentinel_matrix_keeps_restricted_evidence_private`.

## F03 — Artifact/inventory/aggregate/packet oversize

- **Boundary:** Snapshot or serialized provider-bound material exceeds the configured hard bounds.
- **Observable symptom:** A single file over 1,000,000 bytes is recorded as `artifact-too-large` and excluded from eligibility. More than 5,000 included artifacts, more than 3,250,000 included content bytes, an over-3,500,000-byte packet, or a request exceeding the shared prepared-request bound fails locally with `OXBundleError`/request preparation failure and zero provider requests.
- **Likely causes:** Large generated/text fixtures, unexpectedly broad repository scope, too many small files, or a review objective/inventory that pushes serialized packet/request size over the bound.
- **First diagnostic:** Inspect `snapshot.json` counts/exclusions if available; compare included artifact count/content bytes with the frozen constants; for packet/request failures use local byte counts/hashes rather than dumping raw content.
- **Propagation:** Per-artifact oversize -> exclusion. Hard included-inventory/packet/request oversize -> local termination before send claim/network.
- **Safe recovery:** Use a new bounded review that truthfully fits the limits, or deliberately revise the governed limits through a new design/qualification cycle.
- **Evidence/data risk:** Oversize evidence can contain large amounts of source code; avoid copying packet/request bodies into diagnostics.
- **Do not:** Do not truncate, summarize, split one review into multiple provider calls, or drop otherwise eligible included material merely to make a hard-bound review fit.
- **Related tests:** `tests/ox/test_snapshot.py::test_snapshot_excludes_sensitive_generated_large_and_non_text_material`; `tests/ox/test_snapshot.py::test_snapshot_rejects_more_than_maximum_artifact_count`; `tests/ox/test_snapshot.py::test_snapshot_rejects_aggregate_content_over_hard_limit`; `tests/ox/test_service.py::test_preclaim_build_failures_do_not_allocate_send_authority`; `tests/ox/test_security.py::test_provider_free_local_paths_never_open_network_connections`.

## F04 — Prepared-request identity/integrity mismatch

- **Boundary:** Canonical prepared request bytes, request SHA-256, or transmission context no longer match the frozen request authority.
- **Observable symptom:** Local `ValueError`/`OXBundleError` before transport; `send.claim` is not created when service preflight detects the mismatch.
- **Likely causes:** Mutation/tampering of `body_bytes`, request identity metadata, persisted `request.bin`, or a coding regression that reconstructs rather than reuses the canonical request.
- **First diagnostic:** Compare safe request SHA-256 metadata in `review.json` with the prepared/transmission identity; verify `request.bin` hash locally.
- **Propagation:** Identity validation failure -> preclaim termination -> zero provider requests.
- **Safe recovery:** Preserve the mismatched evidence for diagnosis and create a new review from a clean frozen snapshot after fixing the cause.
- **Evidence/data risk:** `request.bin` contains provider-bound source material. Hashes are safe to compare; raw body is restricted.
- **Do not:** Do not rewrite the hash, mutate immutable evidence, or bypass request-identity validation.
- **Related tests:** `tests/ox/test_security.py::test_prepared_request_body_tampering_is_rejected`; `tests/ox/test_security.py::test_prepared_request_identity_tampering_is_rejected`; `tests/ox/test_service.py::test_prepared_integrity_failure_is_preclaim_and_zero_transport`; `tests/ox/test_client.py::test_execute_ox_transport_rejects_request_identity_mismatch_before_transport`; `tests/ox/test_evidence.py::test_claim_send_rejects_request_identity_mismatch_without_consuming_authority`.

## F05 — Send-claim conflict or duplicate/concurrent execution

- **Boundary:** More than one execution path attempts to consume send authority for the same review identity.
- **Observable symptom:** Exactly one `send.claim` creation wins; later claims return false. The losing lifecycle performs no transport and projects existing evidence, commonly `OUTCOME_UNKNOWN` until the winning path finalizes.
- **Likely causes:** Duplicate invocation inside the same process, concurrent service execution, process restart/re-entry, or manual attempt to replay an existing review ID.
- **First diagnostic:** Check for `send.claim`; verify its request SHA matches `review.json`; inspect terminal projection with `ox_get_review`.
- **Propagation:** First atomic claim -> one permitted transport. Later claim -> no transport -> local projection only.
- **Safe recovery:** Let the winning lifecycle finish if it is still active. After interruption, treat the durable claim as consumed authority and inspect evidence; use a new explicit review identity for any later provider call.
- **Evidence/data risk:** Rewriting/deleting `send.claim` destroys replay protection.
- **Do not:** Do not delete/reset the claim, manufacture a new claim timestamp, or issue a second POST for the same review.
- **Related tests:** `tests/ox/test_evidence.py::test_claim_send_is_irreversible_and_survives_store_restart`; `tests/ox/test_crash_and_concurrency.py::test_concurrent_claim_has_exactly_one_winner_and_one_immutable_claim`; `tests/ox/test_crash_and_concurrency.py::test_duplicate_service_execution_performs_at_most_one_transport`; `tests/ox/test_service.py::test_lost_send_claim_projects_existing_evidence_without_transport`.

## F06 — Definite connect/pool failure (`NOT_SENT`)

- **Boundary:** One-shot transport fails during connect or pool acquisition with shared transport classification `NOT_SENT`.
- **Observable symptom:** Review projects `FAILED`, `attempt_outcome=NOT_SENT`; `send.claim` remains present; no `response.bin`.
- **Likely causes:** DNS/network reachability, connection refusal/timeout, exhausted connection pool, or local networking policy before request transmission.
- **First diagnostic:** Inspect the safe transport failure kind and network reachability outside the review lifecycle; confirm the review has exactly one `send.claim` and no response evidence.
- **Propagation:** Claim consumed -> one transport attempt -> definite not-sent classification -> `FAILED` finalization.
- **Safe recovery:** Correct networking and start a completely new explicitly authorized review if another provider attempt is desired.
- **Evidence/data risk:** Low for provider data because transmission is classified not sent, but the local packet/request evidence remains restricted.
- **Do not:** Do not auto-retry or reuse the claimed review identity even though the transport says `NOT_SENT`.
- **Related tests:** `tests/ox/test_client.py::test_execute_ox_transport_preserves_shared_failure_mapping_without_retry`; `tests/ox/test_service.py::test_postclaim_transport_failure_is_terminal_without_retry`.

## F07 — Write/read/deadline/remote ambiguity (`OUTCOME_UNKNOWN`)

- **Boundary:** Transmission may have begun, but write/read/deadline/remote-protocol failure prevents trustworthy completion classification.
- **Observable symptom:** Review projects `OUTCOME_UNKNOWN`, `attempt_outcome=OUTCOME_UNKNOWN`; `send.claim` remains; response evidence may be absent.
- **Likely causes:** Write timeout/error, read timeout/error, absolute deadline, remote protocol failure, or another transport condition after transmission authority was consumed.
- **First diagnostic:** Inspect safe transport failure kind/timestamps and durable evidence presence; never infer non-delivery from the absence of `response.bin`.
- **Propagation:** Claim -> possible transmission -> ambiguous transport termination -> `OUTCOME_UNKNOWN`.
- **Safe recovery:** Investigate externally if necessary. Any later provider attempt requires a fresh explicit review identity.
- **Evidence/data risk:** The provider may have received source material even though no response is locally available.
- **Do not:** Do not retry, reconnect for a result, or downgrade ambiguity to `FAILED` merely to regain send authority.
- **Related tests:** `tests/ox/test_client.py::test_execute_ox_transport_preserves_shared_failure_mapping_without_retry`; `tests/ox/test_client.py::test_execute_ox_transport_absolute_deadline_is_outcome_unknown_without_retry`; `tests/ox/test_service.py::test_postclaim_transport_failure_is_terminal_without_retry`; `tests/ox/test_security.py::test_transport_exception_sentinel_is_sanitized`.

## F08 — Complete provider rejection

- **Boundary:** Provider returns a complete non-2xx HTTP response, including redirect status because redirects are not followed.
- **Observable symptom:** Exact response body is persisted to `response.bin`; review projects `FAILED`, `attempt_outcome=REJECTED`; one transport call only.
- **Likely causes:** Authentication/entitlement, rate limit, provider validation, model availability, or HTTP redirect/rejection from the fixed route.
- **First diagnostic:** Use safe status/outcome metadata. If raw body inspection is required, inspect `response.bin` locally as restricted forensic evidence.
- **Propagation:** Claim -> one complete HTTP response -> persist exact bytes -> `FAILED/REJECTED` finalization.
- **Safe recovery:** Correct the external/configuration cause and create a new explicitly authorized review.
- **Evidence/data risk:** `response.bin` may contain provider diagnostics and must not be copied into routine logs.
- **Do not:** Do not follow redirects, retry 429/5xx automatically, or substitute a provider/model.
- **Related tests:** `tests/ox/test_client.py::test_execute_ox_transport_returns_complete_rejection_without_redirect_or_retry`; `tests/ox/test_service.py::test_complete_provider_rejection_persists_response_then_fails`; `tests/ox/test_security.py::test_redirects_are_rejected_without_followup_request`.

## F09 — Malformed or empty completed provider response

- **Boundary:** HTTP attempt completes successfully, raw response is persisted, but the envelope is invalid or does not contain exactly one non-empty assistant message.
- **Observable symptom:** `response.bin` exists; public state is `FAILED`; `attempt_outcome=COMPLETED`; `review_text` is absent.
- **Likely causes:** Invalid UTF-8/JSON, missing or multiple choices, wrong message/role/content type, whitespace-only content, or provider contract drift.
- **First diagnostic:** Confirm `response.bin` was durably captured before parsing; inspect the restricted envelope locally only as needed.
- **Propagation:** Complete response -> raw persistence -> extraction failure -> definite `FAILED` projection.
- **Safe recovery:** Investigate provider/envelope compatibility and parser contract. A later provider attempt requires a new review.
- **Evidence/data risk:** Raw provider envelope can contain material intentionally hidden from public projection.
- **Do not:** Do not return partially trusted content, invent review text, or loosen parser checks without a reviewed contract change.
- **Related tests:** `tests/ox/test_client.py::test_extract_ox_review_text_rejects_invalid_provider_envelopes`; `tests/ox/test_client.py::test_extract_ox_review_text_does_not_echo_raw_invalid_response`; `tests/ox/test_service.py::test_malformed_2xx_is_persisted_before_failed_protocol_projection`; `tests/ox/test_service.py::test_success_lifecycle_persists_raw_response_before_extraction`.

## F10 — Response or review-text persistence failure

- **Boundary:** Provider response or extracted review cannot be durably persisted after send authority has been consumed.
- **Observable symptom:** Service projects `OUTCOME_UNKNOWN`; `send.claim` remains. For response persistence failure, `response.bin` is absent even though a transport response existed. Review-text persistence uncertainty similarly prevents trustworthy completion.
- **Likely causes:** Filesystem permission/error, disk failure, write/replace/fsync uncertainty, or conflicting write-once evidence.
- **First diagnostic:** Inspect evidence-directory filesystem health and which immutable files exist. Do not repeat the provider call to reconstruct missing local evidence.
- **Propagation:** Claim -> provider attempt -> durable evidence write uncertainty -> `OUTCOME_UNKNOWN`.
- **Safe recovery:** Repair local storage for future reviews. Preserve the existing review as ambiguous; use a new explicit review if another provider result is required.
- **Evidence/data risk:** The provider may have received source material and returned data that is no longer durably reconstructible locally.
- **Do not:** Do not retransmit the same review to repair evidence, overwrite conflicting immutable files, or mark completion without durable bytes.
- **Related tests:** `tests/ox/test_service.py::test_response_persistence_failure_projects_outcome_unknown`; `tests/ox/test_evidence.py::test_response_and_review_text_are_write_once`; `tests/ox/test_evidence.py::test_finalize_completed_requires_durable_response_and_review_text`.

## F11 — Crash/restart after send claim

- **Boundary:** Process stops after `send.claim` creation at any point before trustworthy terminal finalization.
- **Observable symptom:** On restart, retrieval projects `OUTCOME_UNKNOWN` for claimed incomplete states; send authority is never reconstructed. A fully durable completed review remains `COMPLETED`.
- **Likely causes:** Process termination, host restart, crash during transport/persistence/finalization, or abrupt cancellation.
- **First diagnostic:** Inspect `send.claim`, `response.bin`, `review.txt`, and `review.json` presence/consistency; use `ox_get_review` first because it is local and non-networking.
- **Propagation:** Durable claim survives restart -> no recovery send -> state derived from surviving evidence -> typically `OUTCOME_UNKNOWN` unless completion is trustworthy.
- **Safe recovery:** Preserve evidence and investigate. Start a new explicitly authorized review only if another provider request is intentionally desired.
- **Evidence/data risk:** Delivery may have occurred even if terminal files are missing.
- **Do not:** Do not implement startup recovery that resends, delete the claim, or infer that a missing response means the provider saw nothing.
- **Related tests:** `tests/ox/test_crash_and_concurrency.py::test_restart_projection_never_reconstructs_send_authority`; `tests/ox/test_evidence.py::test_get_projects_ready_then_outcome_unknown_after_claim`.

## F12 — Torn/corrupt evidence or untrustworthy completion

- **Boundary:** Claim, response, review text, hashes, byte counts, snapshot metadata, or immutable prepared evidence is missing, changed, malformed, or inconsistent.
- **Observable symptom:** Evidence reads fail closed or a previously stored `COMPLETED` projection is downgraded to `OUTCOME_UNKNOWN`; review text is withheld when completion cannot be verified.
- **Likely causes:** Manual modification, partial/torn filesystem write, disk corruption, external cleanup, or code defect violating write-once/hash binding.
- **First diagnostic:** Compare `review.json` hashes/counts against local `packet.bin`, `request.bin`, `response.bin`, `review.txt`, and `snapshot.json`; inspect the claim identity. Keep raw material local.
- **Propagation:** Integrity check fails -> completion not trusted -> `OUTCOME_UNKNOWN` or `OXEvidenceError`; never restores send authority.
- **Safe recovery:** Preserve original/corrupt evidence for forensics. Repair the underlying storage/code defect; future provider work uses a new review identity.
- **Evidence/data risk:** Manual repair can destroy forensic provenance or accidentally expose source/provider bytes.
- **Do not:** Do not rewrite hashes/counts to match modified files, fabricate missing evidence, or remove `send.claim` to make the review `READY`.
- **Related tests:** `tests/ox/test_crash_and_concurrency.py::test_torn_send_claim_projects_outcome_unknown_and_never_restores_authority`; `tests/ox/test_crash_and_concurrency.py::test_corrupt_completion_evidence_cannot_project_completed`; `tests/ox/test_evidence.py::test_prepared_immutable_evidence_cannot_be_rewritten_with_different_bytes`; `tests/ox/test_evidence.py::test_finalize_completed_requires_durable_response_and_review_text`.

## F13 — Runtime configuration isolation failure

- **Boundary:** OX cannot construct its local runtime because the existing `projects` root/evidence directory/configuration is unavailable or invalid.
- **Observable symptom:** `OXRuntime.require_service()` raises `OXConfigurationError("OX runtime is unavailable.")`; core/NVIDIA/Wolfram server import/startup remains available. Missing provider credential does not block runtime construction and instead fails an individual review at preclaim transmission preflight.
- **Likely causes:** Missing `projects` root, invalid evidence-root path/permissions, malformed settings object, or future regression that eagerly loads provider configuration at server startup.
- **First diagnostic:** Verify the existing Byte-MCP roots include `projects`; verify the evidence root is locally creatable; confirm server import does not require `AI_GATEWAY_API_KEY`.
- **Propagation:** OX construction failure -> OX service unavailable only -> neighboring tool groups remain registered/usable.
- **Safe recovery:** Correct the local root/evidence configuration and restart Byte-MCP. Configure the provider key only when actual OX transmission is intended.
- **Evidence/data risk:** Avoid printing environment values or absolute paths into routine diagnostics.
- **Do not:** Do not invent a second filesystem authority source, eagerly load credentials at startup, or let OX failure take down unrelated tool groups.
- **Related tests:** `tests/ox/test_mcp_surface.py::test_server_reload_does_not_load_ox_provider_settings`; `tests/ox/test_mcp_surface.py::test_ox_runtime_uses_existing_projects_root_without_loading_provider_key`; `tests/ox/test_mcp_surface.py::test_ox_runtime_missing_projects_root_is_fail_isolated`; `tests/ox/test_service.py::test_missing_credential_is_preclaim_and_zero_transport`.

## F14 — MCP surface or provider-isolation drift

- **Boundary:** OX exposes extra tools/authority, changes annotations, imports NVIDIA/Wolfram execution code, or archived OX execution machinery reappears.
- **Observable symptom:** Exact-surface, AST/import, or archive-absence qualification fails. Examples include `ox_continue`, `ox_revalidate`, provider tool authority, Wolfram routing, direct NVIDIA/OX cross-imports, or changed read-only/external annotations.
- **Likely causes:** Feature creep, accidental legacy merge, convenience reuse of provider-specific code, or server registration changes.
- **First diagnostic:** Compare the registered MCP tool set with the frozen expected surface and run the OX security/archive tests; inspect imports rather than exercising providers.
- **Propagation:** Authority drift can expose unreviewed external/network or replay capability and invalidates the clean-room contract.
- **Safe recovery:** Remove the unauthorized surface/coupling and rerun provider-free qualification before any promotion/live call.
- **Evidence/data risk:** Potentially high because added tools/imports may create new data-flow authority not covered by existing privacy guarantees.
- **Do not:** Do not preserve legacy tools for compatibility, add provider tool loops, or call Wolfram/NVIDIA from OX.
- **Related tests:** `tests/ox/test_mcp_surface.py::test_task11_preserves_exact_current_surface`; `tests/ox/test_mcp_surface.py::test_task11_ox_tool_annotations_are_exact`; `tests/ox/test_archive_absence.py::test_legacy_ox_execution_markers_are_absent_from_active_source`; `tests/ox/test_archive_absence.py::test_active_source_does_not_import_archived_ox_execution_modules`; `tests/ox/test_security.py::test_ox_and_nvidia_imports_are_provider_isolated`; `tests/ox/test_security.py::test_prepared_ox_request_has_no_provider_tool_authority_or_wolfram_route`.

## F15 — Provider credential unavailable at review preflight

- **Boundary:** Prepared evidence exists, but `AI_GATEWAY_API_KEY` is absent/empty when the review reaches transmission preflight.
- **Observable symptom:** `OXConfigurationError`; prepared review evidence may remain `READY`; no `send.claim`; zero provider requests.
- **Likely causes:** Credential intentionally unset, launcher/process environment did not inherit it, or operator is running a provider-free configuration.
- **First diagnostic:** Confirm credential configuration through the approved local environment boundary without printing the value; verify `send.claim` is absent.
- **Propagation:** Prepare/persist -> lazy settings load -> missing credential -> local stop before claim/network.
- **Safe recovery:** Configure the credential in the intended runtime process environment, restart if required, then make a new explicit review invocation.
- **Evidence/data risk:** The main risk is leaking the credential during troubleshooting.
- **Do not:** Do not store the key in repository files, objectives, logs, evidence, README/config files, or paste it into chat.
- **Related tests:** `tests/ox/test_service.py::test_missing_credential_is_preclaim_and_zero_transport`; `tests/ox/test_mcp_surface.py::test_server_reload_does_not_load_ox_provider_settings`; `tests/ox/test_mcp_surface.py::test_ox_runtime_uses_existing_projects_root_without_loading_provider_key`.

## First-response diagnostic order

1. Use `ox_get_review` if a review ID exists; it performs no provider networking.
2. Determine whether `send.claim` exists.
3. If no claim exists, diagnose scope/snapshot/size/credential/request-integrity/prepared-evidence locally.
4. If a claim exists, never retry that review identity.
5. Distinguish `FAILED` from `OUTCOME_UNKNOWN` using `attempt_outcome` and durable evidence presence.
6. For `COMPLETED`, verify completion remains trustworthy before using the review text.
7. Inspect restricted evidence only when necessary and never paste raw packet/request/response material into routine channels.
8. After code changes, rerun the OX provider-free qualification plus provider-neutral/NVIDIA/Wolfram regressions before considering promotion.

## Recovery principles

- Evidence before interpretation; raw provider response persistence precedes parsing.
- Ambiguity is sticky: `OUTCOME_UNKNOWN` does not become retry authority.
- Preserve the irreversible `send.claim`.
- Prefer local correction over provider experimentation.
- Never repair a failure by weakening scope containment, exclusions, credential isolation, exact request identity, hard size limits, write-once evidence, or the exact MCP surface.
- Runtime promotion and any first live OX provider call require their own explicit authorization after provider-free qualification.
