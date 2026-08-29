# Byte-MCP Launcher V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-command Windows launcher suite that securely starts, verifies, reports, and stops the accepted Byte-MCP read-only remote stack without re-entering the tunnel Runtime API key.

**Architecture:** Keep launcher responsibilities in PowerShell under `scripts/` and keep machine-local credential, runtime-state, and log data under `%USERPROFILE%\.byte-mcp\`. Isolate reusable launcher helpers in one dot-sourced module-like script so setup/start/status/stop share the same validation, DPAPI, process-ownership, health, state, and logging rules while the Python MCP service remains unchanged.

**Tech Stack:** PowerShell 7+, Windows DPAPI via `ConvertFrom-SecureString` / `ConvertTo-SecureString`, Pester 5+, existing Python 3.12 Byte-MCP runtime, OpenAI `tunnel-client`, GitHub Actions Windows CI.

**Spec:** `docs/superpowers/specs/2026-08-29-byte-mcp-launcher-v1-design.md`

## Global Constraints

- Byte-MCP authority remains read-only for Launcher V1.
- Approved remote root remains only `projects -> %USERPROFILE%\AIProjects`.
- Byte-MCP remains bound to `127.0.0.1:8000` with `streamable-http` transport.
- Tunnel profile remains `byte-mcp-local`, targeting `http://127.0.0.1:8000/mcp`.
- Runtime API key is entered only through a secure prompt and is never stored in plaintext, accepted as a normal command-line parameter, printed, or logged.
- Launcher state contains no secrets, fetched content, search terms, opaque MCP references, or arbitrary MCP payloads.
- Stop never kills a process that cannot be verified as launcher-owned.
- Startup never reports ready until both Byte-MCP liveness and tunnel `/healthz` + `/readyz` checks pass.
- Failed startup rolls back launcher-created processes where safely possible.
- Status is observational and must not mutate launcher state.
- Pester 5+ is the Windows launcher test framework.
- CI never requires a real Runtime API key and never opens a real OpenAI Secure MCP Tunnel.
- Existing Python validation via `scripts/Check.ps1` remains required and must continue to pass.

---

## File Map

### Create
- `scripts/Launcher.Common.ps1` — shared paths, configuration validation, DPAPI helpers, state serialization, process identity checks, health probes, logging helpers, and rollback helpers.
- `scripts/Setup-ByteMCP.ps1` — one-time launcher setup and encrypted Runtime API key storage.
- `scripts/Start-ByteMCP.ps1` — default background startup plus `-Foreground` troubleshooting mode.
- `scripts/Status-ByteMCP.ps1` — read-only process + endpoint classification.
- `scripts/Stop-ByteMCP.ps1` — verified shutdown of launcher-owned processes only.
- `tests/launcher/Launcher.Common.Tests.ps1` — helper/config/state/DPAPI/process/status unit tests.
- `tests/launcher/Setup-ByteMCP.Tests.ps1` — setup/credential lifecycle tests.
- `tests/launcher/Start-ByteMCP.Tests.ps1` — startup, duplicate prevention, environment, and rollback tests using mocks.
- `tests/launcher/Status-ByteMCP.Tests.ps1` — status classification tests.
- `tests/launcher/Stop-ByteMCP.Tests.ps1` — verified-stop and repeated-stop tests.
- `scripts/Check-Launcher.ps1` — Pester entry point for launcher tests.

### Modify
- `.github/workflows/ci.yml` — add a Windows-only launcher test job while preserving existing Python jobs.
- `scripts/Check.ps1` — keep Python validation intact and optionally invoke launcher tests on Windows only after launcher test bootstrap is proven stable.
- `README.md` — document setup/start/status/stop/foreground workflow and machine-local paths.
- `CHANGELOG.md` — record Launcher V1 operational subsystem.

---

### Task 1: Shared Launcher Configuration and Path Contract

**Files:**
- Create: `scripts/Launcher.Common.ps1`
- Create: `tests/launcher/Launcher.Common.Tests.ps1`

