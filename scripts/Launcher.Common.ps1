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
    param(
        [Parameter(Mandatory)] [string] $UserProfile
    )

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

    if (-not $IsWindows) {
        throw 'Byte-MCP Launcher V1 requires Windows.'
    }

    if (-not (Test-Path -LiteralPath $Paths.RepoRoot -PathType Container)) {
        throw 'Byte-MCP repository path is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.PythonPath -PathType Leaf)) {
        throw 'Byte-MCP virtual environment Python is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.RootsFile -PathType Leaf)) {
        throw 'AIProjects-only roots.web.json is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.TunnelProfileFile -PathType Leaf)) {
        throw 'Tunnel profile byte-mcp-local is missing.'
    }

    $null = Get-TunnelClientPath

    if (-not $SkipCredentialCheck -and -not (Test-Path -LiteralPath $Paths.CredentialFile -PathType Leaf)) {
        throw 'Encrypted tunnel Runtime API key is missing. Run Setup-ByteMCP.ps1.'
    }
}

function Assert-CredentialWriteAllowed {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [bool] $ReplaceCredential
    )

    if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $ReplaceCredential) {
        throw 'Encrypted Runtime API key already exists. Use -ReplaceCredential to rotate it.'
    }
}

function Protect-ByteMcpCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [SecureString] $Credential,
        [Parameter(Mandatory)] [string] $Path
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $protected = ConvertFrom-SecureString -SecureString $Credential
    [System.IO.File]::WriteAllText(
        $Path,
        $protected,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Unprotect-ByteMcpCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Encrypted Runtime API key is missing.'
    }

    $protected = [System.IO.File]::ReadAllText($Path).Trim()
    ConvertTo-SecureString -String $protected
}

function New-LauncherChildRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [int] $ProcessId,
        [Parameter(Mandatory)] [string] $ExecutablePath,
        [Parameter(Mandatory)] [string] $StartedAtUtc
    )

    [PSCustomObject]@{
        pid = $ProcessId
        executable_path = [System.IO.Path]::GetFullPath($ExecutablePath)
        started_at_utc = ([datetime] $StartedAtUtc).ToUniversalTime().ToString('o')
    }
}

function New-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RepoPath,
        [Parameter(Mandatory)] [string] $Mode,
        [Parameter(Mandatory)] [int] $ServerPid,
        [Parameter(Mandatory)] [string] $ServerExecutable,
        [Parameter(Mandatory)] [string] $ServerStartedAtUtc,
        [Parameter(Mandatory)] [int] $TunnelPid,
        [Parameter(Mandatory)] [string] $TunnelExecutable,
        [Parameter(Mandatory)] [string] $TunnelStartedAtUtc
    )

    [PSCustomObject]@{
        schema_version = 1
        started_at_utc = [datetime]::UtcNow.ToString('o')
        mode = $Mode
        repo_path = $RepoPath
        root_profile = 'projects'
        tunnel_profile = 'byte-mcp-local'
        server = New-LauncherChildRecord -ProcessId $ServerPid -ExecutablePath $ServerExecutable -StartedAtUtc $ServerStartedAtUtc
        tunnel = New-LauncherChildRecord -ProcessId $TunnelPid -ExecutablePath $TunnelExecutable -StartedAtUtc $TunnelStartedAtUtc
    }
}

function Write-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $State,
        [Parameter(Mandatory)] [string] $Path
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    $tempPath = "$Path.tmp"
    $json = $State | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText(
        $tempPath,
        $json,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Read-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    try {
        $state = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Malformed launcher state: $($_.Exception.Message)"
    }

    if ($state.schema_version -ne 1) {
        throw 'Unsupported launcher state schema.'
    }

    $state
}

function Test-LauncherProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Record,
        [Parameter()] $Process
    )

    if ($null -eq $Process -or [int] $Process.Id -ne [int] $Record.pid) {
        return $false
    }

    try {
        $processPath = [System.IO.Path]::GetFullPath([string] $Process.Path)
        $recordPath = [System.IO.Path]::GetFullPath([string] $Record.executable_path)
    }
    catch {
        return $false
    }

    if (-not [string]::Equals($processPath, $recordPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }

    try {
        $processStarted = $Process.StartTime.ToUniversalTime()
        $recordStarted = ([datetime] $Record.started_at_utc).ToUniversalTime()
    }
    catch {
        return $false
    }

    [math]::Abs(($processStarted - $recordStarted).TotalSeconds) -lt 1
}

