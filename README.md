# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved resources on a Windows computer.

## Project status

Byte-MCP V1.1 remains the accepted local read-only baseline. Its original closeout is preserved as historical evidence, while a bounded remote-integration validation increment is now active using OpenAI Secure MCP Tunnel.

```text
Release baseline:     0.1.1
Local implementation: successful_validation
Remote transport:     OpenAI Secure MCP Tunnel
ChatGPT validation:   in_progress
Authority:            read_only
```

The current deployment work does not add tools or mutation authority. It hardens MCP-facing responses so local absolute filesystem paths are not disclosed and validates the existing four-tool server through the first-party tunnel path.

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

No write, rename, delete, execute, shell, process-control, or unrestricted-path tools exist in V1.

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

Before the first ChatGPT tunnel connection, the MCP response contract is hardened so:

- `list_roots` exposes approved aliases, not backing local filesystem paths;
- search and fetch metadata expose root aliases and relative paths, not `absolute_path`;
- regression tests enforce those response boundaries.

This is a deployment-security increment over the V1.1 baseline, not an expansion of authority.

## Approved local roots

Machine-specific roots live in:

```text
config/roots.local.json
```

That file is excluded from Git. The local scaffold creates these aliases:

- `downloads`
- `documents`
- `projects`

For the resumed ChatGPT tunnel validation, a separate profile outside the repository exposes exactly one root:

```text
projects -> %USERPROFILE%\AIProjects
```

Downloads, Documents, drive roots, and other local locations are not part of the first accepted remote profile. See [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md).

## Supported V1 extraction

Text/source/config formats, PDF, DOCX, XLSX, PPTX, and ZIP metadata listings.

ZIP archives are listed only. Byte-MCP does not execute files or automatically extract archive contents.

## Run

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

```powershell
.\scripts\Check.ps1
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

Runtime audit records are stored locally in:

```text
data/audit.jsonl
```

A remote validation profile may override that location through `BYTE_MCP_AUDIT_FILE`.

Fetched content is never written to the ledger. Search terms and opaque references are fingerprinted before audit storage.

## Architecture

```text
ChatGPT Web                                   validation in progress
    |
    | OpenAI Secure MCP Tunnel
    v
OpenAI tunnel-client                         local outbound-only runtime
    |
    | http://127.0.0.1:8000/mcp
    v
Byte-MCP Streamable HTTP server              validated local baseline
    |
    +-- explicit loopback network boundary
    +-- approved root aliases
    +-- containment and secret-denial policy
    +-- alias + relative-path response boundary
    +-- read-only search/fetch services
    +-- bounded extractors
    +-- append-only local audit ledger
```

No remote deployment is accepted until every gate in the remote-integration resumption document passes.

## Release boundary

The V1.1 capability boundary remains frozen. Any of the following requires a new version and separate security review:

- write, rename, move, delete, or rollback tools
- shell, process, registry, application-control, or arbitrary HTTP tools
- non-loopback binding
- additional remotely exposed roots
- materially different authentication authority
- integration with B87 Chess Arena or another Byte-Nolan system

The separate chess-capability work remains isolated from this release line.

## Planned expansion

Future versions can add separately governed capability modules, authentication, richer document parsing, local application adapters, explicit write approvals, and integration with other systems. New capabilities must remain opt-in, policy-enforced, tested, auditable, and separately releasable.
