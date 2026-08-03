# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved resources on Nolan's Windows computer.

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

## Approved local roots

Machine-specific roots live in:

```text
config/roots.local.json
```

That file is excluded from Git. The scaffold creates these aliases:

- `downloads`
- `documents`
- `projects`

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

The server remains loopback-only in V1.1. `BYTE_MCP_HOST` accepts only `127.0.0.1`, `localhost`, or `::1`.

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

Validate a real search-to-fetch flow:

```powershell
.\scripts\Run-Smoke-Test.ps1 `
    -Root downloads `
    -Query "byte-mcp-v1-test-note" `
    -ExpectName "byte-mcp-v1-test-note.txt"
```

The smoke test emits structured JSON with either `successful_validation` or `failed_validation` classification.

## Audit ledger

Runtime audit records are stored locally in:

```text
data/audit.jsonl
```

The file is excluded from Git. Fetched content is never written to the ledger. Search terms and opaque references are fingerprinted before audit storage.

## Architecture

```text
ChatGPT Web
    |
    |  Custom MCP app / secure local connection
    v
Byte-MCP Streamable HTTP server
    |
    +-- explicit loopback network boundary
    +-- approved root aliases
    +-- containment and secret-denial policy
    +-- read-only search/fetch services
    +-- bounded extractors
    +-- append-only local audit ledger
```

## Planned expansion

Future versions can add separately governed capability modules, authentication, richer document parsing, local application adapters, explicit write approvals, and integration with other Byte-Nolan Construct systems. New capabilities should remain opt-in, policy-enforced, tested, and auditable.
