# Byte-MCP Remote Integration Resumption

## Purpose

Resume Byte-MCP remote deployment without weakening the accepted read-only security boundary.

The original V1.1 implementation was closed as a validated local MCP server because the required ChatGPT custom-MCP connection path was not available at that time. Remote integration validation has now resumed using OpenAI Secure MCP Tunnel.

This document authorizes only the bounded deployment-validation increment described below. It does not authorize new tools, filesystem mutation, public exposure, or non-loopback binding.

## Authoritative baseline

The accepted implementation baseline remains:

```text
Repository:  m-indsRefuge/Byte-MCP
Release:     v0.1.1
Mode:        read-only
Tools:       list_roots, list_directory, search, fetch
Host:        127.0.0.1
Port:        8000
Transport:   streamable-http
```

The deployment candidate adds one security hardening rule to that baseline: MCP-facing responses expose approved root aliases and relative paths, never the backing local absolute filesystem path.

Begin from the current `main` branch after the remote path-sanitization change is merged. Do not begin from the isolated chess-capability branch.

## Deployment authority

The first accepted ChatGPT deployment may expose exactly one root:

```text
Alias:  projects
Path:   %USERPROFILE%\AIProjects
```

The remote profile must not expose Downloads, Documents, the user profile, a drive root, or any other filesystem location.

The tool contract remains exactly:

```text
fetch
list_directory
list_roots
search
```

All four tools remain read-only.

## Gate R0 — clean baseline

From PowerShell 7:

```powershell
#Requires -Version 7.0

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

Set-Location (Join-Path $env:USERPROFILE "AIProjects\Byte-MCP")

git fetch origin
git switch main
git pull --ff-only origin main

git branch --show-current
git rev-parse HEAD
git status --short

.\scripts\Check.ps1
```

Acceptance requires:

- branch is `main`;
- local `main` matches `origin/main`;
- working tree is clean;
- dependency check passes;
- compilation passes;
- Ruff passes;
- Pytest passes.

Stop if any requirement fails.

## Gate R1 — AIProjects-only remote profile

Create the deployment profile outside the repository:

```text
Roots file:     %USERPROFILE%\.byte-mcp\roots.web.json
Audit file:     %USERPROFILE%\.byte-mcp\audit.web.jsonl
Approved root:  %USERPROFILE%\AIProjects
```

Required roots payload:

```json
{
  "roots": {
    "projects": "%USERPROFILE%\\AIProjects"
  }
}
```

Create one harmless canary file directly under `AIProjects` for the first end-to-end proof. The canary must contain no credentials, private data, or executable instructions. A suitable name is:

```text
byte-mcp-remote-canary.txt
```

Set the Byte-MCP runtime environment only in the server terminal:

```powershell
$env:BYTE_MCP_ROOTS_FILE = "$env:USERPROFILE\.byte-mcp\roots.web.json"
$env:BYTE_MCP_AUDIT_FILE = "$env:USERPROFILE\.byte-mcp\audit.web.jsonl"
$env:BYTE_MCP_HOST = "127.0.0.1"
$env:BYTE_MCP_PORT = "8000"
$env:BYTE_MCP_TRANSPORT = "streamable-http"
$env:BYTE_MCP_MAX_FILE_BYTES = "1000000"
$env:BYTE_MCP_MAX_RESPONSE_CHARS = "10000"
$env:BYTE_MCP_MAX_SEARCH_FILES = "20000"
$env:BYTE_MCP_CONTENT_SEARCH_MAX_BYTES = "250000"

.\scripts\Run-Server.ps1
```

The `projects` root may contain many repositories, so the remote validation profile permits a higher bounded filename-scan limit than the earlier one-folder canary profile. Content extraction and response limits remain conservative.

## Gate R2 — local MCP proof

With Byte-MCP running under the AIProjects-only profile, run:

```powershell
.\scripts\Run-Smoke-Test.ps1 -Root projects

.\scripts\Run-Smoke-Test.ps1 `
    -Root projects `
    -Query "byte-mcp-remote-canary" `
    -ExpectName "byte-mcp-remote-canary.txt" `
    -MaxResults 10 `
    -MaxChars 5000
