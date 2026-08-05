#Requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run .\scripts\Check.ps1 after creating .venv."
}

if ([string]::IsNullOrWhiteSpace($env:BYTE_MCP_CHESS_MATCH_ID)) {
    throw "BYTE_MCP_CHESS_MATCH_ID must bind the chess capability to one Arena match."
}

if ([string]::IsNullOrWhiteSpace($env:BYTE_MCP_CHESS_ACTOR)) {
    $env:BYTE_MCP_CHESS_ACTOR = "byte"
}

Push-Location $RepoRoot
try {
    & $Python -m byte_mcp.chess_server
    if ($LASTEXITCODE -ne 0) {
        throw "Byte-MCP Chess exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
