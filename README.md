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

The Streamable HTTP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

## Inspect

In a second PowerShell terminal:

```powershell
.\scripts\Run-Inspector.ps1
```

Connect MCP Inspector to:

```text
http://127.0.0.1:8000/mcp
```

## Validate

```powershell
.\scripts\Check.ps1
```

## Architecture

```text
ChatGPT Web
    |
    |  Custom MCP app / Secure MCP Tunnel (later integration phase)
    v
Byte-MCP Streamable HTTP server
    |
    +-- approved root aliases
    +-- containment and secret-denial policy
    +-- read-only search/fetch services
    +-- bounded extractors
    +-- append-only local audit ledger
```

## Planned expansion

Future versions can add separately governed capability modules, authentication, richer document parsing, local application adapters, explicit write approvals, and integration with other Byte-Nolan Construct systems. New capabilities should remain opt-in and policy-enforced.
