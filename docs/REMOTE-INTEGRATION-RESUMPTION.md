# Byte-MCP Remote Integration Resumption

## Purpose

Resume Byte-MCP remote deployment without reopening completed V1.1 implementation work or weakening the accepted local security boundary.

This document is a future deployment gate. It does not authorize public exposure, new tools, or write capability.

## Resumption prerequisites

Resume only when all of the following are true:

1. The active ChatGPT plan supports custom MCP registration for the intended tool class.
   - Pro is sufficient only for read/fetch access under current OpenAI documentation.
   - Business or Enterprise/Edu is required for full MCP modify/write support under current OpenAI documentation.
2. The account UI exposes the required developer-mode and custom-app creation controls.
3. A supported remote connection is available.
   - Prefer OpenAI Secure MCP Tunnel when available to the account.
   - Otherwise use a stable, authenticated remote endpoint that supports MCP Streamable HTTP requirements.
4. The deployment can keep Byte-MCP bound to loopback.
5. A restricted remote roots profile can be used for the first proof.
6. The operator has time to complete security, protocol, and audit-correlation gates in one controlled session.

Review current OpenAI documentation before resumption because plan availability and UI may change:

- https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta

## Authoritative baseline

The accepted implementation baseline is:

```text
Repository:  m-indsRefuge/Byte-MCP
Release:     v0.1.1
Mode:        read-only
Tools:       list_roots, list_directory, search, fetch
Host:        127.0.0.1
Port:        8000
Transport:   streamable-http
```

Begin from the released `main` branch or `v0.1.1` tag. Do not begin from the isolated chess-capability branch.

## Gate R0 — clean baseline

From PowerShell 7:

```powershell
#Requires -Version 7.0

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

Set-Location "C:\Users\nolan\AIProjects\Byte-MCP"

git fetch origin
git switch main
git pull --ff-only origin main

git branch --show-current
git rev-parse HEAD
git status --short

.\scripts\Check.ps1
```

Required results:

- branch is `main`;
- working tree is clean;
- dependency check passes;
- compilation passes;
- Ruff passes;
- Pytest passes.

Stop if any requirement fails.

## Gate R1 — restricted remote profile

Create the profile outside the repository:

```text
Roots file:  %USERPROFILE%\.byte-mcp\roots.web.json
Audit file:  %USERPROFILE%\.byte-mcp\audit.web.jsonl
Share root:  %USERPROFILE%\Byte-MCP-Share
```

Required roots payload:

```json
{
  "roots": {
    "share": "C:\\Users\\nolan\\Byte-MCP-Share"
  }
}
```

Use only harmless canary files in the share directory.

Set the runtime environment only in the server terminal:

```powershell
$env:BYTE_MCP_ROOTS_FILE = "$env:USERPROFILE\.byte-mcp\roots.web.json"
$env:BYTE_MCP_AUDIT_FILE = "$env:USERPROFILE\.byte-mcp\audit.web.jsonl"
$env:BYTE_MCP_HOST = "127.0.0.1"
$env:BYTE_MCP_PORT = "8000"
$env:BYTE_MCP_TRANSPORT = "streamable-http"
$env:BYTE_MCP_MAX_FILE_BYTES = "1000000"
$env:BYTE_MCP_MAX_RESPONSE_CHARS = "10000"
$env:BYTE_MCP_MAX_SEARCH_FILES = "1000"
$env:BYTE_MCP_CONTENT_SEARCH_MAX_BYTES = "250000"

.\scripts\Run-Server.ps1
```

Required local proof:

```powershell
.\scripts\Run-Smoke-Test.ps1 -Root share

.\scripts\Run-Smoke-Test.ps1 `
    -Root share `
    -Query "byte-mcp-v1-test-note" `
    -ExpectName "byte-mcp-v1-test-note.txt" `
    -MaxResults 10 `
    -MaxChars 5000
```

Acceptance:

- listener exists only on `127.0.0.1` or `::1`;
- only root alias `share` is returned;
- exactly four tools are discovered;
- search and fetch pass;
- fetched content is harmless test data;
- audit contains no raw query, raw opaque reference, or fetched content.

## Gate R2 — remote transport

The remote connection must:

- support HTTPS;
- support the MCP transport behavior used by the current SDK;
- provide a stable endpoint for the duration of app registration and testing;
- require no non-loopback Byte-MCP binding;
- require no router port forwarding;
- require no inbound Windows Firewall rule;
- avoid exposing credentials in command history, logs, screenshots, chat, or Git;
- have an explicit shutdown and credential-revocation procedure.

Do not accept an account-less Cloudflare Quick Tunnel as the final transport. Cloudflare documents Quick Tunnels as development-only and without SSE support:

- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

Before blaming Byte-MCP for any remote client failure, capture the nested client exception, HTTP status, response headers, Byte-MCP server log, tunnel log, and matching audit timestamp.

## Gate R3 — remote MCP proof

Run the existing smoke client against the remote `/mcp` endpoint.

Acceptance requires:

- tool discovery passes;
- only `fetch`, `list_directory`, `list_roots`, and `search` are present;
- `list_roots` returns only `share`;
- remote search and fetch pass;
- the remote result matches the local canary file;
- no Downloads, Documents, or Projects root appears;
- the Byte-MCP audit ledger records matching allowed events.

Stop immediately if the tool list differs from the accepted four-tool contract.

## Gate R4 — ChatGPT draft app

In ChatGPT:

1. Enable developer mode only on the supported account/workspace.
2. Create a private draft custom app.
3. Enter the reviewed remote `/mcp` endpoint.
4. Configure the supported authentication mechanism.
5. Select **Scan Tools**.
6. Compare every discovered tool name, description, input schema, and annotation to the repository contract.
7. Reject the app if any unexpected tool or expanded authority appears.
8. Keep the app private until all acceptance gates pass.

Required discovered tools:

```text
fetch
list_directory
list_roots
search
```

Required annotations for all four tools:

```text
readOnlyHint:     true
destructiveHint:  false
idempotentHint:   true
openWorldHint:    false
```

## Gate R5 — ChatGPT invocation and audit correlation

From a new chat with only the Byte-MCP app enabled:

1. Request `list_roots`.
2. Confirm the response exposes only `share`.
3. Search for the harmless canary file.
4. Fetch the canary file.
5. Record the invocation timestamps.
6. Inspect `%USERPROFILE%\.byte-mcp\audit.web.jsonl`.
7. Match each ChatGPT invocation to an allowed Byte-MCP event.
8. Confirm the audit does not contain fetched content or raw query/reference values.

Acceptance requires complete correlation between the ChatGPT-side calls and the local audit ledger.

## Gate R6 — deployment decision

A remote deployment may be accepted only when Gates R0 through R5 pass.

Before expanding the roots profile, conduct a separate authorization review. Do not automatically replace `share` with Downloads, Documents, or Projects.

## Stop conditions

Stop without workaround when any of the following occurs:

- the account does not expose custom MCP registration;
- the remote endpoint requires Byte-MCP to bind to `0.0.0.0`;
- the transport requires a public inbound firewall rule or router forwarding;
- authentication cannot be configured safely;
- tool scanning returns unexpected tools;
- a remote call cannot be matched to the local audit ledger;
- a secret-bearing file, directory, or local absolute path is exposed;
- the endpoint is publicly reachable without the intended protection;
- the task begins expanding into write, shell, process, registry, or application-control capability.

## Separate future work

Write capability, authentication changes, signed references, richer auditing, and the chess-capability server are new-version work. They must not be bundled into a remote-deployment resumption increment.