**Interfaces:**
- Produces: `Get-ByteMcpLauncherPaths`, `Get-ByteMcpServerEnvironment`, `Assert-ByteMcpLauncherPrerequisites`, `Get-TunnelClientPath`.
- `Get-ByteMcpLauncherPaths` returns a PSCustomObject containing: `RepoRoot`, `PythonPath`, `LocalRoot`, `RootsFile`, `AuditFile`, `CredentialFile`, `RuntimeDir`, `StateFile`, `LogsDir`, `ServerStdOut`, `ServerStdErr`, `TunnelStdOut`, `TunnelStdErr`, `TunnelProfile`.
- `Get-ByteMcpServerEnvironment` returns a hashtable containing exactly the accepted Byte-MCP remote environment values from the spec.

- [ ] **Step 1: Write failing path/environment tests**

```powershell
Describe 'Launcher path and environment contract' {
    BeforeAll {
        . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"
    }

    It 'uses the machine-local .byte-mcp runtime area' {
        $paths = Get-ByteMcpLauncherPaths -RepoRoot 'C:\repo' -UserProfile 'C:\Users\test'
        $paths.CredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
        $paths.StateFile | Should -Be 'C:\Users\test\.byte-mcp\runtime\launcher-state.json'
        $paths.TunnelProfile | Should -Be 'byte-mcp-local'
    }

    It 'builds the accepted AIProjects-only Byte-MCP environment' {
        $envMap = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
        $envMap.BYTE_MCP_ROOTS_FILE | Should -Be 'C:\Users\test\.byte-mcp\roots.web.json'
        $envMap.BYTE_MCP_AUDIT_FILE | Should -Be 'C:\Users\test\.byte-mcp\audit.web.jsonl'
        $envMap.BYTE_MCP_HOST | Should -Be '127.0.0.1'
        $envMap.BYTE_MCP_PORT | Should -Be '8000'
        $envMap.BYTE_MCP_TRANSPORT | Should -Be 'streamable-http'
        $envMap.BYTE_MCP_MAX_FILE_BYTES | Should -Be '1000000'
        $envMap.BYTE_MCP_MAX_RESPONSE_CHARS | Should -Be '10000'
        $envMap.BYTE_MCP_MAX_SEARCH_FILES | Should -Be '20000'
        $envMap.BYTE_MCP_CONTENT_SEARCH_MAX_BYTES | Should -Be '250000'
    }
}
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: FAIL because `Launcher.Common.ps1` and required functions do not yet exist.

- [ ] **Step 3: Implement minimal shared path/environment helpers**

```powershell
function Get-ByteMcpLauncherPaths {
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'
    [PSCustomObject]@{
        RepoRoot       = $RepoRoot
        PythonPath     = Join-Path $RepoRoot '.venv\Scripts\python.exe'
        LocalRoot      = $localRoot
        RootsFile      = Join-Path $localRoot 'roots.web.json'
        AuditFile      = Join-Path $localRoot 'audit.web.jsonl'
        CredentialFile = Join-Path $localRoot 'credentials\tunnel-runtime-key.dpapi'
        RuntimeDir     = Join-Path $localRoot 'runtime'
        StateFile      = Join-Path $localRoot 'runtime\launcher-state.json'
        LogsDir        = Join-Path $localRoot 'logs'
        ServerStdOut   = Join-Path $localRoot 'logs\byte-mcp-server.log'
        ServerStdErr   = Join-Path $localRoot 'logs\byte-mcp-server.err.log'
        TunnelStdOut   = Join-Path $localRoot 'logs\tunnel-client.log'
        TunnelStdErr   = Join-Path $localRoot 'logs\tunnel-client.err.log'
        TunnelProfile  = 'byte-mcp-local'
    }
}

