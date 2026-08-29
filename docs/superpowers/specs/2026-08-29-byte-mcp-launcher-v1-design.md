# Byte-MCP Launcher V1 Design

## Status

Approved design checkpoint pending implementation-plan review.

## Date

2026-08-29

## Purpose

Byte-MCP Launcher V1 provides one reliable operational entry point for bringing the accepted Byte-MCP read-only remote stack online on Windows.

The launcher does not expand MCP authority. Byte-MCP remains the accepted read-only baseline during this work. The launcher only manages local runtime configuration, process lifecycle, secure tunnel credential loading, health verification, state, logs, and recovery.

The intended normal operator experience is:

```powershell
.\scripts\Start-ByteMCP.ps1
```

After successful startup, ChatGPT Web can use the existing private Byte-MCP plugin without the operator manually recreating the server environment or starting the tunnel in separate terminals.

## Authoritative baseline

Implementation begins from the current `main` branch after successful Byte-MCP V1 remote acceptance.

The accepted runtime architecture remains:

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

The current MCP authority remains read-only while the launcher is built.

## Design classification

This is an operational subsystem, not a bounded edit to `Run-Server.ps1`.

The launcher owns four concerns that do not belong inside the Python MCP server:

1. secure local credential persistence;
2. Byte-MCP and tunnel process lifecycle;
3. readiness and state classification;
4. operational logs and recovery.

Windows-specific launcher behavior therefore remains in PowerShell rather than being embedded into Byte-MCP's Python service layer.

## Chosen approach

Use a repository-native PowerShell launcher suite with machine-local runtime data stored outside Git.

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
    └── tunnel-client.err.log
```

The launcher must not persist secrets, fetched content, search terms, opaque MCP references, or arbitrary MCP payloads in launcher state or launcher logs.

## Process model

### Background mode

Default invocation:

```powershell
.\scripts\Start-ByteMCP.ps1
```

The launcher starts Byte-MCP and `tunnel-client` as managed background processes, verifies readiness, records operational state, and returns control to the PowerShell prompt.

Successful output should be concise and equivalent to:

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

Foreground mode uses the same validated configuration and credential path but keeps relevant process output visible for diagnosis.

Foreground mode is an operator/debugging convenience, not a separate deployment profile.

## Setup contract

`Setup-ByteMCP.ps1` is a one-time configuration action. It must not start Byte-MCP or `tunnel-client`.

The script validates the required local infrastructure:

- Byte-MCP repository structure is present;
- `.venv\Scripts\python.exe` exists;
- `%USERPROFILE%\.byte-mcp\roots.web.json` exists;
- `tunnel-client` is installed and resolvable;
- the `byte-mcp-local` tunnel profile exists;
- the credential storage directory can be created;
- the DPAPI credential can be written and read by the current Windows user.

Normal invocation:

```powershell
.\scripts\Setup-ByteMCP.ps1
```

Credential replacement is explicit:

```powershell
.\scripts\Setup-ByteMCP.ps1 -ReplaceCredential
```

If an encrypted credential already exists, setup must refuse to overwrite it unless `-ReplaceCredential` is supplied.

## Credential lifecycle

The restricted OpenAI tunnel Runtime API key is entered only through an interactive secure prompt.

The setup script must not accept the key as a normal command-line parameter.

The credential is encrypted with Windows Data Protection API semantics bound to the current Windows user and persisted only as:

```text
%USERPROFILE%\.byte-mcp\credentials\tunnel-runtime-key.dpapi
```

The plaintext API key must never be written to:

- Git;
- repository files;
- `.env` files;
- YAML or JSON configuration;
- shell history;
- launcher state;
- launcher logs;
- Byte-MCP audit logs;
- console diagnostics.

At startup, `Start-ByteMCP.ps1` decrypts the credential in memory and supplies it only to the `tunnel-client` child process as `CONTROL_PLANE_API_KEY`.

The launcher must release its plaintext representation as soon as practical after process creation.

The key necessarily remains available to the live tunnel process through that process's environment while the tunnel is running.

The encrypted credential is intentionally machine/user-bound. Moving the repository or encrypted blob to another Windows account or computer does not constitute a supported credential migration. Setup must be run again on the new environment.

## Fixed Byte-MCP runtime profile

The launcher starts Byte-MCP with the accepted AIProjects-only remote profile:

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

The launcher must not silently broaden roots or switch Byte-MCP to a non-loopback listener.

The tunnel profile remains:

```text
byte-mcp-local
```

with target:

```text
http://127.0.0.1:8000/mcp
```

## Startup sequence

`Start-ByteMCP.ps1` performs the following sequence:

1. Validate repository, Python environment, roots profile, audit path parent, tunnel profile, tunnel-client executable, and encrypted credential.
2. Inspect existing launcher state.
3. If an existing healthy launcher-managed instance is already running, report it and do not start duplicate processes.
4. If launcher state is stale, classify and clean the stale state without killing unrelated processes.
5. Decrypt the tunnel Runtime API key in memory.
6. Start Byte-MCP with the fixed remote environment.
7. Wait for the MCP listener/endpoint on `127.0.0.1:8000` to become reachable.
8. If Byte-MCP fails to become ready within the configured startup timeout, stop any process created by this invocation, report failure, and do not start the tunnel.
9. Start `tunnel-client run --profile byte-mcp-local` with `CONTROL_PLANE_API_KEY` supplied in the child process environment.
10. Wait for `http://127.0.0.1:8080/healthz` to return healthy.
11. Wait for `http://127.0.0.1:8080/readyz` to return ready.
12. If tunnel health/readiness fails, stop the tunnel process and the Byte-MCP process created by this invocation and report the failed layer.
13. Persist verified process metadata to launcher state.
14. Report `READY` and return control to the operator in background mode.

