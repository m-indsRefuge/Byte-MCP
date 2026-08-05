#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ExpectedMatchId,
    [string]$MoveUci,
    [Nullable[int]]$ExpectedStateVersion,
    [string]$ExpectedPositionHash,
    [string]$IdempotencyKey
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SmokeTest = Join-Path $PSScriptRoot "chess_mcp_smoke_test.py"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run .\scripts\Check.ps1 after creating .venv."
}

$Arguments = @($SmokeTest)
if (-not [string]::IsNullOrWhiteSpace($ExpectedMatchId)) {
    $Arguments += @("--expected-match-id", $ExpectedMatchId)
}

$SubmissionFields = @(
    -not [string]::IsNullOrWhiteSpace($MoveUci),
    $null -ne $ExpectedStateVersion,
    -not [string]::IsNullOrWhiteSpace($ExpectedPositionHash),
    -not [string]::IsNullOrWhiteSpace($IdempotencyKey)
)

if ($SubmissionFields -contains $true) {
    if ($SubmissionFields -contains $false) {
        throw "MoveUci, ExpectedStateVersion, ExpectedPositionHash, and IdempotencyKey must be supplied together."
    }
    $Arguments += @(
        "--move-uci", $MoveUci,
        "--expected-state-version", $ExpectedStateVersion.Value.ToString(),
        "--expected-position-hash", $ExpectedPositionHash,
        "--idempotency-key", $IdempotencyKey
    )
}

Push-Location $RepoRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Byte-MCP Chess smoke test failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