```

Acceptance requires:

- listener exists only on `127.0.0.1` or `::1`;
- exactly four tools are discovered;
- `list_roots` returns only the `projects` alias;
- `list_roots` does not return the backing Windows path;
- search and fetch results expose relative paths only;
- no MCP response contains a local absolute filesystem path;
- search and fetch of the harmless canary pass;
- the audit ledger contains no raw query, raw opaque reference, or fetched content.

## Gate R3 — OpenAI Secure MCP Tunnel runtime

Use OpenAI Secure MCP Tunnel as the transport between ChatGPT and the local loopback MCP server.

Required properties:

- Byte-MCP remains bound to `127.0.0.1:8000`;
- the tunnel client connects outbound to OpenAI;
- no router port forwarding is configured;
- no inbound Windows Firewall rule is added;
- no public generic tunnel hostname is created;
- the long-lived tunnel daemon uses a restricted Runtime API key with Tunnels **Read** + **Use** only;
- the Runtime API key is never committed, logged, screenshotted, or pasted into chat;
- the selected tunnel ID is the same tunnel selected later in the ChatGPT plugin;
- the MCP target is `http://127.0.0.1:8000/mcp`.

Use the installed `tunnel-client` binary as the source of truth for the exact command surface:

```powershell
tunnel-client help quickstart
tunnel-client profiles samples show sample_mcp_remote_no_auth
tunnel-client help doctor
```

A supported profile-based configuration is expected to use the no-auth HTTP MCP sample, the selected tunnel ID, and the local Byte-MCP URL. Keep `CONTROL_PLANE_API_KEY` in the runtime process environment rather than placing the key literal in shell history or a checked-in profile.

Before opening ChatGPT, run:

```powershell
tunnel-client doctor --profile byte-mcp --explain
tunnel-client run --profile byte-mcp
```

Keep the daemon running in the foreground for the manual validation session.

Acceptance requires:

- `doctor --explain` reports no blocking configuration error;
- `/healthz` reports healthy;
- `/readyz` reports ready;
- the local tunnel UI identifies the intended tunnel and the Byte-MCP target;
- Byte-MCP server logs show no unexpected startup or protocol error.

Do not add OAuth to Byte-MCP merely to authenticate the tunnel daemon. Tunnel runtime authentication and MCP application authentication are separate boundaries.

## Gate R4 — ChatGPT private plugin and tool discovery

In ChatGPT Web:

1. Create or edit a private Byte-MCP plugin.
2. Set **Connection** to **Tunnel**.
3. Select the same Secure MCP Tunnel used by the local runtime.
4. Set plugin authentication to **No Auth** for this read-only Byte-MCP deployment unless the current product flow explicitly requires a different supported mode.
5. Scan/discover tools.
6. Compare every discovered tool name, description, input schema, and annotation to the repository contract.
7. Reject the plugin if any unexpected tool or expanded authority appears.

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

Acceptance requires exactly those four tools and no write-capable tool.

## Gate R5 — ChatGPT invocation and audit correlation

From a new chat with only the Byte-MCP plugin enabled:

1. Request `list_roots`.
2. Confirm the response exposes only the `projects` alias and no local absolute path.
3. Search for `byte-mcp-remote-canary.txt`.
4. Fetch the canary file.
5. Record the invocation timestamps.
6. Inspect `%USERPROFILE%\.byte-mcp\audit.web.jsonl` locally.
7. Match each ChatGPT invocation to an allowed Byte-MCP event.
8. Confirm the audit does not contain fetched content or raw query/reference values.

Acceptance requires complete correlation between ChatGPT-side calls and the local audit ledger.

## Gate R6 — deployment decision

The remote deployment is accepted only when Gates R0 through R5 all pass in one controlled validation sequence.

After acceptance, keep the remote root set at `projects` only. Adding another root requires a separate authorization and security review.

## Stop conditions

Stop without workaround when any of the following occurs:

- Byte-MCP must bind to `0.0.0.0` or another non-loopback host;
- the transport requires a public inbound firewall rule or router forwarding;
- tunnel runtime authentication cannot be configured safely;
- `/readyz` does not become ready;
- tool discovery returns anything other than the accepted four-tool contract;
- a remote call cannot be matched to the local audit ledger;
- a secret-bearing file, directory, or local absolute path is exposed;
- Downloads, Documents, a drive root, or another unapproved root appears;
- the endpoint becomes publicly reachable outside the intended Secure MCP Tunnel protection;
- the task begins expanding into write, shell, process, registry, or application-control capability.

## Separate future work

Write capability, additional roots, authentication changes, signed references, richer auditing, and the chess-capability server are new-version work. They must not be bundled into this remote-deployment validation increment.
