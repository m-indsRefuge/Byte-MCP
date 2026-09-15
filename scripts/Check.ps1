[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $PythonPath,
    [Parameter(Mandatory)][string] $ProductionRepo,
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

. (Join-Path $PSScriptRoot 'Launcher.Platform.ps1')
. (Join-Path $PSScriptRoot 'Deployment.Common.ps1')

$RepoRoot = Resolve-DeploymentPath $RepoRoot
$Python = Resolve-DeploymentPath $PythonPath
Assert-DeploymentIsolation $ProductionRepo $RepoRoot $Python
# A caller cannot label a different checkout as production to qualify the managed live tree.
$launcherPaths = Get-ByteMcpLauncherPaths -RepoRoot $ProductionRepo -UserProfile $env:USERPROFILE
if (Test-Path -LiteralPath $launcherPaths.StateFile) {
    $managed = Read-LauncherState $launcherPaths.StateFile
    Assert-DeploymentIsolation $managed.repo_path $RepoRoot $Python
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Isolated qualification environment not found. Create it outside production.'
}

Push-Location $RepoRoot
try {
    $prefix = (Invoke-DeploymentNative $Python @('-B', '-c', 'import sys; print(sys.prefix)')).Trim()
    if ((Resolve-DeploymentPath $prefix) -ine (Resolve-DeploymentPath (Join-Path $RepoRoot '.venv'))) {
        throw 'Qualification interpreter prefix does not belong to the candidate environment.'
    }
    # Verify import provenance before running candidate tests or development tooling.
    $null = Get-DeploymentTools $RepoRoot $Python
    Write-Host "=== DEPENDENCY CHECK ==="
    Invoke-DeploymentNative $Python @('-m', 'pip', 'check')

    Write-Host "`n=== COMPILE ==="
    Invoke-DeploymentNative $Python @('-m', 'compileall', '-q', 'src', 'tests', 'scripts')

    Write-Host "`n=== RUFF ==="
    Invoke-DeploymentNative $Python @('-m', 'ruff', 'check', '.')

    Write-Host "`n=== TESTS ==="
    Invoke-DeploymentNative $Python @('-m', 'pytest')

    Write-Host "`n=== LAUNCHER TESTS ==="
    if ($IsWindows) {
        & (Join-Path $PSScriptRoot 'Check-Launcher.ps1') -RepoRoot $RepoRoot
    }

    else {
        Write-Host 'SKIP: Windows-only launcher tests'
    }

    Write-Host "`n=== MCP IMPORT AND EXACT TOOL DISCOVERY (NO TOOL CALLS) ==="
    Get-DeploymentTools $RepoRoot $Python | Out-Host

    Write-Host "`nPASS: Byte-MCP repository validation complete"
}
finally {
    Pop-Location
}
