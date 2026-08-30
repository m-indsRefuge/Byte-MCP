# Byte-MCP Windows Daemon Operations

Status: **live-qualified on 2026-08-30**

This note records the known-good Windows operating arrangement for Byte-MCP and the recovery anchors for the OX Alpha and Wolfram specialist integrations.

## Local daemon location

The Windows daemon management files are stored locally at:

```text
C:\Users\nolan\AIProjects\Byte MCP Daemon
```

The daemon uses Windows Task Scheduler and starts automatically when the Windows user logs on. It supervises the Byte-MCP server and OpenAI tunnel. The Python virtual environment is persistent on disk and is not recreated during normal startup.

## Qualified daemon behavior

The following path has been live-qualified, including after a real Windows restart and fresh user logon:

```text
Windows logon
  -> Byte-MCP Daemon scheduled task
  -> Byte-MCP supervisor
  -> Byte-MCP server on 127.0.0.1:8000
  -> OpenAI tunnel / health service on 127.0.0.1:8080
  -> ChatGPT Web UI
```

Qualification results:

- scheduled task installed and running
- automatic start after Windows reboot/login: PASS
- Byte-MCP server process: READY
- MCP endpoint: READY
- OpenAI tunnel process: READY
- tunnel health: READY
- tunnel readiness: READY
- ChatGPT Web UI -> Byte-MCP connectivity: PASS
- OX tool surface visible from Web UI smoke test: PASS
- Wolfram tool surface visible from Web UI smoke test: PASS
- no manual startup required after login

## Frozen recovery anchors

### Windows daemon runtime baseline

Branch:

```text
frozen/byte-mcp-windows-daemon-live-qualified-2026-08-30
```

Commit:

```text
6a4568201989756c60b4ec24920e42f5dd722198
```

### OX Alpha Web UI live-qualified baseline

Branch:

```text
frozen/ox-webui-live-qualified-2026-08-30
```

Commit:

```text
6a4568201989756c60b4ec24920e42f5dd722198
```

### Wolfram Web UI live-qualified baseline

Branch:

```text
frozen/wolfram-webui-live-qualified-2026-08-30
```

Commit:

```text
84f42ef499733c4d9612a78264fba347a583cbc2
```

## Daemon management commands

From the local daemon directory:

```powershell
cd 'C:\Users\nolan\AIProjects\Byte MCP Daemon'
```

Check daemon and managed-stack status:

```powershell
.\ByteMCP-Daemon-v3.ps1 -Action Status
```

Start the daemon:

```powershell
.\ByteMCP-Daemon-v3.ps1 -Action Start
```

Stop the daemon, Byte-MCP server, and OpenAI tunnel:

```powershell
.\ByteMCP-Daemon-v3.ps1 -Action Stop
```

Restart the managed environment:

```powershell
.\ByteMCP-Daemon-v3.ps1 -Action Restart
```

Inspect daemon supervisor logs:

```powershell
.\ByteMCP-Daemon-v3.ps1 -Action Logs
```

If unsigned PowerShell scripts are blocked for the current shell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Specialist operating policy

OX Alpha and Wolfram are currently considered stable and frozen. They should remain independent specialist integrations until Byte-MCP is expanded enough to justify a deliberately designed shared specialist-routing/authentication layer.

Current roles:

- **OX Alpha:** independent/adversarial external validator.
- **Wolfram:** computational co-engineer and formal-computation specialist.
- **Byte-MCP:** mediator. OX and Wolfram do not communicate directly.

Do not spend provider calls merely to revalidate a frozen baseline. Re-open specialist integration work when Byte-MCP gains additional external APIs or when a functional regression requires investigation.

## Important recovery rule

Normal development work should not modify the frozen runtime references above. If a future runtime becomes the new qualified production baseline, qualify it first and then create a new frozen recovery branch rather than moving an existing frozen branch.