function Get-ByteMcpServerEnvironment {
    param([Parameter(Mandatory)] [string] $UserProfile)
    $localRoot = Join-Path $UserProfile '.byte-mcp'
    @{
        BYTE_MCP_ROOTS_FILE               = Join-Path $localRoot 'roots.web.json'
        BYTE_MCP_AUDIT_FILE               = Join-Path $localRoot 'audit.web.jsonl'
        BYTE_MCP_HOST                     = '127.0.0.1'
        BYTE_MCP_PORT                     = '8000'
        BYTE_MCP_TRANSPORT                = 'streamable-http'
        BYTE_MCP_MAX_FILE_BYTES           = '1000000'
        BYTE_MCP_MAX_RESPONSE_CHARS       = '10000'
        BYTE_MCP_MAX_SEARCH_FILES         = '20000'
        BYTE_MCP_CONTENT_SEARCH_MAX_BYTES = '250000'
    }
}
```

Add `Get-TunnelClientPath` using `Get-Command tunnel-client -ErrorAction Stop` and `Assert-ByteMcpLauncherPrerequisites` to verify repo, Python, roots file, tunnel-client, and tunnel profile presence without starting any process.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 tests/launcher/Launcher.Common.Tests.ps1
git commit -m "feat: add launcher configuration contract"
```

---

