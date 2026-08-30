# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved local resources and separately governed external validation capabilities.

## Project status

Byte-MCP V1.1 remains the accepted read-only filesystem baseline. The ChatGPT Web connection through OpenAI Secure MCP Tunnel is accepted, Launcher V1 manages that local stack on Windows, and the OX integration candidate is implemented and awaiting its final end-to-end MCP acceptance test.

```text
Release baseline:          0.1.1
Core filesystem authority: accepted / read-only
Remote MCP transport:      OpenAI Secure MCP Tunnel / accepted
Launcher V1:               integrated
OX implementation:         automated + adversarial gates green
OX live provider route:    Vercel -> Z.AI -> GLM-5.3-Flash proven
OX via MCP:                acceptance test pending
Private OX dogfood:        privacy/ZDR gate remains separate
```

Byte-MCP now contains two deliberately separate capability groups:

- **Core local access:** four read-only filesystem tools with no external side effects.
- **OX validation:** four high-level review tools that can transmit only an explicitly approved, deterministic review packet to the fixed OX provider route and append local review evidence. They never mutate or execute the reviewed repository.

Authoritative records:

- [V1.1 Closeout and Freeze](docs/V1.1-CLOSEOUT.md)
- [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md)
- [OX Validation Operations](docs/OX-VALIDATION.md)
- [Security](docs/SECURITY.md)
- [OX Integration Design](docs/superpowers/specs/2026-08-29-ox-integration-design.md)
- [OX Natural Review Superseding Design](docs/superpowers/specs/2026-08-30-ox-natural-review-architecture-design.md)
- [Changelog](CHANGELOG.md)

## Core filesystem capability

The original capability remains deliberately read-only. It can:

- list approved roots;
- list directory contents;
- search approved folders by filename;
- optionally search bounded extractable file content;
- fetch and extract one file returned by search;
- compute SHA-256 for fetched files;
- append every operation to a local audit ledger;
- block path traversal, symlinks, junctions, common secret locations, and sensitive key formats.

The four core MCP tools are:

- `list_roots`
- `list_directory`
- `search`
- `fetch`

No core write, rename, delete, execute, shell, process-control MCP tool, or unrestricted-path tool exists.

## OX validation capability

The OX subsystem adds exactly four MCP tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

OX reads only explicitly allowlisted Git repositories and predeclared subsystem definitions from immutable committed states. It cannot execute repository code, run tests, invoke a shell, modify files, apply patches, commit, delete, or broaden review scope heuristically.

The provider route is fixed in V1:

```text
ChatGPT / Byte
    |
    | OpenAI Secure MCP Tunnel
    v
Byte-MCP
    |
    +-- natural OXReviewService
          |
          v
Vercel AI Gateway
    |
    +-- pinned provider: Z.AI
          |
          +-- zai/glm-5.3-flash
```

There is no generic provider abstraction or automatic provider/model fallback in OX V1.

### Human approval boundary

A new review or blind revalidation uses a two-phase protocol. The first call prepares and persists a deterministic proposal and performs **zero provider calls**. Transmission occurs only after a second explicit approval call revalidates the complete persisted manifest and canonical outbound-payload digest.

OX responses are preserved as exact natural-language provider evidence. Byte may separately derive strict structured findings through `ox_continue` using `record_findings`. Those records are explicitly Byte-authored interpretation, provenance-bound to the exact OX source attempt and response digest; they are never represented as verbatim OX JSON.

See [OX Validation Operations](docs/OX-VALIDATION.md) for configuration, evidence, retry, privacy, and lifecycle rules.

## Launcher V1

Launcher V1 is a repository-native PowerShell control layer for the accepted Byte-MCP + Secure MCP Tunnel stack. It does not add MCP tools, roots, or filesystem mutation authority.

One-time setup stores the restricted tunnel Runtime API key using Windows user-bound DPAPI:

```powershell
.\scripts\Setup-ByteMCP.ps1
```