function Get-LauncherStateClassification {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $StatePath
    )

    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
        return 'absent'
    }

    try {
        $state = Read-LauncherState -Path $StatePath
    }
    catch {
        return 'malformed'
    }

    foreach ($role in @('server', 'tunnel')) {
        $record = $state.$role
        try {
            $process = Get-Process -Id ([int] $record.pid) -ErrorAction Stop
        }
        catch {
            return 'stale'
        }

        if (-not (Test-LauncherProcessIdentity -Record $record -Process $process)) {
            return 'stale'
        }
    }

    'active'
}

function Invoke-LauncherHttpProbe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Uri,
        [int] $TimeoutSeconds = 3
    )

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [timespan]::FromSeconds($TimeoutSeconds)

    try {
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        [PSCustomObject]@{
            reachable = $true
            status_code = [int] $response.StatusCode
            body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult().Trim()
        }
    }
    catch {
        [PSCustomObject]@{
            reachable = $false
            status_code = $null
            body = ''
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Test-ByteMcpEndpoint {
    [CmdletBinding()]
    param()

    (Invoke-LauncherHttpProbe -Uri 'http://127.0.0.1:8000/mcp').reachable
}

function Test-TunnelHealth {
    [CmdletBinding()]
    param()

    $probe = Invoke-LauncherHttpProbe -Uri 'http://127.0.0.1:8080/healthz'
    $probe.reachable -and $probe.status_code -eq 200 -and $probe.body -eq 'live'
}

function Test-TunnelReady {
    [CmdletBinding()]
    param()

    $probe = Invoke-LauncherHttpProbe -Uri 'http://127.0.0.1:8080/readyz'
    $probe.reachable -and $probe.status_code -eq 200 -and $probe.body -eq 'ready'
}

function Test-ManagedServerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $State
    )

    try {
        $process = Get-Process -Id ([int] $State.server.pid) -ErrorAction Stop
    }
    catch {
        return $false
    }

    Test-LauncherProcessIdentity -Record $State.server -Process $process
}

function Test-ManagedTunnelProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $State
    )

    try {
        $process = Get-Process -Id ([int] $State.tunnel.pid) -ErrorAction Stop
    }
    catch {
        return $false
    }

    Test-LauncherProcessIdentity -Record $State.tunnel -Process $process
}

function Get-ByteMcpStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $State
    )

    $serverProcess = Test-ManagedServerProcess -State $State
    $mcpEndpoint = Test-ByteMcpEndpoint
    $tunnelProcess = Test-ManagedTunnelProcess -State $State
    $tunnelHealth = Test-TunnelHealth
    $tunnelReady = Test-TunnelReady
    $overall = if ($serverProcess -and $mcpEndpoint -and $tunnelProcess -and $tunnelHealth -and $tunnelReady) {
        'READY'
    }
    else {
        'DEGRADED'
    }

    [PSCustomObject]@{
        Overall = $overall
        ServerProcess = $serverProcess
        McpEndpoint = $mcpEndpoint
        TunnelProcess = $tunnelProcess
        TunnelHealth = $tunnelHealth
        TunnelReady = $tunnelReady
    }
}

function Rotate-LauncherLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $previous = "$Path.previous"
    if (Test-Path -LiteralPath $previous) {
        Remove-Item -LiteralPath $previous -Force
    }
    if (Test-Path -LiteralPath $Path) {
        Move-Item -LiteralPath $Path -Destination $previous -Force
    }
}

function Wait-LauncherCondition {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [scriptblock] $Condition,
        [Parameter(Mandatory)] [int] $TimeoutSeconds
    )

    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ([datetime]::UtcNow -lt $deadline)

    $false
}

function Wait-ByteMcpEndpoint {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [int] $TimeoutSeconds)
    Wait-LauncherCondition -TimeoutSeconds $TimeoutSeconds -Condition { Test-ByteMcpEndpoint }
}

function Wait-TunnelHealth {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [int] $TimeoutSeconds)
    Wait-LauncherCondition -TimeoutSeconds $TimeoutSeconds -Condition { Test-TunnelHealth }
}

function Wait-TunnelReady {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [int] $TimeoutSeconds)
    Wait-LauncherCondition -TimeoutSeconds $TimeoutSeconds -Condition { Test-TunnelReady }
}

function Get-LauncherUserProfileFromPaths {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [pscustomobject] $Paths)

    if ($Paths.PSObject.Properties.Name -contains 'LocalRoot' -and $Paths.LocalRoot) {
        return (Split-Path -Parent ([string] $Paths.LocalRoot))
    }
    $env:USERPROFILE
}