### Task 2: DPAPI Credential Lifecycle and Setup Command

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Setup-ByteMCP.ps1`
- Create: `tests/launcher/Setup-ByteMCP.Tests.ps1`

**Interfaces:**
- Consumes: `Get-ByteMcpLauncherPaths`, `Assert-ByteMcpLauncherPrerequisites`.
- Produces: `Protect-ByteMcpCredential`, `Unprotect-ByteMcpCredential`, setup command with `-ReplaceCredential` switch.
- `Protect-ByteMcpCredential([SecureString], [string]$Path)` writes only DPAPI-protected text.
- `Unprotect-ByteMcpCredential([string]$Path)` returns a `SecureString`.

- [ ] **Step 1: Write failing credential tests**

```powershell
Describe 'Byte-MCP credential lifecycle' {
    BeforeAll { . "$PSScriptRoot/../../scripts/Launcher.Common.ps1" }

    It 'round-trips a credential through Windows DPAPI' -Skip:(!$IsWindows) {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        $secret = ConvertTo-SecureString 'test-secret-value' -AsPlainText -Force
        Protect-ByteMcpCredential -Credential $secret -Path $path
        $roundTrip = Unprotect-ByteMcpCredential -Path $path
        $plain = [System.Net.NetworkCredential]::new('', $roundTrip).Password
        $plain | Should -Be 'test-secret-value'
        (Get-Content -LiteralPath $path -Raw) | Should -Not -Match 'test-secret-value'
    }

    It 'refuses to replace an existing credential without explicit authorization' {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        Set-Content -LiteralPath $path -Value 'existing'
        { Assert-CredentialWriteAllowed -Path $path -ReplaceCredential:$false } | Should -Throw
    }
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Setup-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL because credential helpers do not exist.

- [ ] **Step 3: Implement DPAPI helpers and setup command**

Use Windows user-bound DPAPI semantics:

```powershell
function Protect-ByteMcpCredential {
    param([SecureString] $Credential, [string] $Path)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $protected = ConvertFrom-SecureString -SecureString $Credential
    [System.IO.File]::WriteAllText($Path, $protected, [System.Text.UTF8Encoding]::new($false))
}

function Unprotect-ByteMcpCredential {
    param([string] $Path)
    $protected = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8).Trim()
    ConvertTo-SecureString -String $protected
}
```

`Setup-ByteMCP.ps1` must:

```powershell
[CmdletBinding()]
param([switch] $ReplaceCredential)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE
Assert-ByteMcpLauncherPrerequisites -Paths $paths -SkipCredentialCheck
Assert-CredentialWriteAllowed -Path $paths.CredentialFile -ReplaceCredential:$ReplaceCredential
$credential = Read-Host 'Paste the restricted Runtime API key' -AsSecureString
Protect-ByteMcpCredential -Credential $credential -Path $paths.CredentialFile
$null = Unprotect-ByteMcpCredential -Path $paths.CredentialFile
Write-Host 'PASS: Byte-MCP launcher setup complete'
```

Do not accept an API key parameter.

- [ ] **Step 4: Run setup tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Setup-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS on Windows; DPAPI test skipped on non-Windows.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 scripts/Setup-ByteMCP.ps1 tests/launcher/Setup-ByteMCP.Tests.ps1
git commit -m "feat: add DPAPI launcher setup"
```

---

### Task 3: State Schema and Process Ownership Verification

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Modify: `tests/launcher/Launcher.Common.Tests.ps1`

**Interfaces:**
- Produces: `New-LauncherState`, `Write-LauncherState`, `Read-LauncherState`, `Test-LauncherProcessIdentity`, `Get-LauncherStateClassification`.
- State identity fields for each child: `pid`, `executable_path`, `started_at_utc`.
- State `schema_version` is `1`.

- [ ] **Step 1: Write failing state/identity tests**

```powershell
It 'serializes state without secret fields' {
    $state = New-LauncherState -RepoPath 'C:\repo' -Mode 'background' `
        -ServerPid 100 -ServerExecutable 'C:\Python\python.exe' -ServerStartedAtUtc '2026-08-29T10:00:00Z' `
        -TunnelPid 200 -TunnelExecutable 'C:\OpenAI\tunnel-client.exe' -TunnelStartedAtUtc '2026-08-29T10:00:01Z'
    $json = $state | ConvertTo-Json -Depth 5
    $json | Should -Not -Match 'API_KEY|credential|secret|content|query|reference'
    $state.schema_version | Should -Be 1
}

It 'classifies a missing state file as absent' {
    Get-LauncherStateClassification -StatePath (Join-Path $TestDrive 'missing.json') | Should -Be 'absent'
}

It 'rejects a PID whose executable path or start time does not match recorded identity' {
    $record = [pscustomobject]@{ pid = 123; executable_path = 'C:\expected.exe'; started_at_utc = '2026-08-29T10:00:00Z' }
    $actual = [pscustomobject]@{ Id = 123; Path = 'C:\other.exe'; StartTime = [datetime]'2026-08-29T10:00:00Z' }
    Test-LauncherProcessIdentity -Record $record -Process $actual | Should -BeFalse
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing state helpers.

- [ ] **Step 3: Implement state and ownership helpers**

Persist state atomically by writing a UTF-8-no-BOM temporary file in the runtime directory and moving it over `launcher-state.json` only after serialization succeeds. `Read-LauncherState` must return a typed classification or throw a launcher-specific malformed-state error; `Test-LauncherProcessIdentity` must compare PID, normalized executable path, and process start time converted to UTC.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 tests/launcher/Launcher.Common.Tests.ps1
git commit -m "feat: add launcher state ownership checks"
```

---

### Task 4: Health Probes and Status Classification

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Status-ByteMCP.ps1`
- Create: `tests/launcher/Status-ByteMCP.Tests.ps1`

**Interfaces:**
- Produces: `Test-ByteMcpEndpoint`, `Test-TunnelHealth`, `Test-TunnelReady`, `Get-ByteMcpStatus`.
- `Get-ByteMcpStatus` returns a PSCustomObject with `ServerProcess`, `McpEndpoint`, `TunnelProcess`, `TunnelHealth`, `TunnelReady`, `RootProfile`, `Overall`, `Reason`.
- Raw Byte-MCP `406` response counts as endpoint liveness; connection failure does not.

- [ ] **Step 1: Write failing status tests**

```powershell
Describe 'Byte-MCP status classification' {
    BeforeAll { . "$PSScriptRoot/../../scripts/Launcher.Common.ps1" }

    It 'reports READY only when both processes and all probes are healthy' {
        Mock Test-ManagedServerProcess { $true }
        Mock Test-ByteMcpEndpoint { $true }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $true }
        Mock Test-TunnelReady { $true }
        $status = Get-ByteMcpStatus -State ([pscustomobject]@{})
        $status.Overall | Should -Be 'READY'
    }

    It 'reports DEGRADED when tunnel is running but not ready' {
        Mock Test-ManagedServerProcess { $true }
        Mock Test-ByteMcpEndpoint { $true }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $true }
        Mock Test-TunnelReady { $false }
        $status = Get-ByteMcpStatus -State ([pscustomobject]@{})
        $status.Overall | Should -Be 'DEGRADED'
        $status.Reason | Should -Match 'ready'
    }
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Status-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL because status helpers do not exist.

- [ ] **Step 3: Implement probes and observational status command**

Use `System.Net.Http.HttpClient` or `Invoke-WebRequest` with explicit timeout. For `http://127.0.0.1:8000/mcp`, treat any successful TCP/HTTP response including the expected raw `406` as liveness. For tunnel endpoints require HTTP 200 with body `live` and `ready` respectively.

`Status-ByteMCP.ps1` must read state and print status but never delete or rewrite `launcher-state.json`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Status-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 scripts/Status-ByteMCP.ps1 tests/launcher/Status-ByteMCP.Tests.ps1
git commit -m "feat: add launcher health status"
```

---

### Task 5: Background Startup, Duplicate Prevention, and Rollback

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Start-ByteMCP.ps1`
- Create: `tests/launcher/Start-ByteMCP.Tests.ps1`

**Interfaces:**
- Consumes all shared path, credential, state, identity, and probe helpers.
- Produces: `Start-ByteMcpBackgroundStack`, `Wait-ByteMcpEndpoint`, `Wait-TunnelReady`, `Stop-LauncherCreatedProcess`.
- `Start-ByteMCP.ps1` parameters: `[switch]$Foreground`, `[int]$StartupTimeoutSeconds = 30`.

- [ ] **Step 1: Write failing background-start tests**

```powershell
It 'does not start duplicate processes when launcher status is READY' {
    Mock Get-ByteMcpStatus { [pscustomobject]@{ Overall = 'READY' } }
    Mock Start-Process {}
    Start-ByteMcpBackgroundStack -Paths $script:paths -StartupTimeoutSeconds 5
    Should -Invoke Start-Process -Times 0
}

It 'rolls back the server when tunnel readiness fails' {
    Mock Start-LauncherServerProcess { [pscustomobject]@{ Id = 101 } }
    Mock Wait-ByteMcpEndpoint { $true }
    Mock Start-LauncherTunnelProcess { [pscustomobject]@{ Id = 202 } }
    Mock Wait-TunnelReady { $false }
    Mock Stop-LauncherCreatedProcess {}
    { Start-ByteMcpBackgroundStack -Paths $script:paths -StartupTimeoutSeconds 1 } | Should -Throw
    Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 202 } -Times 1
    Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 101 } -Times 1
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing startup helpers.

- [ ] **Step 3: Implement background startup**

Implementation requirements:

```powershell
$serverEnv = Get-ByteMcpServerEnvironment -UserProfile $env:USERPROFILE
```

Start server with the repo `.venv\Scripts\python.exe -m byte_mcp`, working directory set to repo root, redirecting stdout/stderr to current-session logs. Supply only the Byte-MCP environment values to the child without changing the persistent user environment.

Decrypt the Runtime API key to a `SecureString`, convert to plaintext only immediately before creating the tunnel child environment, set `CONTROL_PLANE_API_KEY` in the child environment, start:

```text
tunnel-client run --profile byte-mcp-local
```

then clear the launcher-held plaintext variable in a `finally` block.

Before each new background start, rotate current log files to a single `.previous.log` / `.previous.err.log` generation so log growth stays bounded.

Persist launcher state only after both server and tunnel probes succeed.

- [ ] **Step 4: Run startup tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS with no real tunnel connection because process creation and probes are mocked.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 scripts/Start-ByteMCP.ps1 tests/launcher/Start-ByteMCP.Tests.ps1
git commit -m "feat: add transactional background launcher"
```

---

### Task 6: Foreground Troubleshooting Mode

**Files:**
- Modify: `scripts/Start-ByteMCP.ps1`
- Modify: `tests/launcher/Start-ByteMCP.Tests.ps1`

**Interfaces:**
- Consumes validated launcher configuration and credential lifecycle.
- Produces foreground orchestration under the existing `-Foreground` switch.

- [ ] **Step 1: Write failing foreground-mode test**

```powershell
It 'uses visible child consoles in foreground mode and does not write managed background state' {
    Mock Start-LauncherForegroundServer {}
    Mock Start-LauncherForegroundTunnel {}
    Mock Write-LauncherState {}
    Invoke-ByteMcpStart -Foreground
    Should -Invoke Start-LauncherForegroundServer -Times 1
    Should -Invoke Start-LauncherForegroundTunnel -Times 1
    Should -Invoke Write-LauncherState -Times 0
}
```

- [ ] **Step 2: Run focused test and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL because foreground orchestration is not implemented.

- [ ] **Step 3: Implement foreground mode**

Foreground mode must use the same fixed server environment, encrypted credential, tunnel profile, and prerequisite checks as background mode. It may open visible `pwsh.exe` child consoles for server and tunnel diagnostics; it must not create a background `launcher-state.json` that later `Stop-ByteMCP.ps1` could mistake for a managed background stack.

- [ ] **Step 4: Run startup tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Start-ByteMCP.ps1 tests/launcher/Start-ByteMCP.Tests.ps1
git commit -m "feat: add launcher foreground mode"
```

---

### Task 7: Verified Stop and Idempotent Shutdown

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Stop-ByteMCP.ps1`
- Create: `tests/launcher/Stop-ByteMCP.Tests.ps1`

**Interfaces:**
- Produces: `Stop-ByteMcpManagedStack`, `Confirm-LauncherListenersStopped`.
- Consumes state and `Test-LauncherProcessIdentity` before every stop action.

- [ ] **Step 1: Write failing stop tests**

```powershell
It 'refuses to stop a process when identity cannot be verified' {
    Mock Read-LauncherState { $script:state }
    Mock Test-LauncherProcessIdentity { $false }
    Mock Stop-Process {}
    { Stop-ByteMcpManagedStack -StatePath $script:statePath } | Should -Throw
    Should -Invoke Stop-Process -Times 0
}

It 'is safe when no managed launcher state exists' {
    Mock Get-LauncherStateClassification { 'absent' }
    { Stop-ByteMcpManagedStack -StatePath $script:statePath } | Should -Not -Throw
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Stop-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing stop helpers.

- [ ] **Step 3: Implement verified stop**

Stop tunnel first, then server. For each recorded process, retrieve the live process and verify PID + normalized executable path + UTC start time before calling `Stop-Process`. After stopping, verify ports `8080` and `8000` no longer have launcher-owned listeners before deleting the state file. Malformed/unverifiable state must be reported without killing any process.

- [ ] **Step 4: Run stop tests and verify GREEN**

Run:

```powershell
Invoke-Pester -Path .\tests\launcher\Stop-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Launcher.Common.ps1 scripts/Stop-ByteMCP.ps1 tests/launcher/Stop-ByteMCP.Tests.ps1
git commit -m "feat: add verified launcher shutdown"
```

---

### Task 8: Pester Entry Point and Windows CI Gate

**Files:**
- Create: `scripts/Check-Launcher.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/Check.ps1`

**Interfaces:**
- Produces deterministic launcher test command: `./scripts/Check-Launcher.ps1`.

- [ ] **Step 1: Write the launcher check script and intentionally run before CI modification**

```powershell
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $IsWindows) {
    throw 'Byte-MCP launcher tests require Windows.'
}

if (-not (Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge [version]'5.0.0' })) {
    throw 'Pester 5 or newer is required.'
}

