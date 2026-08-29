# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved resources on a Windows computer.

## Project status

Byte-MCP V1.1 remains the accepted read-only capability baseline. The ChatGPT Web integration through OpenAI Secure MCP Tunnel has been validated, and Launcher V1 now provides a bounded Windows control plane for starting, inspecting, and stopping that accepted stack.

```text
Release baseline:     0.1.1
Local implementation: successful_validation
Remote transport:     OpenAI Secure MCP Tunnel
ChatGPT validation:   accepted
Launcher:             V1 validation in progress
Authority:            read_only
```

Launcher V1 does not add tools, roots, or mutation authority. It automates only the already accepted local server and tunnel runtime while preserving the AIProjects-only remote root profile and existing read-only security boundary.

Authoritative records:

- [V1.1 Closeout and Freeze](docs/V1.1-CLOSEOUT.md)
- [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md)
- [Security](docs/SECURITY.md)
- [Changelog](CHANGELOG.md)

## V1 scope

V1 is deliberately read-only:

- list approved roots
- list directory contents
- search approved folders by filename
- optionally search bounded extractable file content
- fetch and extract one file returned by search
- compute SHA-256 for fetched files
- append every operation to a local audit ledger
- block path traversal, symlinks, junctions, common secret locations, and sensitive key formats

No write, rename, delete, execute, shell, process-control MCP tool, or unrestricted-path tool exists in V1.

## V1.1 hardening

V1.1 preserves the four-tool V1 contract while adding:

- explicit loopback-only host, port, and transport settings
- startup rejection of non-loopback hosts and unsupported transports
- audit records for allowed, denied, and unexpected-error outcomes
- SHA-256 fingerprints instead of raw search terms or opaque references in audit records
- repeatable MCP client discovery and search/fetch smoke testing
- Windows and Linux continuous-integration validation
- expanded denial and configuration tests

## Remote-integration hardening

The MCP response contract is hardened so:

- `list_roots` exposes approved aliases, not backing local filesystem paths;
- search and fetch metadata expose root aliases and relative paths, not `absolute_path`;
- regression tests enforce those response boundaries.

The accepted ChatGPT remote profile exposes exactly one root:

```text
projects -> %USERPROFILE%\AIProjects
```

Downloads, Documents, drive roots, and other local locations are not exposed through the accepted remote profile.

## Launcher V1

Launcher V1 is a repository-native PowerShell control layer for the accepted Byte-MCP + Secure MCP Tunnel stack.

One-time setup stores the restricted tunnel Runtime API key using Windows user-bound DPAPI:

```powershell
.\scripts\Setup-ByteMCP.ps1
```

Start the managed background stack:

```powershell
.\scripts\Start-ByteMCP.ps1
```

Inspect launcher state and health without mutating it:

```powershell
.\scripts\Status-ByteMCP.ps1
```

Stop only launcher-owned processes whose PID, executable path, and process start time still match recorded state:

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Run foreground troubleshooting mode when direct server and tunnel diagnostics are needed:

```powershell
.\scripts\Start-ByteMCP.ps1 -Foreground
```

Launcher machine-local data lives beneath:

```text
%USERPROFILE%\.byte-mcp\
```

Key locations include:

```text
credentials\tunnel-runtime-key.dpapi
runtime\launcher-state.json
logs\byte-mcp-server.log
logs\byte-mcp-server.err.log
logs\tunnel-client.log
logs\tunnel-client.err.log
roots.web.json
audit.web.jsonl
```

The encrypted credential is bound to the current Windows user. The Runtime API key is never accepted as a launcher command-line parameter and is injected into the tunnel child process only during process creation. Current and previous log generations are bounded by one `.previous` rotation.

ChatGPT can invoke the local Byte-MCP tools only while both the local MCP server and Secure MCP Tunnel are running and healthy. Launcher V1 remains runtime orchestration only; it does not grant filesystem write authority.

## Approved local roots

Machine-specific roots for manual/local profiles may live in:

```text
config/roots.local.json
```

That file is excluded from Git. The accepted ChatGPT profile is separate and remains AIProjects-only as described above.

## Supported V1 extraction

Text/source/config formats, PDF, DOCX, XLSX, PPTX, and ZIP metadata listings.

ZIP archives are listed only. Byte-MCP does not execute files or automatically extract archive contents.

## Manual server run

The launcher is the preferred operational path. For direct development use, the server can still be run manually:

```powershell
.\scripts\Run-Server.ps1
```

The default Streamable HTTP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The server remains loopback-only. `BYTE_MCP_HOST` accepts only `127.0.0.1`, `localhost`, or `::1`.

## Inspect

In a second PowerShell terminal:

```powershell
.\scripts\Run-Inspector.ps1
```

Connect MCP Inspector to:

```text
http://127.0.0.1:8000/mcp
```

## Validate the repository

Run the aggregate repository gate:

```powershell
.\scripts\Check.ps1
```

On Windows this includes the launcher Pester suite. The launcher-only gate is:

```powershell
.\scripts\Check-Launcher.ps1
```

## Validate the live MCP protocol

With Byte-MCP already running, validate discovery and `list_roots`:

```powershell
.\scripts\Run-Smoke-Test.ps1
```

Validate a real search-to-fetch flow using the active root profile:

```powershell
.\scripts\Run-Smoke-Test.ps1 `
    -Root projects `
    -Query "byte-mcp-remote-canary" `
    -ExpectName "byte-mcp-remote-canary.txt"
```

The smoke test emits structured JSON with either `successful_validation` or `failed_validation` classification.

## Audit ledger

Runtime audit records are stored at the location configured by `BYTE_MCP_AUDIT_FILE`. The accepted ChatGPT profile uses:

```text
%USERPROFILE%\.byte-mcp\audit.web.jsonl
```

Fetched content is never written to the ledger. Search terms and opaque references are fingerprinted before audit storage.

## Architecture

```text
ChatGPT Web                                  accepted integration
    |
    | OpenAI Secure MCP Tunnel
    v
OpenAI tunnel-client                        launcher-managed child process
    |
    | http://127.0.0.1:8000/mcp
    v
Byte-MCP Streamable HTTP server             launcher-managed child process
    |
    +-- explicit loopback network boundary
    +-- approved root aliases
    +-- containment and secret-denial policy
    +-- alias + relative-path response boundary
    +-- read-only search/fetch services
    +-- bounded extractors
    +-- append-only local audit ledger
```

## Release boundary

The V1.1 capability boundary remains frozen. Any of the following requires a new version and separate security review:

- write, rename, move, delete, or rollback MCP tools
- shell, registry, application-control, or arbitrary HTTP MCP tools
- non-loopback binding
- additional remotely exposed roots
- materially different authentication authority
- integration with B87 Chess Arena or another Byte-Nolan system

Launcher process control is local operator infrastructure only; it does not alter the MCP tool authority exposed to ChatGPT.

## Planned expansion

Future versions can add separately governed capability modules, authentication, richer document parsing, local application adapters, explicit write approvals, and integration with other systems. New capabilities must remain opt-in, policy-enforced, tested, auditable, and separately releasable.