The launcher must not report success solely because child processes exist.

## Transactional startup behavior

Startup is transactional where practical.

The launcher must not intentionally leave a half-started stack after a startup failure.

Required rollback rules:

- Byte-MCP startup failure -> no tunnel process is started.
- Tunnel start failure -> stop the Byte-MCP process created by this invocation.
- Tunnel health timeout -> stop both processes created by this invocation.
- Tunnel readiness timeout -> stop both processes created by this invocation.
- State persistence failure after successful child startup -> report failure and stop both launcher-created processes unless state can be safely reconstructed immediately.

Rollback applies only to processes created and verified as belonging to the current launcher operation.

## State management

Launcher state lives at:

```text
%USERPROFILE%\.byte-mcp\runtime\launcher-state.json
```

It contains only operational metadata required to identify and manage the launcher instance, for example:

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
    "executable": "python.exe"
  },
  "tunnel": {
    "pid": 23456,
    "executable": "tunnel-client.exe"
  }
}
```

The actual implementation may include additional non-secret ownership metadata where needed to make PID reuse checks reliable.

A PID by itself is never sufficient proof of ownership because Windows may reuse process IDs.

Before stopping or trusting a recorded process, the launcher must verify that the process still exists and corresponds to the expected process role/executable.

If state is malformed or stale, the launcher must report that condition and avoid killing an unverified process.

## Status contract

`Status-ByteMCP.ps1` is read-only with respect to the running services except that it may safely remove a state file proven to be stale if the implementation contract explicitly classifies that cleanup as benign maintenance. If cleanup introduces ambiguity, status should instead report stale state and leave cleanup to `Start` or `Stop`.

Status must distinguish:

- no launcher state;
- stale launcher state;
- process absent;
- process present but endpoint unhealthy;
- tunnel healthy but not ready;
- complete readiness.

A healthy result should be equivalent to:

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

A degraded result must name the failed layer, for example:

```text
Overall        : DEGRADED
Reason         : tunnel process running but /readyz failed
```

`Status-ByteMCP.ps1` must never display any part of the Runtime API key.

## Stop contract

Normal invocation:

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Stop performs the following:

1. Read and validate launcher state.
2. Verify recorded process identities before acting.
3. Stop the verified tunnel process.
4. Stop the verified Byte-MCP process.
5. Confirm the relevant processes/listeners are no longer live.
6. Remove launcher state only after successful or safely classified shutdown.
7. Report any process that could not be verified or stopped.

Stop must never kill arbitrary `python.exe` or `tunnel-client.exe` processes merely by executable name.

Repeated invocation must be safe. If no launcher-managed instance is running, stop reports that state without failure.

## Logging

Operational logs live outside the repository:

```text
%USERPROFILE%\.byte-mcp\logs\
```

Background mode uses separate standard-output and standard-error logs:

```text
byte-mcp-server.log
byte-mcp-server.err.log
tunnel-client.log
tunnel-client.err.log
```

The exact rotation policy for V1 should remain minimal. The implementation may truncate/recreate logs on each launcher start or use bounded simple rollover, but it must avoid unbounded accidental growth during routine operation.

Launcher logs are distinct from the Byte-MCP audit ledger:

- launcher logs explain infrastructure startup/runtime problems;
- `audit.web.jsonl` records MCP operations and authorization outcomes.

The launcher must never deliberately log the decrypted Runtime API key.

## Error reporting

Failures must identify the layer that failed rather than returning a generic startup error.

Relevant classes include:

- configuration missing/invalid;
- DPAPI credential missing/unreadable;
- Byte-MCP process creation failure;
- Byte-MCP readiness timeout;
- tunnel process creation failure;
- tunnel `/healthz` failure;
- tunnel `/readyz` failure;
- state ownership mismatch;
- state persistence failure;
- shutdown verification failure.

Diagnostics may point the operator to the relevant local log file but must not print secrets.

## Testing strategy

This subsystem must be developed using TDD where practical.

The implementation should isolate pure decision logic from process-launch side effects so that most behavior can be verified without repeatedly launching real background processes.

Tests should cover at least:

- required-path/configuration validation;
- existing-credential refusal;
- explicit credential replacement;
- Windows DPAPI round trip under the current user;
- state serialization/deserialization;
- malformed-state classification;
- stale-state classification;
- process-role/ownership verification;
- duplicate-start prevention;
- status classification;
- rollback decision behavior;
- repeated-stop behavior;
- no-secret fields in persisted state;
- expected environment construction for Byte-MCP;
- expected environment construction for tunnel-client without logging the secret.

PowerShell-specific tests should use Pester if introducing Pester remains lightweight and reproducible. If adding Pester would materially complicate repository bootstrap or CI, the implementation plan must define an equally deterministic Windows-native test harness before production code is written.

The existing Python validation remains required:

```powershell
.\scripts\Check.ps1
```

Launcher work must not regress the accepted Python MCP suite.

## CI strategy

The current Windows and Ubuntu Python jobs remain intact.

Windows-specific launcher tests belong in a Windows CI job because DPAPI and Windows process behavior are not meaningfully portable to Ubuntu.

CI must never require a real tunnel Runtime API key and must never open a real OpenAI Secure MCP Tunnel.

Remote/tunnel acceptance remains a human-controlled live validation step.

## Live acceptance sequence

After automated tests pass, perform the following controlled Windows acceptance sequence:

```text
Setup once
→ start background
→ verify MCP + tunnel READY
→ invoke Byte-MCP from ChatGPT Web
→ run status
→ stop
→ prove ports/listeners disappeared
→ start again without re-entering the Runtime API key
→ verify ChatGPT reconnects through Byte-MCP
→ stop
→ run foreground troubleshooting-mode smoke test
```

Acceptance requires:

1. setup stores only an encrypted credential outside the repository;
2. normal start requires one command and no credential re-entry;
3. only the AIProjects `projects` profile is launched;
4. Byte-MCP remains loopback-only;
5. tunnel health and readiness both pass before `READY` is reported;
6. ChatGPT can invoke the accepted Byte-MCP tools after launcher startup;
7. status reports process and endpoint state accurately;
8. stop terminates only launcher-owned processes;
9. no Byte-MCP or tunnel listeners remain after successful stop;
10. restart succeeds without rerunning setup;
11. foreground mode provides usable troubleshooting output;
12. no secret is written to Git, state, launcher logs, or console output.

## Non-goals

Launcher V1 does not:

- add write authority to Byte-MCP;
- add new MCP tools;
- alter the accepted four-tool read-only contract;
- expose Downloads or Documents;
- expose Byte-MCP on `0.0.0.0`;
- install a Windows service;
- create a Scheduled Task;
- auto-start at Windows login;
- manage Git operations;
- run tests or arbitrary shell commands on behalf of ChatGPT;
- manage unrelated Python or tunnel-client processes.

Full AIProjects write authority is separate follow-on subsystem work after the launcher is accepted.

## Future expansion

After Launcher V1 is stable, possible later work includes:

- optional Windows-login startup;
- Windows service or Scheduled Task integration;
- bounded log rotation;
- richer local status UI;
- controlled self-recovery after unexpected child-process exit;
- additional explicitly authorized Byte-MCP profiles.

These are not required for Launcher V1 acceptance.

## Security invariants

The following invariants are mandatory:

1. Byte-MCP remains bound to loopback.
2. The launcher uses only the approved AIProjects remote profile.
3. The OpenAI Runtime API key is never stored in plaintext.
4. The key is never accepted as a normal command-line argument.
5. The key is never printed or logged.
6. Launcher state contains no secrets or MCP content.
7. Stop never kills a process that it cannot verify as launcher-owned.
8. Startup never reports ready until both Byte-MCP and the tunnel are actually ready.
9. Failed startup rolls back processes created by that invocation where safely possible.
10. The launcher does not alter Byte-MCP's filesystem authority.

## Completion boundary

Byte-MCP Launcher V1 is complete only when:

- the four launcher scripts are implemented;
- automated Windows launcher tests pass;
- the existing Python Byte-MCP validation still passes;
- live background startup passes;
- ChatGPT invocation through the launched stack passes;
- status and stop behavior pass;
- restart without credential re-entry passes;
- foreground troubleshooting mode passes;
- secret non-disclosure checks pass;
- Nolan gives human acceptance.

Only after this subsystem is accepted should development move to the separately authorized AIProjects full-write capability.