Invoke-Pester -Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'tests\launcher') -CI
if ($LASTEXITCODE -ne 0) { throw 'Launcher Pester suite failed.' }
Write-Host 'PASS: Byte-MCP launcher validation complete'
```

Run:

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: PASS locally once prior tasks are green.

- [ ] **Step 2: Add a Windows launcher CI job**

Add a dedicated job to `.github/workflows/ci.yml` that runs on `windows-latest`, installs/imports Pester 5+ if needed, and executes:

```powershell
pwsh -File .\scripts\Check-Launcher.ps1
```

Do not supply a real Runtime API key. All tunnel/process tests remain mocked.

- [ ] **Step 3: Wire local aggregate validation without breaking Ubuntu**

Update `scripts/Check.ps1` so the existing Python dependency/compile/Ruff/pytest sequence is unchanged. After Python tests, on Windows only, invoke `scripts/Check-Launcher.ps1`; on non-Windows print a clear launcher-test skip message.

- [ ] **Step 4: Run the full local gate**

Run:

```powershell
.\scripts\Check.ps1
```

Expected: Python validation passes, launcher Pester suite passes on Windows, final repository validation reports PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Check-Launcher.ps1 scripts/Check.ps1 .github/workflows/ci.yml
git commit -m "ci: validate Byte-MCP launcher on Windows"
```

