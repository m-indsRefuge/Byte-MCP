#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $RuntimeRepo,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $ExpectedPredecessor,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $TargetCommit,
    [Parameter(Mandatory)][string] $CandidateRepo,
    [string[]] $ExpectedAdded = @(),
    [string[]] $ExpectedRemoved = @(),
    [string] $SupervisorTaskName = 'Byte-MCP Daemon',
    [switch] $Apply
)

. (Join-Path $PSScriptRoot 'Deployment.Common.ps1')
Invoke-ByteMcpPromotion @PSBoundParameters
