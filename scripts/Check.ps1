[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run the scaffold or recreate .venv."
}

Push-Location $RepoRoot
try {
    & $Python -m compileall -q src tests
    & $Python -m ruff check .
    & $Python -m pytest
}
finally {
    Pop-Location
}
