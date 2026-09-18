# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved local resources and separately governed external capabilities.

## Project status

Byte-MCP V1.1 remains the accepted read-only filesystem baseline. The ChatGPT Web connection through OpenAI Secure MCP Tunnel is accepted, Launcher V1 manages that local stack on Windows, and the clean-room OX implementation has completed its provider-free implementation/security qualification on its feature branch.

```text
Release baseline:            0.1.1
Core filesystem authority:   accepted / read-only
Remote MCP transport:        OpenAI Secure MCP Tunnel / accepted
Launcher V1:                 integrated
NVIDIA governed provider:    integrated
Wolfram query capability:    integrated
OX clean-room implementation: provider-free qualification green
OX runtime promotion:        requires separate explicit authorization
First live clean-room OX call: requires separate explicit authorization
```

The currently registered MCP surface is deliberately bounded to ten tools across four capability groups:

- **Core local access:** `list_roots`, `list_directory`, `search`, `fetch`.
- **Wolfram:** `wolfram_query`.
- **NVIDIA:** `nvidia_query`, `nvidia_review`, `nvidia_get_review`.
- **OX clean-room review:** `ox_review`, `ox_get_review`.

Authoritative current records:

- [V1.1 Closeout and Freeze](docs/V1.1-CLOSEOUT.md)
- [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md)
- [OX Clean-Room Operator Contract](docs/OX.md)
- [OX Historical Archive](archive/OX-ARCHIVE.md)
- [Security](docs/SECURITY.md)
- [Changelog](CHANGELOG.md)

Pre-clean-room OX operator/design documents are historical references only; the archive note identifies the preserved generations and the current contract boundary.

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

## OX clean-room review capability

OX is a small synchronous adversarial code-review subsystem. It exposes exactly two MCP tools:

- `ox_review(repository, mode, objective, paths=None)`
- `ox_get_review(review_id)`

OX is code-review-only. It does not execute repository code, run tests, invoke a shell, modify files, apply patches, commit, delete, provide general chat, or give the provider access to Byte-MCP tools.

Repository authority comes from Byte-MCP's existing `projects` root. The caller selects a direct-child repository name beneath that root rather than an arbitrary absolute path. `FULL_REPOSITORY` reviews all eligible frozen material; `BOUNDED` reviews only explicitly selected normalized relative paths.

The snapshot uses current filesystem bytes, so eligible staged, unstaged, and untracked material can be reviewed. Sensitive/generated/non-text material and link/junction/nested-repository boundaries are excluded or rejected under the versioned snapshot policy. Hard included-content/packet/request limits fail locally rather than truncating or splitting a review.

The provider route is fixed:

```text
ChatGPT / Byte
    |
    | OpenAI Secure MCP Tunnel
    v
Byte-MCP
    |
    +-- clean-room OXReviewService
          |
          v
Vercel AI Gateway
    |
    +-- provider allow-list: Z.AI
          |
          +-- zai/glm-5.3-flash
```

### Human approval boundary

One explicit `ox_review` invocation authorizes that review's complete synchronous lifecycle and permits at most one outbound provider request. There is no second approval gate, automatic retry, continuation, revalidation, worker, recovery loop, or second POST under the same review identity.

Before transport, Byte-MCP freezes the snapshot and canonical request, persists prepared evidence, loads the credential lazily, verifies request identity and provider-bound safety, then creates an irreversible `send.claim`. Once that claim exists, send authority is consumed permanently for that review identity.

The exact raw provider response is persisted before Byte-MCP decodes the provider envelope. OX's review remains free-form prose; no findings/severity/decision schema is imposed.

See [OX Clean-Room Operator Contract](docs/OX.md) for the complete scope, evidence, failure-state, privacy, and approval contract. Historical OX V1/V2 behavior is preserved only through the [OX Historical Archive](archive/OX-ARCHIVE.md) and Git history.

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

The launcher inherits ordinary parent-process environment variables when starting Byte-MCP. OX reads `AI_GATEWAY_API_KEY` only when an `ox_review` reaches transmission preflight; the key is not stored in repository configuration or launcher state by the clean-room OX subsystem.

## Approved local roots

Machine-specific manual/local root configuration may live in:

```text
config/roots.local.json
```

For the accepted ChatGPT profile, the remote filesystem root remains deliberately bounded to the approved project location rather than a drive root or whole user profile.

Clean-room OX reuses the existing `projects` root. Repository arguments are direct-child directory names beneath that root. [`config/ox-repositories.example.json`](config/ox-repositories.example.json) is documentation-only and is not a second runtime authorization registry.

## Supported extraction

Text/source/config formats, PDF, DOCX, XLSX, PPTX, and ZIP metadata listings are supported by the core filesystem capability. ZIP archives are listed only; Byte-MCP does not execute files or automatically extract archive contents.

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

OX runtime construction is lazy and fail-isolated. It does not require the provider key at server import/startup. If the clean-room OX local runtime cannot be constructed, OX remains unavailable without preventing core, Wolfram, or NVIDIA startup. If `AI_GATEWAY_API_KEY` is absent, an individual `ox_review` stops before `send.claim` and performs zero provider requests.

## Validate the repository

Run the aggregate gate:

```powershell
.\scripts\Check.ps1
```

The Python gate performs dependency integrity, compilation, Ruff, and full pytest validation. On Windows, the aggregate script also runs the launcher Pester suite. The launcher-only gate is:

```powershell
.\scripts\Check-Launcher.ps1
```

CI validates Python 3.12 on Windows and Ubuntu and runs the dedicated Windows launcher jobs.

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

OX keeps detailed review evidence separately, outside the reviewed repository. The default is `%LOCALAPPDATA%\Byte-MCP\ox` on Windows and `${XDG_DATA_HOME:-~/.local/share}/byte-mcp/ox` on POSIX; `BYTE_MCP_OX_EVIDENCE_DIR` may override it.

Each clean-room review directory can contain `review.json`, `snapshot.json`, `packet.bin`, `request.bin`, irreversible `send.claim`, `response.bin`, and `review.txt`. Raw packet/request/response evidence is restricted forensic material and is not returned by `ox_get_review`.

## Authority boundary

The core V1.1 filesystem authority remains frozen. Wolfram, NVIDIA, and OX are separately governed capability exceptions; OX specifically is fixed-purpose outbound code review, not arbitrary HTTP access. Launcher process control is local operator infrastructure only and does not alter the MCP authority exposed to ChatGPT.

Any future addition of write, rename, move, delete, rollback, shell, process, registry, application-control, arbitrary HTTP, broader filesystem roots, OX continuation/retry/revalidation, provider tool access, or materially different authentication/provider authority requires a new capability contract and security review.
