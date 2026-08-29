# Byte-MCP Launcher V1 Design

## Status

Approved in conversation; pending written-spec review before implementation planning.

## Date

2026-08-29

## Purpose

Byte-MCP Launcher V1 provides one reliable Windows entry point for bringing the accepted Byte-MCP remote stack online.

The launcher does **not** expand MCP authority. Byte-MCP remains the accepted read-only baseline during this subsystem. The launcher manages only local runtime configuration, secure tunnel credential loading, process lifecycle, readiness checks, state, logs, shutdown, and recovery.

Normal operation should become:

```powershell
.\scripts\Start-ByteMCP.ps1
```

After successful startup, ChatGPT Web can invoke the existing private Byte-MCP plugin without manually rebuilding environment variables or starting the server and tunnel in separate terminals.

## Authoritative baseline

Implementation begins from the accepted Byte-MCP V1 `main` baseline after successful ChatGPT remote acceptance.

```text
ChatGPT Web
    |
    | OpenAI Secure MCP Tunnel
    v
tunnel-client
    |
    | http://127.0.0.1:8000/mcp
    v
Byte-MCP
    |
    v
projects -> %USERPROFILE%\AIProjects
```

The MCP authority remains read-only for this subsystem.

## Architecture decision

Launcher V1 is a repository-native PowerShell operational subsystem. Windows-specific process, credential, and health-management concerns stay outside the Python MCP service.

Repository scripts:

```text
scripts/
├── Setup-ByteMCP.ps1
├── Start-ByteMCP.ps1
├── Stop-ByteMCP.ps1
└── Status-ByteMCP.ps1
```

Machine-local runtime area:

```text
%USERPROFILE%\.byte-mcp\
├── credentials\
│   └── tunnel-runtime-key.dpapi
├── runtime\
│   └── launcher-state.json
└── logs\
    ├── byte-mcp-server.log
    ├── byte-mcp-server.err.log
    ├── tunnel-client.log
    ├── tunnel-client.err.log
    └── *.previous.log
```

No credential, fetched content, search term, opaque MCP reference, or arbitrary MCP payload may be persisted in launcher state or deliberately emitted by launcher logging.

## Process model

### Background mode

Default invocation:

```powershell
.\scripts\Start-ByteMCP.ps1
```

The launcher starts Byte-MCP and `tunnel-client` as managed background child processes, verifies the complete stack, records verified process state, reports readiness, and returns control to the PowerShell prompt.

Successful output should be equivalent to:

```text
BYTE-MCP READY

MCP server : ready
Tunnel     : ready
Root       : projects
Mode       : background
```

### Foreground troubleshooting mode

Troubleshooting invocation:

```powershell
.\scripts\Start-ByteMCP.ps1 -Foreground
```

Foreground mode uses the same roots profile, tunnel profile, credential path, ownership checks, startup ordering, and readiness gates as background mode. It starts the two child executables with visible console output instead of redirecting their stdout/stderr to launcher log files.

The launcher still records the actual child PIDs and verifies readiness before reporting success. Foreground mode changes observability only; it is not a different deployment or authority profile.

## Setup contract

`Setup-ByteMCP.ps1` is a one-time configuration action. It must not start Byte-MCP or `tunnel-client`.

It validates that:

- the Byte-MCP repository structure is present;
- `.venv\Scripts\python.exe` exists;
- `%USERPROFILE%\.byte-mcp\roots.web.json` exists;
- `tunnel-client` is installed and resolvable;
- the `byte-mcp-local` tunnel profile exists;
- the local credential/runtime/log directories can be created;
- the DPAPI credential can be encrypted and decrypted by the current Windows user.

Normal invocation:

```powershell
.\scripts\Setup-ByteMCP.ps1
```

Explicit credential replacement:

```powershell
.\scripts\Setup-ByteMCP.ps1 -ReplaceCredential
```

If an encrypted credential already exists, setup refuses to overwrite it unless `-ReplaceCredential` is supplied.

## Credential lifecycle

The restricted OpenAI tunnel Runtime API key is entered only through an interactive secure prompt such as `Read-Host -AsSecureString`.

