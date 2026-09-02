[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $RuntimeRepo,

    [ValidateRange(10, 300)]
    [int] $HealthCheckSeconds = 30,

    [ValidateRange(10, 300)]
    [int] $StartupTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LocalRoot = Join-Path $env:USERPROFILE '.byte-mcp'
$DaemonRoot = Join-Path $LocalRoot 'daemon'
$LogPath = Join-Path $DaemonRoot 'supervisor.log'

$StartScript = Join-Path $RuntimeRepo 'scripts\Start-ByteMCP.ps1'
$StatusScript = Join-Path $RuntimeRepo 'scripts\Status-ByteMCP.ps1'
$StopScript = Join-Path $RuntimeRepo 'scripts\Stop-ByteMCP.ps1'

function Rotate-LogIfNeeded {
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        return
    }

    $item = Get-Item -LiteralPath $LogPath
    if ($item.Length -lt 5MB) {
        return
    }

    $previous = "$LogPath.previous"
    Remove-Item -LiteralPath $previous -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $LogPath -Destination $previous -Force
}

function Write-DaemonLog {
    param(
        [Parameter(Mandatory)][string] $Level,
        [Parameter(Mandatory)][string] $Message
    )

    New-Item -ItemType Directory -Force -Path $DaemonRoot | Out-Null
    Rotate-LogIfNeeded

    $line = '{0} [{1}] {2}' -f (
        [datetime]::Now.ToString('yyyy-MM-dd HH:mm:ss'),
        $Level.ToUpperInvariant(),
        $Message
    )

    Add-Content -LiteralPath $LogPath -Value $line -Encoding utf8
}

function Assert-Runtime {
    foreach ($path in @($StartScript, $StatusScript, $StopScript)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required Byte-MCP launcher script missing: $path"
        }
    }

    $python = Join-Path $RuntimeRepo '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Runtime Python is missing: $python"
    }
}

function Get-StatusSafe {
    try {
        $status = & $StatusScript
        if ($null -eq $status) {
            return [PSCustomObject]@{
                Overall = 'DEGRADED'
                Classification = 'no-status'
            }
        }
        return $status
    }
    catch {
        Write-DaemonLog -Level 'ERROR' -Message "Status failed: $($_.Exception.Message)"
        return [PSCustomObject]@{
            Overall = 'DEGRADED'
            Classification = 'status-error'
        }
    }
}

function Get-FailedComponentsText {
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $Status
    )

    if ($Status.PSObject.Properties.Name -notcontains 'FailedComponents') {
        return 'unavailable'
    }

    $failed = @($Status.FailedComponents)
    if ($failed.Count -eq 0) {
        return 'none'
    }

    $failed -join ','
}

function Stop-StackSafe {
    try {
        & $StopScript | Out-Null
        Write-DaemonLog -Level 'INFO' -Message 'Managed Byte-MCP stack stopped.'
    }
    catch {
        Write-DaemonLog -Level 'WARN' -Message "Stop reported: $($_.Exception.Message)"
    }
}

function Start-Stack {
    Write-DaemonLog -Level 'INFO' -Message 'Starting managed Byte-MCP server and OpenAI tunnel.'

    & $StartScript -StartupTimeoutSeconds $StartupTimeoutSeconds | Out-Null

    $status = Get-StatusSafe
    if ([string] $status.Overall -ne 'READY') {
        $failed = Get-FailedComponentsText -Status $status
        throw "Byte-MCP startup completed but status is '$($status.Overall)'; failed=$failed."
    }

    Write-DaemonLog -Level 'INFO' -Message 'Byte-MCP server and OpenAI tunnel are READY.'
}

function Repair-Stack {
    param([Parameter(Mandatory)][string] $Reason)

    Write-DaemonLog -Level 'WARN' -Message "Repairing managed stack: $Reason"
    Stop-StackSafe
    Start-Sleep -Seconds 2
    Start-Stack
}

Assert-Runtime
Write-DaemonLog -Level 'INFO' -Message "Supervisor started. RuntimeRepo=$RuntimeRepo"

$consecutiveFailures = 0

while ($true) {
    try {
        $status = Get-StatusSafe

        if ([string] $status.Overall -ne 'READY') {
            $failed = Get-FailedComponentsText -Status $status
            Repair-Stack -Reason "status=$($status.Overall); classification=$($status.Classification); failed=$failed"
        }

        $consecutiveFailures = 0
        Start-Sleep -Seconds $HealthCheckSeconds
    }
    catch {
        $consecutiveFailures++
        $delay = [math]::Min(
            300,
            [math]::Max(15, $HealthCheckSeconds * $consecutiveFailures)
        )

        Write-DaemonLog `
            -Level 'ERROR' `
            -Message "Supervisor cycle failed (#$consecutiveFailures): $($_.Exception.Message). Retry in ${delay}s."

        Start-Sleep -Seconds $delay
    }
}