Start the managed background stack:

```powershell
.\scripts\Start-ByteMCP.ps1
```

Inspect launcher state and health:

```powershell
.\scripts\Status-ByteMCP.ps1
```

Stop only launcher-owned processes whose PID, executable path, and process start time still match recorded state:

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Foreground troubleshooting remains available:

```powershell
.\scripts\Start-ByteMCP.ps1 -Foreground
```

Launcher machine-local data lives beneath:

```text
%USERPROFILE%\.byte-mcp\
```

Important locations include:

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

The launcher inherits ordinary parent-process environment variables when starting Byte-MCP. OX therefore sees `AI_GATEWAY_API_KEY` only when that variable is present in the launcher process environment; the key is not stored in repository configuration or launcher state.

## Approved local roots

Machine-specific manual/local root configuration may live in:

```text
config/roots.local.json
```

For the accepted ChatGPT profile, the remote filesystem root remains deliberately bounded to the approved project location rather than a drive root or whole user profile.

OX repository/subsystem authorization is separate and machine-local:

```text
config/ox-repositories.local.json
```

That file is Git-ignored. Start from [`config/ox-repositories.example.json`](config/ox-repositories.example.json).

## Supported extraction

Text/source/config formats, PDF, DOCX, XLSX, PPTX, and ZIP metadata listings are supported. ZIP archives are listed only; Byte-MCP does not execute files or automatically extract archive contents.

## Manual server run

The launcher is the preferred operational path on Windows. For direct development use:

```powershell
.\scripts\Run-Server.ps1
```

The default Streamable HTTP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The server remains loopback-only. `BYTE_MCP_HOST` accepts only `127.0.0.1`, `localhost`, or `::1`.

OX is optional. Without `AI_GATEWAY_API_KEY`, OX initializes as `DISABLED` while the four core tools remain available. Invalid optional OX configuration produces a fail-isolated `MISCONFIGURED` OX runtime rather than preventing core startup.

## Validate the repository

Run the aggregate gate:

```powershell
.\scripts\Check.ps1
```

The Python gate performs dependency integrity, compilation, Ruff, and full pytest validation. On Windows, the aggregate script also runs the launcher Pester suite. The launcher-only gate is:

```powershell
.\scripts\Check-Launcher.ps1
```

CI validates Python 3.12 on Windows and Ubuntu and runs the dedicated Windows launcher job.

## Validate the live core MCP protocol

With Byte-MCP running, validate discovery and `list_roots`:

```powershell
.\scripts\Run-Smoke-Test.ps1
```

Validate a real search-to-fetch flow:

```powershell
.\scripts\Run-Smoke-Test.ps1 `
    -Root projects `
    -Query "byte-mcp-remote-canary" `
    -ExpectName "byte-mcp-remote-canary.txt"
```

## Audit and OX evidence

Core runtime audit records are stored at the location configured by `BYTE_MCP_AUDIT_FILE`. The accepted ChatGPT profile uses:

```text
%USERPROFILE%\.byte-mcp\audit.web.jsonl
```

Fetched content is never written to that ledger. Search terms and opaque references are fingerprinted before audit storage.

OX keeps detailed review evidence separately, outside the reviewed repository. The default is a user-local data directory and can be overridden with `BYTE_MCP_OX_EVIDENCE_DIR`. Evidence includes prepared scope, manifests, attempts, raw provider responses, natural conversation history, optional Byte-derived findings, adjudication, and revalidation records.

## Authority boundary

The core V1.1 filesystem authority remains frozen. OX is a separately reviewed capability exception for **fixed-purpose outbound validation**, not arbitrary HTTP access. Launcher process control is local operator infrastructure only and does not alter the MCP authority exposed to ChatGPT.

Any future addition of write, rename, move, delete, rollback, shell, process, registry, application-control, arbitrary HTTP, broader filesystem roots, or materially different authentication/provider authority requires a new capability contract and security review.