The setup script must not accept the key as a normal command-line parameter.

On Windows, the implementation uses PowerShell secure-string persistence backed by the current user's Windows DPAPI context (`ConvertFrom-SecureString` without a supplied key, and the corresponding `ConvertTo-SecureString` restore path).

The encrypted representation is stored only at:

```text
%USERPROFILE%\.byte-mcp\credentials\tunnel-runtime-key.dpapi
```

The plaintext key must never be written to:

- Git;
- repository files;
- `.env` files;
- YAML or JSON configuration;
- shell history;
- launcher state;
- launcher logs;
- Byte-MCP audit logs;
- console diagnostics.

At startup, `Start-ByteMCP.ps1` decrypts the secret in memory only long enough to populate `CONTROL_PLANE_API_KEY` in the `tunnel-client` child process environment. The launcher then releases its plaintext representation as soon as practical.

The live tunnel process necessarily retains access to its own environment while running.

The encrypted credential is intentionally Windows-user bound. Copying the repository or encrypted blob to another user account or computer is not a supported credential migration; setup must be run again there.

## Fixed runtime profile

The launcher starts Byte-MCP with the accepted AIProjects-only remote environment:

```text
BYTE_MCP_ROOTS_FILE=%USERPROFILE%\.byte-mcp\roots.web.json
BYTE_MCP_AUDIT_FILE=%USERPROFILE%\.byte-mcp\audit.web.jsonl
BYTE_MCP_HOST=127.0.0.1
BYTE_MCP_PORT=8000
BYTE_MCP_TRANSPORT=streamable-http
BYTE_MCP_MAX_FILE_BYTES=1000000
BYTE_MCP_MAX_RESPONSE_CHARS=10000
BYTE_MCP_MAX_SEARCH_FILES=20000
BYTE_MCP_CONTENT_SEARCH_MAX_BYTES=250000
```

The launcher must never broaden roots or switch Byte-MCP to a non-loopback listener.

Tunnel profile:

```text
byte-mcp-local
```

Tunnel target:

```text
http://127.0.0.1:8000/mcp
```

## Startup sequence

`Start-ByteMCP.ps1` performs this sequence:

1. Validate repository, Python environment, roots profile, audit directory, tunnel profile, tunnel-client executable, encrypted credential, and local runtime directories.
2. Inspect any existing launcher state.
3. If a healthy launcher-owned instance is already running, report it and do not create duplicates.
4. If state is stale, classify it and clean only the stale state record; never kill an unverified process.
5. Decrypt the Runtime API key in memory.
6. Start Byte-MCP with the fixed remote environment.
7. Wait for `127.0.0.1:8000` and `/mcp` to respond. A raw HTTP response such as the expected MCP `406` is sufficient to prove the HTTP MCP endpoint is live; process existence alone is not.
8. If the MCP endpoint does not become live within the startup timeout, stop any server process created by this invocation, report the server-layer failure, and do not start the tunnel.
9. Start `tunnel-client run --profile byte-mcp-local` with `CONTROL_PLANE_API_KEY` supplied only in that child environment.
10. Wait for `http://127.0.0.1:8080/healthz` to return `200` and `live`.
11. Wait for `http://127.0.0.1:8080/readyz` to return `200` and `ready`.
12. If tunnel health/readiness fails, stop both launcher-created processes and report the tunnel-layer failure.
13. Persist verified process ownership metadata.
14. Report `READY`.

The launcher must never report readiness solely because child PIDs exist.

## Transactional startup

Startup is transactional where practical:

- Byte-MCP start/readiness failure -> no tunnel is started.
- Tunnel process creation failure -> stop the Byte-MCP process created by this invocation.
- Tunnel health timeout -> stop both launcher-created processes.
- Tunnel readiness timeout -> stop both launcher-created processes.
- State-write failure after successful child startup -> stop both launcher-created processes unless state can be reconstructed and persisted immediately.

Rollback applies only to processes created and verified as belonging to the current launcher operation.

## State and process ownership

State lives at:

```text
%USERPROFILE%\.byte-mcp\runtime\launcher-state.json
```

It contains non-secret operational metadata such as:

