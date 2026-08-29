# Byte-MCP Launcher V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-command Windows launcher suite that securely starts, verifies, reports, and stops the accepted Byte-MCP read-only remote stack without re-entering the tunnel Runtime API key.

**Architecture:** Keep launcher responsibilities in PowerShell under `scripts/` and machine-local credential, runtime-state, and log data under `%USERPROFILE%\.byte-mcp\`. Shared launcher helpers live in one dot-sourced script so setup/start/status/stop use identical path, DPAPI, ownership, health, state, and rollback rules while the Python MCP service remains unchanged.

**Tech Stack:** PowerShell 7+, Windows DPAPI through `ConvertFrom-SecureString` / `ConvertTo-SecureString`, Pester 5+, existing Python 3.12 Byte-MCP runtime, OpenAI `tunnel-client`, GitHub Actions Windows CI.

**Spec:** `docs/superpowers/specs/2026-08-29-byte-mcp-launcher-v1-design.md`

## Global Constraints

- Byte-MCP authority remains read-only for Launcher V1.
- Approved remote root remains only `projects -> %USERPROFILE%\AIProjects`.
- Byte-MCP remains bound to `127.0.0.1:8000` with `streamable-http` transport.
- Tunnel profile remains `byte-mcp-local`, targeting `http://127.0.0.1:8000/mcp`.
- Runtime API key is entered only through a secure prompt and is never stored in plaintext, accepted as a normal command-line parameter, printed, or logged.
- Launcher state contains no secrets, fetched content, search terms, opaque MCP references, or arbitrary MCP payloads.
- Stop never kills a process that cannot be verified as launcher-owned.
- Startup never reports ready until Byte-MCP liveness and tunnel `/healthz` + `/readyz` checks pass.
- Failed startup rolls back launcher-created processes where safely possible.
- Status is observational and never mutates launcher state.
- Pester 5+ is the Windows launcher test framework.
- CI never requires a real Runtime API key and never opens a real OpenAI Secure MCP Tunnel.
- Existing Python validation via `scripts/Check.ps1` remains required and must continue to pass.

---

## File Map

### Create
- `scripts/Launcher.Common.ps1` — shared paths, configuration validation, DPAPI helpers, state serialization, process identity checks, probes, log rotation, and rollback helpers.
- `scripts/Setup-ByteMCP.ps1` — one-time launcher setup and encrypted Runtime API key storage.
- `scripts/Start-ByteMCP.ps1` — default background startup plus `-Foreground` troubleshooting mode.
- `scripts/Status-ByteMCP.ps1` — read-only process + endpoint classification.
- `scripts/Stop-ByteMCP.ps1` — verified shutdown of launcher-owned processes only.
- `scripts/Check-Launcher.ps1` — deterministic Pester entry point.
- `tests/launcher/Launcher.Common.Tests.ps1` — helper/config/state/DPAPI/process/probe tests.
- `tests/launcher/Setup-ByteMCP.Tests.ps1` — setup/credential lifecycle tests.
- `tests/launcher/Start-ByteMCP.Tests.ps1` — startup, duplicate prevention, environment, and rollback tests using mocks.
- `tests/launcher/Status-ByteMCP.Tests.ps1` — status classification tests.
- `tests/launcher/Stop-ByteMCP.Tests.ps1` — verified-stop and repeated-stop tests.

### Modify
- `.github/workflows/ci.yml` — add a Windows-only launcher test job while preserving existing Python jobs.
- `scripts/Check.ps1` — preserve current Python validation and invoke launcher validation on Windows only.
- `README.md` — document setup/start/status/stop/foreground workflow and machine-local paths.
- `CHANGELOG.md` — record Launcher V1 operational subsystem.

---

## Locked Shared Interfaces

