# Changelog

All notable Byte-MCP changes are documented here.

## [Unreleased] - Launcher V1

### Added

- Added repository-native PowerShell launcher commands for one-time setup, background start, observational status, verified stop, and foreground troubleshooting.
- Added Windows user-bound DPAPI storage for the restricted Secure MCP Tunnel Runtime API key outside the repository.
- Added launcher state with PID, executable path, and process start-time identity for both managed children.
- Added MCP endpoint, tunnel health, and tunnel readiness gates before a background stack is recorded as ready.
- Added transactional startup rollback so only processes created by the failed launcher invocation are stopped, in reverse order.
- Added duplicate-start prevention and unmanaged port-conflict refusal for ports 8000 and 8080.
- Added one-generation launcher log rotation beneath `%USERPROFILE%\.byte-mcp\logs`.
- Added verified, idempotent shutdown that refuses to kill processes whose recorded identity cannot be proven.
- Added foreground troubleshooting mode without managed launcher-state persistence.
- Added Pester launcher validation and a Windows GitHub Actions launcher job.

### Security boundary

- Launcher V1 does not add MCP tools, filesystem mutation authority, new remote roots, shell access, or non-loopback binding.
- The accepted ChatGPT remote profile remains `projects -> %USERPROFILE%\AIProjects` only.
- The Runtime API key is never accepted as a launcher command-line parameter and is only exposed through process-scope environment during tunnel child creation.

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
