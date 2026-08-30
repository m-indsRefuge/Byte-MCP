# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol server for connecting Byte to explicitly approved resources on a Windows computer.

## Project status

Byte-MCP V1.1 remains the accepted local read-only baseline. The `build/byte-mcp-ox-validation-v1` branch adds a separately governed, optional OX external-validation capability without changing the original filesystem authority.

```text
Release baseline:          0.1.1
Core local implementation: accepted read-only baseline
Remote MCP transport:      OpenAI Secure MCP Tunnel
OX integration candidate:  automated/adversarial gates green
OX live provider route:    non-sensitive round trip proven
Private OX dogfood:        privacy/ZDR gate pending
```

The integrated branch exposes two distinct capability groups:

- **Core local access:** four read-only filesystem tools with no external side effects.
- **OX validation:** four high-level tools that may transmit an explicitly approved review packet to the fixed OX provider route and append local evidence, but never mutate or execute the reviewed repository.

Authoritative records:

- [V1.1 Closeout and Freeze](docs/V1.1-CLOSEOUT.md)
- [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md)
- [OX Validation Operations](docs/OX-VALIDATION.md)
- [Security](docs/SECURITY.md)
- [OX Integration Design](docs/superpowers/specs/2026-08-29-ox-integration-design.md)
- [Changelog](CHANGELOG.md)

## Core V1 scope

The original local capability is deliberately read-only:

- list approved roots
- list directory contents
- search approved folders by filename
- optionally search bounded extractable file content
- fetch and extract one file returned by search
- compute SHA-256 for fetched files
- append every operation to a local audit ledger
- block path traversal, symlinks, junctions, common secret locations, and sensitive key formats

The four core MCP tools are:

- `list_roots`
- `list_directory`
- `search`
- `fetch`

No core write, rename, delete, execute, shell, process-control, or unrestricted-path tool exists.

## OX validation capability

The OX subsystem adds exactly four MCP tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

These tools are isolated from the original `FileService` lifecycle. OX can read only explicitly allowlisted Git repositories and predeclared subsystem definitions from immutable committed states. It cannot execute repository code, run tests, invoke a shell, modify files, apply patches, commit, delete, or broaden review scope heuristically.

The provider route is fixed in V1:

```text
Byte-MCP
  -> natural OXReviewService
  -> Vercel AI Gateway
  -> pinned Z.AI provider
  -> zai/glm-5.3-flash
```

There is no generic provider abstraction or automatic fallback to a different model/provider in this version.

A new review or blind revalidation uses a two-phase approval protocol. The first call prepares and persists a deterministic proposal and performs **zero provider calls**. Transmission occurs only after a second explicit approval call revalidates the persisted manifest and exact canonical outbound-payload digest. Any material change invalidates that approval.

OX review responses are preserved as exact natural-language provider evidence. Byte may separately derive structured local findings through `ox_continue`'s `record_findings` mode. Those findings are explicitly labelled as Byte-authored interpretation and bound to the exact OX source attempt and response hash; they are not represented as verbatim OX JSON.

See [OX Validation Operations](docs/OX-VALIDATION.md) for configuration, evidence, lifecycle, retry, privacy, and live-route rules.

## V1.1 hardening

V1.1 preserves the four-tool core contract while adding:

- explicit loopback-only host, port, and transport settings
- startup rejection of non-loopback hosts and unsupported transports
- audit records for allowed, denied, and unexpected-error outcomes
- SHA-256 fingerprints instead of raw search terms or opaque references in audit records
- repeatable MCP client discovery and search/fetch smoke testing
- Windows and Linux continuous-integration validation
- expanded denial and configuration tests

## Remote-integration hardening

For ChatGPT tunnel connectivity, the MCP response contract is hardened so:

- `list_roots` exposes approved aliases, not backing local filesystem paths;
- search and fetch metadata expose root aliases and relative paths, not `absolute_path`;
- regression tests enforce those response boundaries.

The Secure MCP Tunnel is a transport layer and does not expand Byte-MCP's local filesystem authority.

## Approved local roots

Machine-specific roots live in:

```text
config/roots.local.json
```

That file is excluded from Git. The local scaffold can define aliases such as:

- `downloads`
- `documents`
- `projects`

For the accepted ChatGPT tunnel profile, the remote root remains deliberately bounded to the approved project location rather than a drive root or entire user profile. See [Remote Integration Resumption](docs/REMOTE-INTEGRATION-RESUMPTION.md).

OX repository/subsystem authorization is separate and machine-local:

```text
config/ox-repositories.local.json
```

That file is also excluded from Git. Start from [`config/ox-repositories.example.json`](config/ox-repositories.example.json).

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

OX is optional. Without `AI_GATEWAY_API_KEY`, the OX runtime is `DISABLED` while the four core tools remain available. Invalid optional OX configuration produces a fail-isolated `MISCONFIGURED` OX runtime rather than preventing the core server from starting.

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

CI validates Python 3.12 on Windows and Ubuntu with dependency integrity, compilation, Ruff, and the full pytest suite.

## Validate the live core MCP protocol

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

## Audit and OX evidence

Core runtime audit records are stored locally in:

```text
data/audit.jsonl
```

A remote validation profile may override that location through `BYTE_MCP_AUDIT_FILE`.

Fetched content is never written to the core ledger. Search terms and opaque references are fingerprinted before audit storage.

OX keeps its detailed review evidence separately. By default it uses a user-local data directory rather than the repository; it may be overridden with `BYTE_MCP_OX_EVIDENCE_DIR`. OX evidence records prepared scope, manifests, attempts, raw provider responses, natural conversation history, optional Byte-derived findings, Byte adjudication, and revalidation evidence while keeping the reviewed repository read-only.

## Architecture

```text
ChatGPT / Byte
    |
    | OpenAI Secure MCP Tunnel
    v
Byte-MCP Streamable HTTP server
    |
    +-- Core local capability
    |     +-- approved root aliases
    |     +-- containment + secret-denial policy
    |     +-- read-only search/fetch services
    |     +-- bounded extractors
    |     +-- append-only local audit ledger
    |
    +-- Optional OX validation capability
          +-- allowlisted Git repository/subsystem registry
          +-- deterministic committed-state bundle builder
          +-- digest-bound two-phase approval
          +-- exact natural OX response evidence
          +-- provenance-bound Byte findings/adjudication
          +-- fixed Vercel AI Gateway client
                +-- pinned Z.AI
                      +-- zai/glm-5.3-flash
```

## Authority boundary

The core V1.1 filesystem authority remains frozen. OX is a separately reviewed capability exception for **fixed-purpose outbound validation**, not arbitrary HTTP access.

Neither capability grants reviewed-repository mutation. Any future addition of write, rename, move, delete, rollback, shell, process, registry, application-control, arbitrary HTTP, broader filesystem roots, or materially different authentication/provider authority requires a new capability contract and security review.

The separate chess-capability work remains isolated from this release line.

## Planned expansion

Future versions can add separately governed capability modules, authentication, richer document parsing, local application adapters, explicit write approvals, and integration with other systems. New capabilities must remain opt-in, policy-enforced, tested, auditable, and separately releasable.