---

### Task 9: Operator Documentation and Release Notes

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents exact operator commands and separates launcher infrastructure from future write authority.

- [ ] **Step 1: Update README with the launcher workflow**

Document exactly:

```powershell
# One-time setup
.\scripts\Setup-ByteMCP.ps1

# Daily background startup
.\scripts\Start-ByteMCP.ps1

# Status
.\scripts\Status-ByteMCP.ps1

# Stop
.\scripts\Stop-ByteMCP.ps1

# Troubleshooting
.\scripts\Start-ByteMCP.ps1 -Foreground
```

State that setup uses Windows user-bound DPAPI; machine-local state/log/credential files live under `%USERPROFILE%\.byte-mcp`; ChatGPT Web can use the existing Byte-MCP plugin only while the local server and tunnel are live; Launcher V1 does not add write authority.

- [ ] **Step 2: Update CHANGELOG**

Add a Launcher V1 entry covering one-command startup, DPAPI credential persistence, health/readiness verification, managed process state, safe shutdown, and Windows CI.

- [ ] **Step 3: Run documentation-sensitive validation**

Run:

```powershell
.\scripts\Check.ps1
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add README.md CHANGELOG.md
git commit -m "docs: document Byte-MCP launcher V1"
```

---

### Task 10: Full Automated Verification Gate

