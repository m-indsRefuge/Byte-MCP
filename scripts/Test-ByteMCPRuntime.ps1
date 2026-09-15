#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $RuntimeRepo,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $ExpectedHead,
    [Parameter(Mandatory)][string[]] $ExpectedTools,
    [string] $SupervisorTaskName = 'Byte-MCP Daemon'
)
. (Join-Path $PSScriptRoot 'Deployment.Common.ps1')
Assert-DeploymentClean $RuntimeRepo
$snapshot = Get-DeploymentRuntime $RuntimeRepo
Assert-DeploymentRuntime $snapshot $RuntimeRepo $ExpectedHead $ExpectedTools
$null = Get-DeploymentSupervisor $RuntimeRepo $SupervisorTaskName
$snapshot
