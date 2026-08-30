[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $IsWindows) {
    throw 'Byte-MCP launcher tests require Windows.'
}

$pester = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version -ge [version]'5.0.0' } |
    Sort-Object Version -Descending |
    Select-Object -First 1

if ($null -eq $pester) {
    throw 'Pester 5 or newer is required.'
}

Import-Module $pester.Path -Force

$repoRoot = Split-Path -Parent $PSScriptRoot
$result = Invoke-Pester `
    -Path (Join-Path $repoRoot 'tests\launcher') `
    -PassThru `
    -Output Detailed

if ($result.FailedCount -gt 0) {
    throw "Launcher Pester suite failed: $($result.FailedCount) failed."
}

Write-Host 'PASS: Byte-MCP launcher validation complete'
