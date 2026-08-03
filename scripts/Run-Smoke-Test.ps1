[CmdletBinding()]
param(
    [string]$Url = "http://127.0.0.1:8000/mcp",
    [string]$Root = "downloads",
    [string]$Query = "",
    [string]$ExpectName = "",
    [ValidateRange(1, 50)]
    [int]$MaxResults = 20,
    [ValidateRange(1000, 60000)]
    [int]$MaxChars = 5000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SmokeTest = Join-Path $PSScriptRoot "mcp_smoke_test.py"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run the scaffold or recreate .venv."
}

$Arguments = @(
    $SmokeTest,
    "--url", $Url,
    "--root", $Root,
    "--max-results", $MaxResults,
    "--max-chars", $MaxChars
)

if ($Query) {
    $Arguments += @("--query", $Query)
}

if ($ExpectName) {
    $Arguments += @("--expect-name", $ExpectName)
}

Push-Location $RepoRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Byte-MCP protocol smoke test failed."
    }
}
finally {
    Pop-Location
}