**Files:**
- No production changes unless evidence requires repair.

**Interfaces:**
- Verifies the complete automated launcher subsystem before live tunnel acceptance.

- [ ] **Step 1: Run launcher tests directly**

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: all launcher Pester tests PASS.

- [ ] **Step 2: Run full repository validation**

```powershell
.\scripts\Check.ps1
```

Expected: dependency check, compile, Ruff, Python tests, and Windows launcher tests all PASS.

- [ ] **Step 3: Inspect working tree and diff**

```powershell
git status --short
git diff --check
git log --oneline -10
```

Expected: no unintended files, no whitespace errors, and each prior task represented by a focused commit.

- [ ] **Step 4: If any verification fails, repair from evidence using a RED/GREEN commit pair where behavior changes**

Do not proceed to live acceptance until automated verification is fully green.

---

### Task 11: Live Windows Acceptance — Setup and Background Start

**Files:**
- Machine-local only under `%USERPROFILE%\.byte-mcp`; no committed changes unless live evidence exposes a defect.

**Interfaces:**
- Exercises real DPAPI, real Byte-MCP, real `tunnel-client`, and ChatGPT Web.

- [ ] **Step 1: Stop the currently manual server/tunnel stack**

Use the existing manual terminals to terminate the currently running Byte-MCP server and `tunnel-client` cleanly. Confirm ports `8000` and `8080` no longer listen before testing the launcher.