function Start-LauncherServerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    $userProfile = Get-LauncherUserProfileFromPaths -Paths $Paths
    $map = Get-ByteMcpServerEnvironment -UserProfile $userProfile
    $prior = @{}

    try {
        foreach ($name in $map.Keys) {
            $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $map[$name], 'Process')
        }

        Start-Process -FilePath $Paths.PythonPath `
            -ArgumentList '-m', 'byte_mcp' `
            -WorkingDirectory $Paths.RepoRoot `
            -PassThru `
            -RedirectStandardOutput $Paths.ServerStdOut `
            -RedirectStandardError $Paths.ServerStdErr
    }
    finally {
        foreach ($name in $map.Keys) {
            [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
        }
    }
}

function Start-LauncherTunnelProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    $secure = Unprotect-ByteMcpCredential -Path $Paths.CredentialFile
    $plain = $null
    $priorKey = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process')

    try {
        $plain = [System.Net.NetworkCredential]::new('', $secure).Password
        [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $plain, 'Process')
        Start-Process -FilePath (Get-TunnelClientPath) `
            -ArgumentList 'run', '--profile', $Paths.TunnelProfile `
            -WorkingDirectory $Paths.RepoRoot `
            -PassThru `
            -RedirectStandardOutput $Paths.TunnelStdOut `
            -RedirectStandardError $Paths.TunnelStdErr
    }
    finally {
        [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $priorKey, 'Process')
        $plain = $null
        $secure = $null
    }
}

function Start-LauncherForegroundServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    $userProfile = Get-LauncherUserProfileFromPaths -Paths $Paths
    $map = Get-ByteMcpServerEnvironment -UserProfile $userProfile
    $prior = @{}

    try {
        foreach ($name in $map.Keys) {
            $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $map[$name], 'Process')
        }

        Start-Process -FilePath $Paths.PythonPath `
            -ArgumentList '-m', 'byte_mcp' `
            -WorkingDirectory $Paths.RepoRoot `
            -NoNewWindow `
            -PassThru
    }
    finally {
        foreach ($name in $map.Keys) {
            [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
        }
    }
}

function Start-LauncherForegroundTunnel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    $secure = Unprotect-ByteMcpCredential -Path $Paths.CredentialFile
    $plain = $null
    $priorKey = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process')

    try {
        $plain = [System.Net.NetworkCredential]::new('', $secure).Password
        [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $plain, 'Process')
        Start-Process -FilePath (Get-TunnelClientPath) `
            -ArgumentList 'run', '--profile', $Paths.TunnelProfile `
            -WorkingDirectory $Paths.RepoRoot `
            -NoNewWindow `
            -PassThru
    }
    finally {
        [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $priorKey, 'Process')
        $plain = $null
        $secure = $null
    }
}

function Stop-LauncherCreatedProcess {
    [CmdletBinding()]
    param(
        [Parameter()] $Process
    )

    if ($null -eq $Process) {
        return
    }

    Stop-Process -Id ([int] $Process.Id) -ErrorAction SilentlyContinue
    Wait-Process -Id ([int] $Process.Id) -Timeout 10 -ErrorAction SilentlyContinue
}

function Get-LauncherPortConflicts {
    [CmdletBinding()]
    param()

    @(Get-NetTCPConnection -LocalPort 8000, 8080 -State Listen -ErrorAction SilentlyContinue)
}