```powershell
Get-ByteMcpLauncherPaths -RepoRoot <string> -UserProfile <string> -> PSCustomObject
Get-ByteMcpServerEnvironment -UserProfile <string> -> hashtable
Get-TunnelClientPath -> string
Assert-ByteMcpLauncherPrerequisites -Paths <PSCustomObject> [-SkipCredentialCheck] -> void
Protect-ByteMcpCredential -Credential <SecureString> -Path <string> -> void
Unprotect-ByteMcpCredential -Path <string> -> SecureString
Assert-CredentialWriteAllowed -Path <string> -ReplaceCredential <bool> -> void
New-LauncherState (...) -> PSCustomObject
Write-LauncherState -State <PSCustomObject> -Path <string> -> void
Read-LauncherState -Path <string> -> PSCustomObject
Get-LauncherStateClassification -StatePath <string> -> absent|malformed|stale|active
Test-LauncherProcessIdentity -Record <PSCustomObject> -Process <Process> -> bool
Test-ByteMcpEndpoint -> bool
Test-TunnelHealth -> bool
Test-TunnelReady -> bool
Get-ByteMcpStatus -State <PSCustomObject> -> PSCustomObject
Start-ByteMcpBackgroundStack -Paths <PSCustomObject> -StartupTimeoutSeconds <int> -> PSCustomObject
Stop-ByteMcpManagedStack -StatePath <string> -> void
```

State child identity fields are exactly:

```json
{
  "pid": 12345,
  "executable_path": "C:\\...\\python.exe",
  "started_at_utc": "2026-08-29T10:00:00.0000000Z"
}
```

`schema_version` is `1`.

---

### Task 1: Shared Launcher Configuration and Prerequisite Contract

**Files:**
- Create: `scripts/Launcher.Common.ps1`
- Create: `tests/launcher/Launcher.Common.Tests.ps1`

**Interfaces:**
- Produces: `Get-ByteMcpLauncherPaths`, `Get-ByteMcpServerEnvironment`, `Get-TunnelClientPath`, `Assert-ByteMcpLauncherPrerequisites`.

- [ ] **Step 1: Write the failing configuration tests**

