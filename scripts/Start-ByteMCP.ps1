[CmdletBinding()]
param(
    [switch] $Foreground,
    [ValidateRange(1, 300)] [int] $StartupTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')
. (Join-Path $PSScriptRoot 'Launcher.Ownership.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE

if ($Foreground) {
    Start-ByteMcpForegroundStack -Paths $paths -StartupTimeoutSeconds $StartupTimeoutSeconds
}
else {
    Start-ByteMcpBackgroundStack -Paths $paths -StartupTimeoutSeconds $StartupTimeoutSeconds
}