```json
{
  "schema_version": 1,
  "started_at_utc": "2026-08-29T00:00:00Z",
  "mode": "background",
  "repo_path": "C:\\Users\\...\\AIProjects\\Byte-MCP",
  "root_profile": "projects",
  "tunnel_profile": "byte-mcp-local",
  "server": {
    "pid": 12345,
    "executable_path": "C:\\...\\.venv\\Scripts\\python.exe",
    "process_start_utc": "2026-08-29T00:00:00Z"
  },
  "tunnel": {
    "pid": 23456,
    "executable_path": "C:\\...\\tunnel-client.exe",
    "process_start_utc": "2026-08-29T00:00:01Z"
  }
}
```

A PID is never sufficient proof of ownership because Windows may reuse PIDs.

Before trusting or stopping a recorded process, the launcher verifies at minimum:

- PID exists;
- executable path matches the expected executable;
- process start time matches the recorded launcher instance within a small implementation-defined timestamp tolerance.

If ownership cannot be proven, the launcher reports the mismatch and does not kill the process.

## Status contract

`Status-ByteMCP.ps1` is observational and does not mutate launcher state.

It distinguishes:

- no launcher state;
- malformed launcher state;
- stale launcher state;
- process absent;
- ownership mismatch;
- server process running but MCP endpoint unhealthy;
- tunnel process running but `/healthz` unhealthy;
- tunnel healthy but `/readyz` not ready;
- complete readiness.

Healthy output should be equivalent to:

```text
BYTE-MCP STATUS

Server process : running
MCP endpoint   : ready
Tunnel process : running
Tunnel health  : healthy
Tunnel ready   : ready
Root profile   : projects
Overall        : READY
```

A degraded result names the failed layer, for example:

```text
Overall        : DEGRADED
Reason         : tunnel process running but /readyz failed
```

Status never prints any part of the Runtime API key.

## Stop contract

Normal invocation:

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Stop:

1. reads and validates launcher state;
2. verifies recorded process ownership;
3. stops the verified tunnel child first;
4. stops the verified Byte-MCP child;
5. confirms the processes and relevant listeners are gone;
6. removes launcher state only after successful or safely classified shutdown;
7. reports anything it could not verify or stop.

Stop must never kill arbitrary `python.exe` or `tunnel-client.exe` processes by executable name.

Repeated stop is idempotent from the operator's perspective: if no launcher-managed instance is running, it reports that state without treating it as an error.

`Start` and `Stop` may remove a state file after conclusively proving it is stale. `Status` does not.

## Logging

Background operational logs live at:

```text
%USERPROFILE%\.byte-mcp\logs\
```

Current-session files:

```text
byte-mcp-server.log
byte-mcp-server.err.log
tunnel-client.log
tunnel-client.err.log
```

Launcher V1 uses a one-session bounded rollover. Before a new background start, each existing current log is moved to a matching `.previous.log` file, replacing the older previous file. Only the current and immediately previous launcher sessions are retained by this subsystem.

Foreground mode displays child output directly instead of redirecting to these current-session logs.

Launcher logs and the Byte-MCP audit ledger remain separate:

- launcher logs diagnose infrastructure startup/runtime behavior;
- `%USERPROFILE%\.byte-mcp\audit.web.jsonl` records MCP operations and authorization outcomes.

The launcher must never deliberately log the decrypted Runtime API key.

## Error reporting

Failures identify their layer rather than returning a generic error.

Required classes include:

- missing/invalid configuration;
- DPAPI credential missing/unreadable;
- Byte-MCP process creation failure;
- Byte-MCP endpoint timeout;
- tunnel process creation failure;
- tunnel `/healthz` failure;
- tunnel `/readyz` failure;
- state ownership mismatch;
- state persistence failure;
- shutdown verification failure.

Diagnostics may point to a relevant local log path but never expose secrets.

## Testing strategy

Launcher V1 is developed with TDD where practical. Decision logic should be isolated from operating-system side effects so that configuration, state, ownership, classification, and rollback behavior can be tested deterministically.

PowerShell launcher tests use **Pester 5 or later**. Pester is a development/CI dependency only; normal launcher operation must not require Pester to be installed.

