[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run the scaffold or recreate .venv."
}

Push-Location $RepoRoot
try {
    Write-Host "=== DEPENDENCY CHECK ==="
    & $Python -m pip check

    Write-Host "`n=== COMPILE ==="
    & $Python -m compileall -q src tests scripts\mcp_smoke_test.py scripts\wolfram_qualification.py

    Write-Host "`n=== RUFF ==="
    & $Python -m ruff check .

    Write-Host "`n=== TESTS ==="
    & $Python -m pytest

    Write-Host "`n=== LAUNCHER TESTS ==="
    if ($IsWindows) {
        & (Join-Path $PSScriptRoot 'Check-Launcher.ps1')
    }
    else {
        Write-Host 'SKIP: Windows-only launcher tests'
    }

    Write-Host "`nPASS: Byte-MCP repository validation complete"
}
finally {
    Pop-Location
}
