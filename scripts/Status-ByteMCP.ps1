[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE
$classification = Get-LauncherStateClassification -StatePath $paths.StateFile

switch ($classification) {
    'absent' {
        [PSCustomObject]@{
            Overall = 'STOPPED'
            Classification = 'absent'
        }
    }
    'malformed' {
        [PSCustomObject]@{
            Overall = 'DEGRADED'
            Classification = 'malformed'
        }
    }
    'stale' {
        [PSCustomObject]@{
            Overall = 'DEGRADED'
            Classification = 'stale'
        }
    }
    'active' {
        $state = Read-LauncherState -Path $paths.StateFile
        $status = Get-ByteMcpStatus -State $state
        $status | Add-Member -NotePropertyName Classification -NotePropertyValue 'active' -PassThru
    }
    default {
        throw "Unknown launcher state classification: $classification"
    }
}