```powershell
Describe 'Launcher configuration contract' {
    BeforeAll { . "$PSScriptRoot/../../scripts/Launcher.Common.ps1" }

    It 'uses the machine-local .byte-mcp runtime area' {
        $paths = Get-ByteMcpLauncherPaths -RepoRoot 'C:\repo' -UserProfile 'C:\Users\test'
        $paths.CredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
        $paths.StateFile | Should -Be 'C:\Users\test\.byte-mcp\runtime\launcher-state.json'
        $paths.TunnelProfile | Should -Be 'byte-mcp-local'
    }

    It 'builds the accepted AIProjects-only Byte-MCP environment' {
        $map = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
        $map.BYTE_MCP_ROOTS_FILE | Should -Be 'C:\Users\test\.byte-mcp\roots.web.json'
        $map.BYTE_MCP_AUDIT_FILE | Should -Be 'C:\Users\test\.byte-mcp\audit.web.jsonl'
        $map.BYTE_MCP_HOST | Should -Be '127.0.0.1'
        $map.BYTE_MCP_PORT | Should -Be '8000'
        $map.BYTE_MCP_TRANSPORT | Should -Be 'streamable-http'
        $map.BYTE_MCP_MAX_FILE_BYTES | Should -Be '1000000'
        $map.BYTE_MCP_MAX_RESPONSE_CHARS | Should -Be '10000'
        $map.BYTE_MCP_MAX_SEARCH_FILES | Should -Be '20000'
        $map.BYTE_MCP_CONTENT_SEARCH_MAX_BYTES | Should -Be '250000'
    }
}
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: FAIL because the shared script/functions do not exist.

- [ ] **Step 3: Implement the shared configuration functions**

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ByteMcpLauncherPaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'
    [PSCustomObject]@{
        RepoRoot          = $RepoRoot
        PythonPath        = Join-Path $RepoRoot '.venv\Scripts\python.exe'
        LocalRoot         = $localRoot
        RootsFile         = Join-Path $localRoot 'roots.web.json'
        AuditFile         = Join-Path $localRoot 'audit.web.jsonl'
        CredentialFile    = Join-Path $localRoot 'credentials\tunnel-runtime-key.dpapi'
        RuntimeDir        = Join-Path $localRoot 'runtime'
        StateFile         = Join-Path $localRoot 'runtime\launcher-state.json'
        LogsDir           = Join-Path $localRoot 'logs'
        ServerStdOut      = Join-Path $localRoot 'logs\byte-mcp-server.log'
        ServerStdErr      = Join-Path $localRoot 'logs\byte-mcp-server.err.log'
        TunnelStdOut      = Join-Path $localRoot 'logs\tunnel-client.log'
        TunnelStdErr      = Join-Path $localRoot 'logs\tunnel-client.err.log'
        TunnelProfile     = 'byte-mcp-local'
        TunnelProfileFile = Join-Path $env:APPDATA 'tunnel-client\byte-mcp-local.yaml'
    }
}

function Get-ByteMcpServerEnvironment {
    [CmdletBinding()]
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

function Get-TunnelClientPath {
    [CmdletBinding()]
    param()
    (Get-Command tunnel-client -CommandType Application -ErrorAction Stop).Source
}

function Assert-ByteMcpLauncherPrerequisites {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [switch] $SkipCredentialCheck
    )

    if (-not $IsWindows) { throw 'Byte-MCP Launcher V1 requires Windows.' }
    if (-not (Test-Path -LiteralPath $Paths.RepoRoot -PathType Container)) { throw 'Byte-MCP repository path is missing.' }
    if (-not (Test-Path -LiteralPath $Paths.PythonPath -PathType Leaf)) { throw 'Byte-MCP virtual environment Python is missing.' }
    if (-not (Test-Path -LiteralPath $Paths.RootsFile -PathType Leaf)) { throw 'AIProjects-only roots.web.json is missing.' }
    if (-not (Test-Path -LiteralPath $Paths.TunnelProfileFile -PathType Leaf)) { throw 'Tunnel profile byte-mcp-local is missing.' }
    $null = Get-TunnelClientPath
    if (-not $SkipCredentialCheck -and -not (Test-Path -LiteralPath $Paths.CredentialFile -PathType Leaf)) {
        throw 'Encrypted tunnel Runtime API key is missing. Run Setup-ByteMCP.ps1.'
    }
}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

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
- Produces: `Protect-ByteMcpCredential`, `Unprotect-ByteMcpCredential`, `Assert-CredentialWriteAllowed`, `Setup-ByteMCP.ps1 -ReplaceCredential`.

- [ ] **Step 1: Write failing credential tests**

```powershell
Describe 'Byte-MCP credential lifecycle' {
    BeforeAll { . "$PSScriptRoot/../../scripts/Launcher.Common.ps1" }

    It 'round-trips a credential through Windows user-bound protection' -Skip:(!$IsWindows) {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        $secret = ConvertTo-SecureString 'test-secret-value' -AsPlainText -Force
        Protect-ByteMcpCredential -Credential $secret -Path $path
        $roundTrip = Unprotect-ByteMcpCredential -Path $path
        [System.Net.NetworkCredential]::new('', $roundTrip).Password | Should -Be 'test-secret-value'
        (Get-Content -LiteralPath $path -Raw) | Should -Not -Match 'test-secret-value'
    }

    It 'refuses accidental credential replacement' {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        Set-Content -LiteralPath $path -Value 'existing'
        { Assert-CredentialWriteAllowed -Path $path -ReplaceCredential:$false } | Should -Throw
    }
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Setup-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL because credential helpers do not exist.

- [ ] **Step 3: Implement credential helpers and setup**

```powershell
function Assert-CredentialWriteAllowed {
    param([string] $Path, [bool] $ReplaceCredential)
    if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $ReplaceCredential) {
        throw 'Encrypted Runtime API key already exists. Use -ReplaceCredential to rotate it.'
    }
}

function Protect-ByteMcpCredential {
    param([SecureString] $Credential, [string] $Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $protected = ConvertFrom-SecureString -SecureString $Credential
    [System.IO.File]::WriteAllText($Path, $protected, [System.Text.UTF8Encoding]::new($false))
}

function Unprotect-ByteMcpCredential {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Encrypted Runtime API key is missing.' }
    ConvertTo-SecureString -String ([System.IO.File]::ReadAllText($Path).Trim())
}
```

Create `Setup-ByteMCP.ps1` with no API-key parameter:

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

- [ ] **Step 4: Run and verify GREEN**

```powershell
Invoke-Pester -Path .\tests\launcher\Setup-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS on Windows.

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

- [ ] **Step 1: Write failing state tests**

```powershell
It 'serializes state without secret-bearing fields' {
    $state = New-LauncherState -RepoPath 'C:\repo' -Mode 'background' `
        -ServerPid 100 -ServerExecutable 'C:\Python\python.exe' -ServerStartedAtUtc '2026-08-29T10:00:00Z' `
        -TunnelPid 200 -TunnelExecutable 'C:\OpenAI\tunnel-client.exe' -TunnelStartedAtUtc '2026-08-29T10:00:01Z'
    ($state | ConvertTo-Json -Depth 5) | Should -Not -Match 'API_KEY|credential|secret|content|query|reference'
    $state.schema_version | Should -Be 1
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Launcher.Common.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing state helpers.

- [ ] **Step 3: Implement exact state and identity behavior**

```powershell
function New-LauncherChildRecord {
    param([int] $Pid, [string] $ExecutablePath, [string] $StartedAtUtc)
    [PSCustomObject]@{
        pid = $Pid
        executable_path = [System.IO.Path]::GetFullPath($ExecutablePath)
        started_at_utc = ([datetime]$StartedAtUtc).ToUniversalTime().ToString('o')
    }
}

function New-LauncherState {
    param(
        [string] $RepoPath, [string] $Mode,
        [int] $ServerPid, [string] $ServerExecutable, [string] $ServerStartedAtUtc,
        [int] $TunnelPid, [string] $TunnelExecutable, [string] $TunnelStartedAtUtc
    )
    [PSCustomObject]@{
        schema_version = 1
        started_at_utc = [datetime]::UtcNow.ToString('o')
        mode = $Mode
        repo_path = $RepoPath
        root_profile = 'projects'
        tunnel_profile = 'byte-mcp-local'
        server = New-LauncherChildRecord $ServerPid $ServerExecutable $ServerStartedAtUtc
        tunnel = New-LauncherChildRecord $TunnelPid $TunnelExecutable $TunnelStartedAtUtc
    }
}

function Write-LauncherState {
    param([pscustomobject] $State, [string] $Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllText($tmp, ($State | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Read-LauncherState {
    param([string] $Path)
    try { $state = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Malformed launcher state: $($_.Exception.Message)" }
    if ($state.schema_version -ne 1) { throw 'Unsupported launcher state schema.' }
    $state
}

function Test-LauncherProcessIdentity {
    param([pscustomobject] $Record, $Process)
    if ($null -eq $Process -or $Process.Id -ne [int]$Record.pid) { return $false }
    $samePath = [string]::Equals(
        [System.IO.Path]::GetFullPath($Process.Path),
        [System.IO.Path]::GetFullPath([string]$Record.executable_path),
        [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $samePath) { return $false }
    [math]::Abs(($Process.StartTime.ToUniversalTime() - ([datetime]$Record.started_at_utc).ToUniversalTime()).TotalSeconds) -lt 1
}
```

`Get-LauncherStateClassification`: missing file -> `absent`; JSON/schema failure -> `malformed`; either recorded process absent or identity mismatch -> `stale`; both identities verified -> `active`.

- [ ] **Step 4: Run and verify GREEN**

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

### Task 4: Health Probes and Read-Only Status Classification

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Status-ByteMCP.ps1`
- Create: `tests/launcher/Status-ByteMCP.Tests.ps1`

**Interfaces:**
- Produces: `Invoke-LauncherHttpProbe`, `Test-ByteMcpEndpoint`, `Test-TunnelHealth`, `Test-TunnelReady`, `Get-ByteMcpStatus`.

- [ ] **Step 1: Write failing status tests**

```powershell
It 'reports READY only when all runtime checks pass' {
    Mock Test-ManagedServerProcess { $true }
    Mock Test-ByteMcpEndpoint { $true }
    Mock Test-ManagedTunnelProcess { $true }
    Mock Test-TunnelHealth { $true }
    Mock Test-TunnelReady { $true }
    (Get-ByteMcpStatus -State ([pscustomobject]@{})).Overall | Should -Be 'READY'
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Status-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing status helpers.

- [ ] **Step 3: Implement probes**

```powershell
function Invoke-LauncherHttpProbe {
    param([string] $Uri, [int] $TimeoutSeconds = 3)
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [timespan]::FromSeconds($TimeoutSeconds)
    try {
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        [pscustomobject]@{
            reachable = $true
            status_code = [int]$response.StatusCode
            body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult().Trim()
        }
    } catch {
        [pscustomobject]@{ reachable = $false; status_code = $null; body = '' }
    } finally {
        $client.Dispose(); $handler.Dispose()
    }
}
function Test-ByteMcpEndpoint { (Invoke-LauncherHttpProbe 'http://127.0.0.1:8000/mcp').reachable }
function Test-TunnelHealth { $p = Invoke-LauncherHttpProbe 'http://127.0.0.1:8080/healthz'; $p.status_code -eq 200 -and $p.body -eq 'live' }
function Test-TunnelReady { $p = Invoke-LauncherHttpProbe 'http://127.0.0.1:8080/readyz'; $p.status_code -eq 200 -and $p.body -eq 'ready' }
```

The raw MCP endpoint's expected `406` counts as liveness because it is reachable. `Get-ByteMcpStatus` returns `STOPPED` for absent state, `DEGRADED` for malformed/stale/unhealthy state, and `READY` only when both verified processes plus MCP endpoint, tunnel health, and tunnel readiness succeed. `Status-ByteMCP.ps1` only reads and prints status; it never rewrites/deletes state.

- [ ] **Step 4: Run and verify GREEN**

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

### Task 5: Transactional Background Startup and Bounded Logs

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Start-ByteMCP.ps1`
- Create: `tests/launcher/Start-ByteMCP.Tests.ps1`

**Interfaces:**
- Produces: `Rotate-LauncherLog`, `Wait-LauncherCondition`, `Start-LauncherServerProcess`, `Start-LauncherTunnelProcess`, `Stop-LauncherCreatedProcess`, `Start-ByteMcpBackgroundStack`.
- `Start-ByteMCP.ps1`: `[switch] $Foreground`, `[int] $StartupTimeoutSeconds = 30`.

- [ ] **Step 1: Write failing duplicate/rollback tests**

```powershell
It 'does not create a duplicate stack when status is READY' {
    Mock Get-ByteMcpStatus { [pscustomobject]@{ Overall = 'READY' } }
    Mock Start-LauncherServerProcess {}
    Start-ByteMcpBackgroundStack -Paths $script:paths -StartupTimeoutSeconds 5
    Should -Invoke Start-LauncherServerProcess -Times 0
}

It 'rolls back both children when tunnel readiness fails' {
    Mock Start-LauncherServerProcess { [pscustomobject]@{ Id = 101; Path = 'C:\python.exe'; StartTime = Get-Date } }
    Mock Wait-ByteMcpEndpoint { $true }
    Mock Start-LauncherTunnelProcess { [pscustomobject]@{ Id = 202; Path = 'C:\tunnel-client.exe'; StartTime = Get-Date } }
    Mock Wait-TunnelReady { $false }
    Mock Stop-LauncherCreatedProcess {}
    { Start-ByteMcpBackgroundStack -Paths $script:paths -StartupTimeoutSeconds 1 } | Should -Throw
    Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 202 } -Times 1
    Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 101 } -Times 1
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing startup helpers.

- [ ] **Step 3: Implement bounded logs and child launch**

```powershell
function Rotate-LauncherLog {
    param([string] $Path)
    $previous = "$Path.previous"
    if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Force }
    if (Test-Path -LiteralPath $Path) { Move-Item -LiteralPath $Path -Destination $previous -Force }
}

function Wait-LauncherCondition {
    param([scriptblock] $Condition, [int] $TimeoutSeconds)
    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds 250
    } while ([datetime]::UtcNow -lt $deadline)
    $false
}
```

For background children use `Start-Process -PassThru -RedirectStandardOutput ... -RedirectStandardError ...`. Inject only process-scope environment values immediately around `Start-Process` and restore all parent values in `finally`; never write them to user/machine persistent environment.

Server launch:

```powershell
$map = Get-ByteMcpServerEnvironment -UserProfile $env:USERPROFILE
$prior = @{}
try {
    foreach ($name in $map.Keys) {
        $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $map[$name], 'Process')
    }
    $process = Start-Process -FilePath $Paths.PythonPath -ArgumentList '-m','byte_mcp' -WorkingDirectory $Paths.RepoRoot -PassThru -RedirectStandardOutput $Paths.ServerStdOut -RedirectStandardError $Paths.ServerStdErr
} finally {
    foreach ($name in $map.Keys) { [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process') }
}
```

Tunnel launch:

```powershell
$secure = Unprotect-ByteMcpCredential -Path $Paths.CredentialFile
$plain = $null
$priorKey = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process')
try {
    $plain = [System.Net.NetworkCredential]::new('', $secure).Password
    [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $plain, 'Process')
    $process = Start-Process -FilePath (Get-TunnelClientPath) -ArgumentList 'run','--profile',$Paths.TunnelProfile -WorkingDirectory $Paths.RepoRoot -PassThru -RedirectStandardOutput $Paths.TunnelStdOut -RedirectStandardError $Paths.TunnelStdErr
} finally {
    [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $priorKey, 'Process')
    $plain = $null; $secure = $null
}
```

Exact startup sequence: prerequisites -> classify existing state -> if READY report existing stack and return -> if state stale clean only the stale state file after proving recorded PIDs are absent/unverified -> reject unmanaged port conflicts -> rotate current logs to one `.previous` generation -> start server -> wait MCP liveness -> start tunnel -> wait `/healthz` -> wait `/readyz` -> atomically write verified state -> return READY. Any failure stops only children created by that invocation in reverse order and removes any partial state file.

- [ ] **Step 4: Run and verify GREEN**

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: PASS with process/probe calls mocked; no real tunnel opens.

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
- Produces: `Start-ByteMcpForegroundStack` under `-Foreground`.

- [ ] **Step 1: Write failing foreground test**

```powershell
It 'does not write managed state in foreground mode' {
    Mock Write-LauncherState {}
    Mock Start-LauncherForegroundServer { [pscustomobject]@{ Id = 101 } }
    Mock Start-LauncherForegroundTunnel { [pscustomobject]@{ Id = 202 } }
    Mock Wait-ByteMcpEndpoint { $true }
    Mock Wait-TunnelReady { $true }
    Start-ByteMcpForegroundStack -Paths $script:paths -StartupTimeoutSeconds 1
    Should -Invoke Write-LauncherState -Times 0
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Start-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL because foreground orchestration is absent.

- [ ] **Step 3: Implement foreground behavior**

Use the same process-scope environment injection and DPAPI credential retrieval as Task 5, but start both children with `Start-Process -NoNewWindow -PassThru` and no output redirection so diagnostics remain visible in the current PowerShell console. Sequence: start server -> wait MCP liveness -> start tunnel -> wait health/readiness -> print `BYTE-MCP FOREGROUND READY` -> wait on tunnel. In `finally`, stop only the two foreground children. Never call `Write-LauncherState`.

- [ ] **Step 4: Run and verify GREEN**

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

- [ ] **Step 1: Write failing stop tests**

```powershell
It 'never stops an unverified process' {
    Mock Get-LauncherStateClassification { 'active' }
    Mock Read-LauncherState { $script:state }
    Mock Get-Process { [pscustomobject]@{ Id = 123; Path = 'C:\other.exe'; StartTime = Get-Date } }
    Mock Test-LauncherProcessIdentity { $false }
    Mock Stop-Process {}
    { Stop-ByteMcpManagedStack -StatePath $script:statePath } | Should -Throw
    Should -Invoke Stop-Process -Times 0
}

It 'is safe when no managed state exists' {
    Mock Get-LauncherStateClassification { 'absent' }
    { Stop-ByteMcpManagedStack -StatePath $script:statePath } | Should -Not -Throw
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
Invoke-Pester -Path .\tests\launcher\Stop-ByteMCP.Tests.ps1 -Output Detailed
```

Expected: FAIL on missing stop helpers.

- [ ] **Step 3: Implement verified shutdown**

```powershell
$classification = Get-LauncherStateClassification -StatePath $StatePath
if ($classification -eq 'absent') { return }
if ($classification -in @('malformed','stale')) { throw "Launcher state is $classification; refusing unverified shutdown." }
$state = Read-LauncherState -Path $StatePath
foreach ($role in @('tunnel','server')) {
    $record = $state.$role
    $process = Get-Process -Id $record.pid -ErrorAction Stop
    if (-not (Test-LauncherProcessIdentity -Record $record -Process $process)) {
        throw "Refusing to stop unverified $role process."
    }
    Stop-Process -Id $process.Id -ErrorAction Stop
    Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
}
if (-not (Confirm-LauncherListenersStopped)) { throw 'Launcher-owned listeners did not shut down cleanly.' }
Remove-Item -LiteralPath $StatePath -Force
```

`Confirm-LauncherListenersStopped` inspects ports 8000 and 8080 and succeeds only when no launcher-owned listener remains. Never fall back to killing by executable name.

- [ ] **Step 4: Run and verify GREEN**

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

### Task 8: Launcher Test Entry Point and Windows CI

**Files:**
- Create: `scripts/Check-Launcher.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/Check.ps1`

**Interfaces:**
- Produces deterministic `./scripts/Check-Launcher.ps1` gate.

- [ ] **Step 1: Create launcher test entry point**

```powershell
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Byte-MCP launcher tests require Windows.' }
$pester = Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge [version]'5.0.0' } | Sort-Object Version -Descending | Select-Object -First 1
if ($null -eq $pester) { throw 'Pester 5 or newer is required.' }
Import-Module $pester.Path -Force
$repoRoot = Split-Path -Parent $PSScriptRoot
$result = Invoke-Pester -Path (Join-Path $repoRoot 'tests\launcher') -PassThru -Output Detailed
if ($result.FailedCount -gt 0) { throw "Launcher Pester suite failed: $($result.FailedCount) failed." }
Write-Host 'PASS: Byte-MCP launcher validation complete'
```

- [ ] **Step 2: Add Windows launcher CI job**

Add `launcher-test` on `windows-latest`: checkout -> ensure Pester 5+ -> `pwsh -File .\scripts\Check-Launcher.ps1`. No Runtime API key and no live tunnel.

- [ ] **Step 3: Extend aggregate local gate**

Keep current dependency/compile/Ruff/pytest sequence unchanged, then:

```powershell
if ($IsWindows) {
    Write-Host "`n=== LAUNCHER TESTS ==="
    & (Join-Path $PSScriptRoot 'Check-Launcher.ps1')
} else {
    Write-Host "`n=== LAUNCHER TESTS ==="
    Write-Host 'SKIP: Windows-only launcher tests'
}
```

- [ ] **Step 4: Run full local gate**

```powershell
.\scripts\Check.ps1
```

Expected: Python validation and Pester launcher validation PASS on Windows.

- [ ] **Step 5: Commit**

```powershell
git add scripts/Check-Launcher.ps1 scripts/Check.ps1 .github/workflows/ci.yml
git commit -m "ci: validate Byte-MCP launcher on Windows"
```

---

### Task 9: Operator Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document exact commands**

```powershell
.\scripts\Setup-ByteMCP.ps1
.\scripts\Start-ByteMCP.ps1
.\scripts\Status-ByteMCP.ps1
.\scripts\Stop-ByteMCP.ps1
.\scripts\Start-ByteMCP.ps1 -Foreground
```

Document Windows-user-bound DPAPI, `%USERPROFILE%\.byte-mcp` machine-local data, the fact that ChatGPT works only while the local server+tunnel are live, and that Launcher V1 does not add write authority.

- [ ] **Step 2: Add CHANGELOG entry**

Record one-command startup, DPAPI storage, health/readiness gates, process ownership state, one-generation log rotation, verified shutdown, foreground mode, and Windows CI.

- [ ] **Step 3: Run validation**

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

### Task 10: Automated Verification Gate

- [ ] Run `./scripts/Check-Launcher.ps1`; expect all Pester tests PASS.
- [ ] Run `./scripts/Check.ps1`; expect dependency, compile, Ruff, Python tests, and launcher tests PASS.
- [ ] Run `git status --short`, `git diff --check`, `git log --oneline -10`; expect no unintended files or whitespace failures.
- [ ] If evidence fails, preserve the failing result, make the smallest correction, rerun the focused gate, then rerun the full gate. Behavior-changing repairs receive RED/GREEN commits.

---

### Task 11: Live Windows Acceptance — Setup and Background Stack

- [ ] Stop current manual Byte-MCP/tunnel terminals.
- [ ] Run `Get-NetTCPConnection -LocalPort 8000,8080 -State Listen -ErrorAction SilentlyContinue`; expect no listeners.
- [ ] Run `./scripts/Setup-ByteMCP.ps1`; enter the restricted Runtime API key only at secure prompt.
- [ ] Confirm `%USERPROFILE%\.byte-mcp\credentials\tunnel-runtime-key.dpapi` exists without printing its contents.
- [ ] Run `./scripts/Start-ByteMCP.ps1`; expect `BYTE-MCP READY`, server ready, tunnel ready, root projects, mode background.
- [ ] Run `./scripts/Status-ByteMCP.ps1`; expect `Overall : READY`.

---

### Task 12: Live ChatGPT Reconnection, Stop, Restart, and Foreground Acceptance

- [ ] In ChatGPT Web call `list_roots`; expect only `projects`.
- [ ] Run `./scripts/Stop-ByteMCP.ps1`; expect verified tunnel-first/server-second shutdown.
- [ ] Run `Get-NetTCPConnection -LocalPort 8000,8080 -State Listen -ErrorAction SilentlyContinue`; expect no launcher-owned listeners.
- [ ] Run `./scripts/Start-ByteMCP.ps1` again; expect READY without setup or credential prompt.
- [ ] Call `list_roots` again in ChatGPT; expect `projects` only.
- [ ] Stop the background stack cleanly.
- [ ] Run `./scripts/Start-ByteMCP.ps1 -Foreground`; expect live diagnostics in the current console, same roots/tunnel profile, and no managed background state file. Terminate with Ctrl+C after readiness.
- [ ] Accept Launcher V1 only if no secret appears in Git/state/logs/console, startup is one command, status is accurate, stop is ownership-safe, restart requires no credential re-entry, and ChatGPT reconnects.

---

## Plan Self-Review Result

- **Spec coverage:** setup, DPAPI lifecycle, fixed AIProjects profile, background/foreground modes, transactional rollback, state ownership, observational status, verified stop, bounded logs, Pester, Windows CI, documentation, and live acceptance are mapped to tasks.
- **Placeholder scan:** no `TBD`, `TODO`, “implement later,” or unspecified test/failure placeholders remain.
- **Interface consistency:** function names, state schema, environment names, tunnel profile, ports, and status classifications are consistent across tasks.
- **Security check:** no real credential value appears in the plan and the live key is never passed as a normal command-line argument.
