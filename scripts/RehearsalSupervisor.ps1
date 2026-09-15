#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $RuntimeRepo,
    [Parameter(Mandatory)][string] $StateRoot,
    [Parameter(Mandatory)][string] $PythonPath,
    [Parameter(Mandatory)][int] $McpPort,
    [Parameter(Mandatory)][int] $TunnelPort
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($StateRoot)
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$rootsFile = Join-Path $root 'roots.web.json'
$auditFile = Join-Path $root 'audit.web.jsonl'
@{ roots = @{ rehearsal = $root } } | ConvertTo-Json -Compress | Set-Content -LiteralPath $rootsFile -Encoding utf8
if (-not (Test-Path -LiteralPath $auditFile)) { New-Item -ItemType File -Path $auditFile | Out-Null }

$serverEnv = @{
    BYTE_MCP_ROOTS_FILE = $rootsFile
    BYTE_MCP_AUDIT_FILE = $auditFile
    BYTE_MCP_HOST = '127.0.0.1'
    BYTE_MCP_PORT = [string]$McpPort
    BYTE_MCP_TRANSPORT = 'streamable-http'
    BYTE_MCP_MAX_FILE_BYTES = '1000000'
    BYTE_MCP_MAX_RESPONSE_CHARS = '10000'
    BYTE_MCP_MAX_SEARCH_FILES = '20000'
    BYTE_MCP_CONTENT_SEARCH_MAX_BYTES = '250000'
}
$server = Start-Process -FilePath $PythonPath -WorkingDirectory $RuntimeRepo `
    -ArgumentList @('-B', '-m', 'byte_mcp.server') -Environment $serverEnv `
    -RedirectStandardOutput (Join-Path $logs 'server.out.log') `
    -RedirectStandardError (Join-Path $logs 'server.err.log') -PassThru
$tunnelScript = Join-Path $PSScriptRoot 'RehearsalTunnel.ps1'
$pwsh = @((Get-Command pwsh -CommandType Application).Source)[0]
$tunnel = Start-Process -FilePath $pwsh `
    -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$tunnelScript,'-Port',[string]$TunnelPort) `
    -RedirectStandardOutput (Join-Path $logs 'tunnel.out.log') `
    -RedirectStandardError (Join-Path $logs 'tunnel.err.log') -PassThru

$stateDir = Join-Path $root 'runtime'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$launcherState = [ordered]@{
    schema_version = 1; started_at_utc = [DateTime]::UtcNow.ToString('o'); mode = 'background'; repo_path = $RuntimeRepo
    root_profile = 'rehearsal'; tunnel_profile = 'rehearsal'
    server = @{ pid = $server.Id; executable_path = $PythonPath; started_at_utc = $server.StartTime.ToUniversalTime().ToString('o') }
    tunnel = @{ pid = $tunnel.Id; executable_path = $pwsh; started_at_utc = $tunnel.StartTime.ToUniversalTime().ToString('o') }
}
$statePath = Join-Path $stateDir 'launcher-state.json'
$launcherState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding utf8
$supervisorState = [ordered]@{ pid = $PID; state_path = $statePath; started_at_utc = [DateTime]::UtcNow.ToString('o') }
$supervisorState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'supervisor.json') -Encoding utf8

try {
    while ($true) {
        if ($server.HasExited -or $tunnel.HasExited) { exit 2 }
        Start-Sleep -Seconds 1
    }
}
finally {
    # The transaction owns child shutdown; this process only supervises their lifetime.
}
