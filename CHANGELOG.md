# Changelog

All notable Byte-MCP changes are documented here.

## Unreleased

### Wolfram LLM co-engineer — implementation in validation

- Added a separately governed `wolfram_query` capability backed by the fixed Wolfram|Alpha LLM API route.
- Added bounded input/output handling, deny-first secret screening, machine-path sanitization, typed provider failures, and zero automatic retries.
- Added metadata-only audit and conservative UTC-month quota accounting without caching provider result content.
- Added optional Windows user-bound DPAPI storage for the Wolfram AppID and child-only launcher injection; missing Wolfram credentials do not block Byte-MCP core startup.
- Preserved the original V1 qualification fixture as exploratory provenance and added a frozen V2 30-task campaign with refined coding defects, campaign-ground-truth root-cause scoring, incomplete-campaign refusal, duplicate-primary rejection, per-mode five-follow-up ceilings, and deterministic A/B/C/D capability profiles.
- Froze separate `RAW` and `BYTE_MEDIATED` V2 inputs before live benchmark execution, including per-task route reasons, `wolfram-native-v0.1` mediated queries, transmitted-query SHA-256 evidence, and independent score summaries.
- Added a fixed six-case Byte-mediated Wolfram-native calibration corpus covering symbolic identity verification, constrained optimization, recurrence analysis, bounded sequence generation, state counting, and Boolean counterexample evidence.
- Added an MCP-only native calibration runner that discovers and calls `wolfram_query` without direct provider HTTP, AppID, or authorization handling and validates only bounded expected evidence in memory.
- Validated the six-case calibration through the local MCP boundary and separately validated the full ChatGPT Web UI -> secure tunnel -> Byte-MCP -> Wolfram -> Web UI path. Documented that ChatGPT's server connection must be refreshed after MCP tool-surface changes so the Web UI re-discovers the current schema.
- Documented the Byte-owned native query protocol and the separation between V1 exploratory, V2 RAW, and V2 BYTE_MEDIATED evidence.
- Preserved the invariant that OX and Wolfram never communicate directly; Byte remains the only mediator.

### External review hardening

- Hardened secret denial so secret/credential stems and sensitive suffixes remain blocked through ordinary and multi-suffix filenames.
- Normalized strict path-resolution, roots-configuration, and document-extraction failures into Byte-MCP domain errors.
- Changed `ByteMCPError` to inherit directly from `Exception`, preventing broad `RuntimeError` catches from silently consuming domain failures.
- Added extractor-level input limits as defense-in-depth while retaining the existing configured fetch and content-search byte ceilings.
- Repaired text decoding to require a UTF-16 BOM before UTF-16 decoding and otherwise prefer UTF-8 with a cp1252 fallback.
- Made service initialization eager at server startup so invalid root configuration fails before the MCP listener binds.
- Made search and directory truncation flags report actual omitted eligible results rather than merely reaching the requested bound.
- Added `max_chars_applied` to fetch responses when the service clamps a client request.
- Hardened directory/search handling for files that disappear or become uninspectable during enumeration.
- Chose fail-closed audit semantics: audit persistence failures now raise a Byte-MCP `AuditError` instead of leaking raw filesystem errors or returning an unaudited access result.
- Added defensive audit serialization with `default=str` and documented the V1 single-process/no-rotation audit contract.
- Documented that opaque refs are identifiers rather than authentication tokens; decoded paths are always revalidated against approved roots.
- Added adversarial regression coverage for the external-review findings and a characterization test proving the configured fetch-size limit.

### Deferred after review

- Same-handle extraction/hash consistency for concurrently modified files.
- A separate PDF page-count limit in addition to byte limits.
- Complete extraction of PPTX grouped shapes/tables.
- Multi-process audit locking and log rotation.
- Standalone wheel-layout support for default config-path discovery.

## [0.1.1] - 2026-08-06

### Completed

- Froze the four-tool read-only MCP contract: `list_roots`, `list_directory`, `search`, and `fetch`.
- Enforced loopback-only Streamable HTTP runtime configuration.
- Added denied-operation and unexpected-error auditing.
- Replaced raw audit storage of queries and opaque references with SHA-256 fingerprints and lengths.
- Added repeatable MCP discovery and search/fetch smoke testing.
- Added Windows and Ubuntu GitHub Actions validation.
- Expanded security, service, and settings tests to 14 passing tests.
- Validated the accepted implementation through local Gates A-F.
- Validated a restricted local remote-integration profile exposing only the `share` root.
- Recorded remote ChatGPT deployment as an external dependency rather than unfinished Byte-MCP implementation.
- Added closeout, freeze, and remote-integration resumption documentation.

### Deployment status

```text
Implementation:      successful_validation
Deployment status:   integration_ready
ChatGPT deployment:  blocked_external_dependency
Lifecycle state:     complete_and_frozen
```

### Deferred

- ChatGPT custom-app registration until a supported account capability is available.
- Stable authenticated remote transport.
- Write, rename, move, delete, rollback, shell, process, registry, and application-control capabilities.
- B87 Chess Arena capability, which remains isolated on a separate branch.

## [0.1.0] - 2026-08-03

### Added

- Initial permissioned read-only local files MCP server.
- Approved-root configuration.
- Filename and bounded content search.
- Opaque file references and bounded fetch extraction.
- Support for text, PDF, DOCX, XLSX, PPTX, and ZIP metadata extraction.
- SHA-256 calculation for fetched files.
- Basic local audit ledger.
- Traversal, symlink, junction, secret-location, and sensitive-suffix denial.
