# Changelog

All notable Byte-MCP changes are documented here.

## Unreleased

### OX validation integration candidate

- Added an optional OX external-validation subsystem while preserving the accepted four-tool core filesystem authority.
- Added exactly four OX MCP tools: `ox_review`, `ox_continue`, `ox_revalidate`, and `ox_get_review`.
- Added deterministic review bundles from allowlisted immutable Git commits and versioned subsystem definitions, with mandatory source/test/boundary/context evidence and bounded verification records.
- Added two-phase human approval for initial review and blind revalidation, binding approval to the complete deterministic manifest and canonical outbound `payload_sha256` before network access.
- Added a fixed non-streaming Vercel AI Gateway client pinned to the Z.AI provider and `zai/glm-5.3-flash`, with redirects disabled and no provider/model fallback.
- Added append-only OX review, attempt, native-message, provider-response, findings, adjudication, and revalidation evidence outside the reviewed repository.
- Added explicit `NOT_SENT`, `REJECTED`, `COMPLETED`, and `OUTCOME_UNKNOWN` attempt semantics with no automatic retries and renewed approval for replay paths that can resend repository context.
- Added fail-isolated OX runtime states so missing credentials or invalid optional OX configuration do not prevent the original Byte-MCP tools from starting.
- Added configured-credential fail-closed guards across preparation, continuation, adjudication, targeted revalidation, retry replay, and all bounded retrieval views.
- Added adversarial tests for forbidden scope/repository states, manifest/payload tampering, credential persistence/transmission/retrieval, ambiguous transport outcomes, and legacy retry replay.
- Added `docs/OX-VALIDATION.md` and updated the README/security boundary for the integrated capability.
- Verified the integration candidate on Windows and Ubuntu with 229 passing tests, Ruff, compilation, and dependency integrity before the live provider canary.
- Live Vercel AI Gateway → Z.AI canary remains pending explicit human approval and is not run in CI.

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