- [ ] **Step 2: Run one-time setup**

```powershell
.\scripts\Setup-ByteMCP.ps1
```

Enter the restricted Runtime API key only at the secure prompt.

Expected: setup validates prerequisites and creates `%USERPROFILE%\.byte-mcp\credentials\tunnel-runtime-key.dpapi` without printing the key.

- [ ] **Step 3: Prove credential is not plaintext**

```powershell
Get-Item "$env:USERPROFILE\.byte-mcp\credentials\tunnel-runtime-key.dpapi"
```

Do not print/decrypt the content for evidence. Confirm only that the file exists outside the repository.

- [ ] **Step 4: Start background stack**

```powershell
.\scripts\Start-ByteMCP.ps1
```

Expected final classification:

```text
BYTE-MCP READY
MCP server : ready
Tunnel     : ready
Root       : projects
Mode       : background
```

- [ ] **Step 5: Verify status**

```powershell
.\scripts\Status-ByteMCP.ps1
```

Expected: `Overall : READY` with server process running, MCP endpoint ready, tunnel process running, tunnel health healthy, tunnel ready ready, root `projects`.

---

### Task 12: Live ChatGPT Reconnection, Stop, Restart, and Foreground Acceptance

**Files:**
- Machine-local only unless evidence requires repair.

**Interfaces:**
- Completes user-facing acceptance of the one-command launcher.

- [ ] **Step 1: Verify ChatGPT invocation through launcher-started stack**

From ChatGPT Web with Byte-MCP enabled, call `list_roots` and confirm only `projects` is returned. Perform a harmless search/fetch of the existing remote canary if needed to prove end-to-end data flow.

- [ ] **Step 2: Stop the stack**

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Expected: verified tunnel process stops first, verified server stops second, state file is removed after successful shutdown.

- [ ] **Step 3: Prove listeners disappeared**

```powershell
Get-NetTCPConnection -LocalPort 8000,8080 -State Listen -ErrorAction SilentlyContinue
```

Expected: no launcher-owned listeners remain.

- [ ] **Step 4: Restart without re-entering credential**

```powershell
.\scripts\Start-ByteMCP.ps1
```

Expected: `READY` without rerunning setup or prompting for the Runtime API key.

- [ ] **Step 5: Verify ChatGPT reconnects**

Call `list_roots` again from ChatGPT Web. Expected: `projects` only.

- [ ] **Step 6: Stop background stack again**

```powershell
.\scripts\Stop-ByteMCP.ps1
```

Expected: clean shutdown.

- [ ] **Step 7: Smoke-test foreground troubleshooting mode**

```powershell
.\scripts\Start-ByteMCP.ps1 -Foreground
```

Expected: visible diagnostic consoles use the same AIProjects-only profile and tunnel profile. Manually terminate foreground children after confirming successful startup; no managed background state file should be left behind.

- [ ] **Step 8: Final acceptance decision**

Accept Launcher V1 only if all twelve live acceptance requirements from the design spec are satisfied, including no secret disclosure, one-command background startup, accurate status, safe stop, restart without credential re-entry, and functional ChatGPT reconnection.

---

## Final Review Checklist

Before merge/closeout, verify:

- Every launcher production behavior has a corresponding Pester test or explicit live acceptance step.
- No Runtime API key literal appears in Git history for this branch.
- `launcher-state.json` schema contains no credential/content/query/reference fields.
- `Status-ByteMCP.ps1` does not mutate state.
- `Stop-ByteMCP.ps1` never falls back to killing by process name.
- Background startup is transactional and rolls back on tunnel failure.
- Foreground mode does not create managed background state.
- Existing four-tool Byte-MCP read-only behavior remains unchanged.
- Windows and Ubuntu Python CI remain green; launcher tests are Windows-only.
- README explicitly says Launcher V1 is operational infrastructure and does not yet grant write authority.