Tests cover at least:

- required-path/configuration validation;
- existing-credential refusal;
- explicit credential replacement;
- Windows DPAPI round trip under the current user;
- state serialization/deserialization;
- malformed-state classification;
- stale-state classification;
- PID/executable/start-time ownership verification;
- duplicate-start prevention;
- status classification;
- rollback decisions;
- repeated-stop behavior;
- no-secret fields in persisted state;
- exact Byte-MCP environment construction;
- tunnel environment construction without secret logging;
- bounded log rollover.

The existing Python validation remains mandatory:

```powershell
.\scripts\Check.ps1
```

Launcher work must not regress the accepted MCP suite.

## CI strategy

The existing Windows and Ubuntu Python jobs remain intact.

A Windows launcher-test job installs Pester 5+, runs the launcher unit/integration tests that do not require a live OpenAI credential, and validates PowerShell syntax.

CI must never require a real tunnel Runtime API key and must never open a real OpenAI Secure MCP Tunnel.

DPAPI tests run only on Windows. Live OpenAI tunnel acceptance remains a human-controlled local validation gate.

## Live acceptance sequence

After automated verification passes:

```text
Setup once
→ start background
→ verify MCP + tunnel READY
→ invoke Byte-MCP from ChatGPT Web
→ run status
→ stop
→ prove both listeners disappeared
→ start again without re-entering the Runtime API key
→ verify ChatGPT reconnects
→ stop
→ run foreground troubleshooting-mode smoke test
```

Acceptance requires:

1. setup stores only a DPAPI-encrypted credential outside the repository;
2. normal startup requires one command and no credential re-entry;
3. only the AIProjects `projects` profile is launched;
4. Byte-MCP remains loopback-only;
5. MCP liveness and tunnel health/readiness pass before `READY` is reported;
6. ChatGPT can invoke the accepted Byte-MCP tools after launcher startup;
7. status reports process and endpoint state accurately;
8. stop terminates only launcher-owned processes;
9. no Byte-MCP or tunnel listeners remain after successful stop;
10. restart succeeds without rerunning setup;
11. foreground mode provides visible troubleshooting output;
12. no Runtime API secret is written to Git, state, logs, or console output.

## Non-goals

Launcher V1 does not:

- add write authority;
- add MCP tools;
- alter the accepted four-tool read-only contract;
- expose Downloads or Documents;
- bind Byte-MCP to `0.0.0.0`;
- install a Windows service;
- create a Scheduled Task;
- auto-start at Windows login;
- manage Git operations;
- run tests or arbitrary shell commands on behalf of ChatGPT;
- manage unrelated Python or tunnel-client processes.

Full AIProjects write authority is separate follow-on subsystem work after Launcher V1 acceptance.

## Future expansion

Possible later additions include Windows-login startup, Windows service/Scheduled Task integration, richer local status UI, controlled self-recovery after unexpected child exit, and additional explicitly authorized Byte-MCP profiles. None is required for Launcher V1.

## Security invariants

1. Byte-MCP remains bound to loopback.
2. The launcher uses only the approved AIProjects remote profile.
3. The OpenAI Runtime API key is never persisted in plaintext.
4. The key is never accepted as a normal command-line argument.
5. The key is never printed or logged.
6. Launcher state contains no secrets or MCP content.
7. Stop never kills a process that cannot be verified as launcher-owned.
8. Startup never reports ready until Byte-MCP and the tunnel are actually ready.
9. Failed startup rolls back processes created by that invocation where safely possible.
10. The launcher does not alter Byte-MCP's filesystem authority.

## Completion boundary

Byte-MCP Launcher V1 is complete only when:

- all four launcher scripts are implemented;
- Pester launcher tests pass on Windows;
- the existing Python Byte-MCP validation still passes;
- live background startup passes;
- ChatGPT invocation through the launcher-started stack passes;
- status and stop behavior pass;
- restart without credential re-entry passes;
- foreground troubleshooting mode passes;
- secret non-disclosure checks pass;
- Nolan gives human acceptance.

Only after this subsystem is accepted should development move to the separately authorized AIProjects full-write capability.
