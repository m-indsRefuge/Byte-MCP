# IDE-01 Failure Map — VS Code Active Context

## Scope and invariants

IDE-01 exposes one local, read-only MCP tool, `vscode_active_context`, which reads bounded telemetry produced by `editor-state-mcp` from `.editor-state/state.json` beneath the approved `projects` root.

Invariants:

- The tool never writes to the workspace or telemetry file.
- Telemetry must remain beneath the approved `projects` root.
- Links, junctions, path escapes, malformed telemetry, and unsupported producers fail closed.
- Selection text is bounded to 12,000 characters.
- Telemetry state is bounded to 1,000,000 bytes (and additionally by the configured Byte-MCP file-size limit).
- Stale telemetry is reported as stale rather than silently treated as current.
- Audit records contain metadata and selection character count, never the selected text itself.
- Tool discovery must not initialize NVIDIA, Wolfram, or any external provider.

## Failure boundaries

| ID | Failure boundary | Observable symptom | Likely causes | First diagnostics | Propagation path | Safe recovery | Data risk | Do not | Related tests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IDE01-F01 | No editor-state telemetry | `NotFoundError` reporting no VS Code editor state under the approved projects root. | `editor-state-mcp` is not installed/running, no workspace is open, or no state has been written yet. | Confirm the intended VS Code workspace is open beneath the approved `projects` root and `.editor-state/state.json` exists there. | No state candidate → local read terminates → MCP tool returns a bounded local error. | Restore the editor-state producer or open/select a file so it emits state, then invoke the tool again. | None from the failed read. | Do not broaden the approved root or synthesize telemetry to make the call pass. | `tests/test_vscode_context.py::test_vscode_active_context_requires_editor_state` |
| IDE01-F02 | Stale telemetry | Tool succeeds with `stale=true` and an elevated `age_seconds`. | VS Code lost focus, extension stopped updating, workspace closed, or state file is old. | Inspect `updated_at`, `age_seconds`, `focused`, and telemetry file mtime. | Valid state is read → age exceeds 600 seconds → result is explicitly marked stale. | Refocus/open the intended workspace and allow the producer to emit fresh state; re-read. | Acting on stale context could target the wrong code if the caller ignores the flag. | Do not hide or reset staleness timestamps. | `tests/test_vscode_context.py::test_vscode_active_context_marks_old_telemetry_stale` |
| IDE01-F03 | Active-file path escape or unsafe filesystem indirection | `AccessDeniedError`, local rejection, or unsafe candidate skipped. | Malformed `relativePath`, `..` escape, symlink/junction, or telemetry pointing outside its workspace. | Inspect the reported relative path and workspace location without following the unsafe path. | Telemetry path → containment/link validation → fail closed before file content is returned. | Correct the producer/workspace state so the active file is a normal file beneath the workspace. | Without this boundary, arbitrary local files could be exposed through telemetry. | Do not disable `resolve_under_root`, link/junction checks, or approved-root containment. | `tests/test_vscode_context.py::test_vscode_active_context_rejects_active_file_escape` |
| IDE01-F04 | Malformed, unsupported, or unexpected telemetry | `UnsupportedFileError`. | Invalid UTF-8/JSON, unsupported schema version, missing active editor object, non-file scheme, wrong producer name, or invalid selection type. | Validate the state file schema and confirm producer name `editor-state-mcp`; do not print selected text into diagnostics. | State candidate → bounded load/schema validation → local rejection. | Repair/update the producer or regenerate a valid state file. | Malformed telemetry must not weaken containment or leak arbitrary values. | Do not accept unknown schemas/producers permissively. | `tests/test_vscode_context.py` contract tests plus `_load_state` validation |
| IDE01-F05 | Oversized telemetry | `LimitExceededError` before JSON parsing. | Producer emitted an unexpectedly large state file or the configured Byte-MCP file limit is smaller than the IDE-01 cap. | Check file size and configured `max_file_bytes`; do not inspect or log the whole payload merely to diagnose size. | `stat()` → size bound → fail closed before content parse. | Reduce producer output or restore the expected bounded state format. | Reading an unbounded state file could consume excessive memory or expose excessive context. | Do not raise limits ad hoc to make one state file pass. | `src/byte_mcp/vscode_context.py::_load_state` and IDE-01 focused tests |
| IDE01-F06 | Selection exceeds Byte-MCP context bound | Tool succeeds, selection text is truncated to 12,000 characters, `text_truncated_by_byte_mcp=true`. | User selected a very large block or producer supplied a large deliberate selection. | Inspect truncation flags and `selection_chars` audit metadata, not raw selection text. | Valid selection → deterministic prefix bound → bounded result. | Narrow the selection if full context is needed, then invoke again. | Full unbounded selection could expose more source than intended and inflate context. | Do not bypass the 12,000-character bound or log truncated/raw selection content. | `tests/test_vscode_context.py::test_vscode_active_context_bounds_selected_text` |
| IDE01-F07 | Deliberate selection belongs to a different file | Tool returns `selection=null` rather than reusing unrelated prior text. | Focus/selection changed after the last deliberate selection. | Compare active editor relative path with `lastDeliberateSelection.relativePath`. | Current selection empty → last deliberate selection path mismatch → no selection returned. | Re-select the intended code in the active file. | Reusing another file's selection could create false context and misdirect later actions. | Do not reuse deliberate selections across file boundaries. | `tests/test_vscode_context.py::test_vscode_active_context_does_not_reuse_deliberate_selection_from_other_file` |
| IDE01-F08 | Tool-surface regression | Exact MCP surface test or deployment probe fails; count is not 12 or delta is not exactly `+vscode_active_context`. | Stale registry expectations, accidental OX/tool reintroduction, missing registration, or unrelated feature contamination. | Compare the candidate surface against production predecessor `6dbb9ed8d2db6982219194b4aefb920a9507898d`. | Server registration → static/offline tool discovery → exact-set qualification failure. | Reconcile only the intended production-lineage expectations/registration and rerun structured qualification. | Extra tools can enlarge the public capability surface unexpectedly. | Do not weaken exact-set assertions or add unrelated tools to make tests pass. | `tests/test_specialist_integration.py`, `tests/test_deployment_probe.py`, `tests/test_nvidia_runtime_integration.py` |
| IDE01-F09 | Provider-laziness regression during discovery | Offline deployment probe raises because a provider or FileService was initialized. | Tool registration/import gained side effects or provider runtime became eager. | Run `test_offline_real_server_discovery_keeps_providers_lazy`; inspect import/registration changes only. | Module import/tool enumeration → unexpected runtime initialization/network boundary → fail closed. | Restore lazy provider initialization and side-effect-free discovery. | Eager discovery could contact external systems without explicit authorization. | Do not make a live provider call to diagnose discovery. | `tests/test_deployment_probe.py::test_offline_real_server_discovery_keeps_providers_lazy` |

## First-response diagnostic order

1. Confirm the active workspace is beneath the approved `projects` root.
2. Confirm `.editor-state/state.json` exists and its producer/schema are expected.
3. Check telemetry age and `stale` state.
4. Check active-file containment and link/junction status.
5. Check state-file size and selection truncation flags.
6. For surface failures, compare exact predecessor/candidate tool sets before changing tests.
7. Keep all diagnosis provider-free; IDE-01 has no reason to contact NVIDIA, Wolfram, or OX.

## Recovery principles

- Prefer correcting the telemetry producer or workspace state over weakening Byte-MCP validation.
- Treat stale context as stale evidence, not current truth.
- Preserve approved-root containment and bounded context limits.
- Keep the tool read-only and local.
- Never solve an IDE-01 failure by widening provider access, adding retries, or changing unrelated MCP tools.
