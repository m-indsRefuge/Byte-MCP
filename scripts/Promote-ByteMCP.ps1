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
    [switch] $Apply,
    [string] $StateRoot = (Join-Path $env:USERPROFILE '.byte-mcp'),
    [ValidateRange(1024,65535)][int] $McpPort = 8000,
    [ValidateRange(1024,65535)][int] $TunnelPort = 8080,
    [ValidateSet('ScheduledTask','LocalProcess')][string] $SupervisorKind = 'ScheduledTask',
    [string] $SupervisorName = $SupervisorTaskName,
    [ValidateSet('Production','Disposable')][string] $Mode = 'Production',
    [string] $BaselineFailureFile,
    [switch] $InjectPostStartFailure
)

. (Join-Path $PSScriptRoot 'Deployment.Common.ps1')
Invoke-ByteMcpPromotion @PSBoundParameters