function Start-ByteMcpBackgroundStack {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [Parameter(Mandatory)] [int] $StartupTimeoutSeconds
    )

    Assert-ByteMcpLauncherPrerequisites -Paths $Paths
    $classification = Get-LauncherStateClassification -StatePath $Paths.StateFile

    if ($classification -eq 'active') {
        $state = Read-LauncherState -Path $Paths.StateFile
        $status = Get-ByteMcpStatus -State $state
        if ($status.Overall -eq 'READY') {
            return $status
        }
        throw 'Existing Byte-MCP launcher stack is active but DEGRADED; refusing duplicate startup.'
    }

    if ($classification -eq 'malformed') {
        throw 'Launcher state is malformed; refusing startup until it is inspected.'
    }

    if ($classification -eq 'stale' -and (Test-Path -LiteralPath $Paths.StateFile -PathType Leaf)) {
        Remove-Item -LiteralPath $Paths.StateFile -Force
    }

    $conflicts = Get-LauncherPortConflicts
    if ($conflicts.Count -gt 0) {
        $ports = ($conflicts | ForEach-Object { $_.LocalPort } | Sort-Object -Unique) -join ', '
        throw "Unmanaged launcher port conflict detected on port(s): $ports."
    }

    foreach ($logPath in @($Paths.ServerStdOut, $Paths.ServerStdErr, $Paths.TunnelStdOut, $Paths.TunnelStdErr)) {
        Rotate-LauncherLog -Path $logPath
    }

    $server = $null
    $tunnel = $null

    try {
        $server = Start-LauncherServerProcess -Paths $Paths
        if (-not (Wait-ByteMcpEndpoint -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Byte-MCP server did not become reachable before the startup timeout.'
        }

        $tunnel = Start-LauncherTunnelProcess -Paths $Paths
        if (-not (Wait-TunnelHealth -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Secure MCP tunnel health check failed before the startup timeout.'
        }
        if (-not (Wait-TunnelReady -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Secure MCP tunnel readiness check failed before the startup timeout.'
        }

        $state = New-LauncherState -RepoPath $Paths.RepoRoot -Mode 'background' `
            -ServerPid ([int] $server.Id) -ServerExecutable ([string] $server.Path) -ServerStartedAtUtc ($server.StartTime.ToUniversalTime().ToString('o')) `
            -TunnelPid ([int] $tunnel.Id) -TunnelExecutable ([string] $tunnel.Path) -TunnelStartedAtUtc ($tunnel.StartTime.ToUniversalTime().ToString('o'))
        Write-LauncherState -State $state -Path $Paths.StateFile

        [PSCustomObject]@{
            Overall = 'READY'
            State = $state
        }
    }
    catch {
        if ($null -ne $tunnel) {
            Stop-LauncherCreatedProcess -Process $tunnel
        }
        if ($null -ne $server) {
            Stop-LauncherCreatedProcess -Process $server
        }
        if (Test-Path -LiteralPath $Paths.StateFile -PathType Leaf) {
            Remove-Item -LiteralPath $Paths.StateFile -Force
        }
        throw
    }
}

function Start-ByteMcpForegroundStack {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [Parameter(Mandatory)] [int] $StartupTimeoutSeconds
    )

    Assert-ByteMcpLauncherPrerequisites -Paths $Paths
    $server = $null
    $tunnel = $null

    try {
        $server = Start-LauncherForegroundServer -Paths $Paths
        if (-not (Wait-ByteMcpEndpoint -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Byte-MCP server did not become reachable before the startup timeout.'
        }

        $tunnel = Start-LauncherForegroundTunnel -Paths $Paths
        if (-not (Wait-TunnelHealth -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Secure MCP tunnel health check failed before the startup timeout.'
        }
        if (-not (Wait-TunnelReady -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Secure MCP tunnel readiness check failed before the startup timeout.'
        }

        Write-Host 'BYTE-MCP FOREGROUND READY'
        Wait-Process -Id ([int] $tunnel.Id)
    }
    finally {
        if ($null -ne $tunnel) {
            Stop-LauncherCreatedProcess -Process $tunnel
        }
        if ($null -ne $server) {
            Stop-LauncherCreatedProcess -Process $server
        }
    }
}

function Confirm-LauncherListenersStopped {
    [CmdletBinding()]
    param(
        [int] $TimeoutSeconds = 10
    )

    Wait-LauncherCondition -TimeoutSeconds $TimeoutSeconds -Condition {
        @(Get-NetTCPConnection -LocalPort 8000, 8080 -State Listen -ErrorAction SilentlyContinue).Count -eq 0
    }
}

function Stop-ByteMcpManagedStack {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $StatePath
    )

    $classification = Get-LauncherStateClassification -StatePath $StatePath
    if ($classification -eq 'absent') {
        return [PSCustomObject]@{ Overall = 'STOPPED' }
    }
    if ($classification -eq 'malformed') {
        throw 'Launcher state is malformed; refusing unverified shutdown.'
    }
    if ($classification -eq 'stale') {
        throw 'Launcher state is stale; refusing unverified shutdown.'
    }

    $state = Read-LauncherState -Path $StatePath
    foreach ($role in @('tunnel', 'server')) {
        $record = $state.$role
        try {
            $process = Get-Process -Id ([int] $record.pid) -ErrorAction Stop
        }
        catch {
            throw "Refusing to stop unverified $role process."
        }

        if (-not (Test-LauncherProcessIdentity -Record $record -Process $process)) {
            throw "Refusing to stop unverified $role process."
        }

        Stop-Process -Id ([int] $process.Id) -ErrorAction Stop
        Wait-Process -Id ([int] $process.Id) -Timeout 10 -ErrorAction SilentlyContinue
    }

    if (-not (Confirm-LauncherListenersStopped)) {
        throw 'Launcher-owned listeners did not shut down cleanly.'
    }

    Remove-Item -LiteralPath $StatePath -Force
    [PSCustomObject]@{ Overall = 'STOPPED' }
}
