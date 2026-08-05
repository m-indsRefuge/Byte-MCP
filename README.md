# Byte-MCP

Byte-MCP is an extensible, permissioned Model Context Protocol system for connecting Byte to explicitly approved capabilities on Nolan's Windows computer.

## Capability isolation

Byte-MCP runs separately governed MCP processes rather than combining every capability into one server:

```text
Byte-MCP Files  http://127.0.0.1:8000/mcp
Byte-MCP Chess  http://127.0.0.1:8001/mcp
```

The file process does not register chess tools. The chess process does not register file tools.

## V1 read-only file scope

V1 is deliberately read-only:

- list approved roots
- list directory contents
- search approved folders by filename
- optionally search bounded extractable file content
- fetch and extract one file returned by search
- compute SHA-256 for fetched files
- append every operation to a local audit ledger
- block path traversal, symlinks, junctions, common secret locations, and sensitive key formats

No write, rename, delete, execute, shell, process-control, or unrestricted-path tools exist in the file capability.

## V1.1 file hardening

V1.1 preserves the four-tool V1 contract while adding:

- explicit loopback-only host, port, and transport settings
- startup rejection of non-loopback hosts and unsupported transports
- audit records for allowed, denied, and unexpected-error outcomes
- SHA-256 fingerprints instead of raw search terms or opaque references in audit records
- repeatable MCP client discovery and search/fetch smoke testing
- Windows and Linux continuous-integration validation
- expanded denial and configuration tests

## V2 isolated chess capability

The chess capability provides one narrow command channel into B87 Chess Arena. It is bound at startup to one Arena match and one Byte actor.

Tools:

- `chess_get_turn`
- `chess_get_match`
- `chess_get_events`
- `chess_submit_move`

Byte-MCP never changes a chess board directly. `chess_submit_move` forwards one UCI proposal with the expected state version and position hash to the Arena deterministic referee.

The caller cannot select another match or actor. Move submissions require persistent idempotency keys so repeated MCP calls cannot submit the same move twice.

The full contract is documented in:

```text
docs/V2-CHESS-CAPABILITY-CONTRACT.md
```

## Approved local roots

Machine-specific roots live in:

```text
config/roots.local.json
```

That file is excluded from Git. The scaffold creates these aliases:

- `downloads`
- `documents`
- `projects`

## Supported file extraction

Text/source/config formats, PDF, DOCX, XLSX, PPTX, and ZIP metadata listings.

ZIP archives are listed only. Byte-MCP does not execute files or automatically extract archive contents.

## Run the file server

```powershell
.\scripts\Run-Server.ps1
```

Default endpoint:

```text
http://127.0.0.1:8000/mcp
```

## Run the chess server

First bind the capability to the exact Arena match created for Byte:

```powershell
$env:BYTE_MCP_CHESS_MATCH_ID = "<arena-match-uuid>"
$env:BYTE_MCP_CHESS_ACTOR = "byte"
```

Then launch the separate process:

```powershell
.\scripts\Run-Chess-Server.ps1
```

Default endpoint:

```text
http://127.0.0.1:8001/mcp
```

Optional settings:

```text
BYTE_MCP_CHESS_ARENA_BASE_URL=http://127.0.0.1:8787/api/v1
BYTE_MCP_CHESS_HOST=127.0.0.1
BYTE_MCP_CHESS_PORT=8001
BYTE_MCP_CHESS_TIMEOUT_SECONDS=10
```

Both the MCP listener and Arena target remain loopback-only.

## Inspect

In a second PowerShell terminal:

```powershell
.\scripts\Run-Inspector.ps1
```

Connect MCP Inspector to the relevant endpoint:

```text
Files: http://127.0.0.1:8000/mcp
Chess: http://127.0.0.1:8001/mcp
```

## Validate the repository

```powershell
.\scripts\Check.ps1
```

## Validate the live file protocol

With the file server already running, validate discovery and `list_roots`:

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

## Validate the live chess protocol

With the Arena and match-bound chess server already running:

```powershell
.\scripts\Run-Chess-Smoke-Test.ps1 `
    -ExpectedMatchId "<arena-match-uuid>"
```

This proves the isolated four-tool boundary, bound match identity, current turn, and immutable event access without submitting a move.

To validate one live Byte move and persistent duplicate suppression:

```powershell
.\scripts\Run-Chess-Smoke-Test.ps1 `
    -ExpectedMatchId "<arena-match-uuid>" `
    -MoveUci "e7e5" `
    -ExpectedStateVersion 1 `
    -ExpectedPositionHash "<64-character-position-hash>" `
    -IdempotencyKey "byte-turn-0001"
```

The smoke test submits the same tool call twice. The first call reaches the Arena; the second must be returned from the local idempotency receipt without another Arena submission.

Smoke tests emit structured JSON with either `successful_validation` or `failed_validation` classification.

## Audit ledgers

File runtime audit:

```text
data/audit.jsonl
```

Chess runtime audit and idempotency receipts:

```text
data/chess-audit.jsonl
data/chess-idempotency.json
```

All are excluded from Git. Raw search terms, opaque references, and chess idempotency keys are not written directly to audit.

## Architecture

```text
ChatGPT Web
    |
    +--> Byte-MCP Files :8000
    |       +-- approved root aliases
    |       +-- containment and secret-denial policy
    |       +-- read-only search/fetch services
    |
    +--> Byte-MCP Chess :8001
            +-- one bound Arena match
            +-- one bound Byte actor
            +-- persistent idempotency
            +-- B87 deterministic referee
```

## Planned expansion

Future capability modules must remain isolated, opt-in, policy-enforced, tested, and auditable. Deferred chess work includes autonomous turn scheduling, multi-match binding, engine evaluation, mentorship, and memory experiments.
