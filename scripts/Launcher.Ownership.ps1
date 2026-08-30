Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-LauncherProcessDescendsFrom {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [int] $ProcessId,
        [Parameter(Mandatory)] [int] $AncestorProcessId
    )

    if ($ProcessId -eq $AncestorProcessId) {
        return $true
    }

    $current = $ProcessId
    $visited = [System.Collections.Generic.HashSet[int]]::new()

    for ($depth = 0; $depth -lt 16; $depth++) {
        if (-not $visited.Add($current)) {
            return $false
        }

        try {
            $record = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $current" -ErrorAction Stop
        }
        catch {
            return $false
        }

        if ($null -eq $record) {
            return $false
        }

        $parent = [int] $record.ParentProcessId
        if ($parent -eq $AncestorProcessId) {
            return $true
        }
        if ($parent -le 0 -or $parent -eq $current) {
            return $false
        }

        $current = $parent
    }

    $false
}

function Resolve-LauncherServerListenerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $LauncherProcess
    )

    $listeners = @(
        Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq '127.0.0.1' }
    )

    $ownerIds = @(
        $listeners |
            ForEach-Object { [int] $_.OwningProcess } |
            Sort-Object -Unique
    )

    if ($ownerIds.Count -ne 1) {
        throw "Unable to establish unique launcher ownership for the Byte-MCP listener on port 8000."
    }

    $ownerId = [int] $ownerIds[0]
    if (-not (Test-LauncherProcessDescendsFrom -ProcessId $ownerId -AncestorProcessId ([int] $LauncherProcess.Id))) {
        throw "Port 8000 listener PID $ownerId is not owned by launcher process PID $($LauncherProcess.Id)."
    }

    try {
        Get-Process -Id $ownerId -ErrorAction Stop
    }
    catch {
        throw "Unable to resolve launcher-owned Byte-MCP listener PID $ownerId."
    }
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

    $conflicts = @(Get-LauncherPortConflicts)
    if ($conflicts.Count -gt 0) {
        $ports = ($conflicts | ForEach-Object { $_.LocalPort } | Sort-Object -Unique) -join ', '
        throw "Unmanaged launcher port conflict detected on port(s): $ports."
    }

    foreach ($logPath in @($Paths.ServerStdOut, $Paths.ServerStdErr, $Paths.TunnelStdOut, $Paths.TunnelStdErr)) {
        Rotate-LauncherLog -Path $logPath
    }

    $serverLauncher = $null
    $server = $null
    $tunnel = $null

    try {
        $serverLauncher = Start-LauncherServerProcess -Paths $Paths
        if (-not (Wait-ByteMcpEndpoint -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Byte-MCP server did not become reachable before the startup timeout.'
        }

        $server = Resolve-LauncherServerListenerProcess -LauncherProcess $serverLauncher

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
        if ($null -ne $serverLauncher -and ($null -eq $server -or [int] $serverLauncher.Id -ne [int] $server.Id)) {
            Stop-LauncherCreatedProcess -Process $serverLauncher
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
    $serverLauncher = $null
    $server = $null
    $tunnel = $null

    try {
        $serverLauncher = Start-LauncherForegroundServer -Paths $Paths
        if (-not (Wait-ByteMcpEndpoint -TimeoutSeconds $StartupTimeoutSeconds)) {
            throw 'Byte-MCP server did not become reachable before the startup timeout.'
        }

        $server = Resolve-LauncherServerListenerProcess -LauncherProcess $serverLauncher

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
        if ($null -ne $serverLauncher -and ($null -eq $server -or [int] $serverLauncher.Id -ne [int] $server.Id)) {
            Stop-LauncherCreatedProcess -Process $serverLauncher
        }
    }
}
