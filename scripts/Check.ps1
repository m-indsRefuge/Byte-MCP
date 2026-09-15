[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $PythonPath,
    [Parameter(Mandatory)][string] $ProductionRepo,
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $StateRoot,
    [string] $BaselineFailureFile,
    [ValidateRange(1024,65535)][int] $McpPort = 8000,
    [ValidateRange(1024,65535)][int] $TunnelPort = 8080,
    [string] $SupervisorName = 'Byte-MCP Daemon'
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
$context = if ($StateRoot) {
    New-DeploymentContext -RuntimeRepo $ProductionRepo -StateRoot $StateRoot -McpPort $McpPort -TunnelPort $TunnelPort -SupervisorKind LocalProcess -SupervisorName $SupervisorName -Mode Disposable -BaselineFailureFile $BaselineFailureFile
} else { $null }
$stateFile = if ($context) { $context.LauncherStatePath } else { (Get-ByteMcpLauncherPaths -RepoRoot $ProductionRepo -UserProfile $env:USERPROFILE).StateFile }
if (Test-Path -LiteralPath $stateFile) {
    $managed = Read-LauncherState $stateFile
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
    $oldNativePreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $pytestOutput = @(& $Python '-m' 'pytest' '--tb=no' '-q' 2>&1 | ForEach-Object { $_.ToString() })
        $pytestExit = $LASTEXITCODE
    }
    finally { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
    $pytestOutput | ForEach-Object { Write-Host $_ }
    $failedNodes = @($pytestOutput | Where-Object { $_ -match '^FAILED\s+(.+?)(?:\s+-\s+.*)?$' } | ForEach-Object { $Matches[1].Trim() } | Sort-Object -Unique)
    $summary = ($pytestOutput | Where-Object { $_ -match '\d+\s+passed|\d+\s+failed' } | Select-Object -Last 1)
    $passedCount = if ($summary -match '(\d+)\s+passed') { [int]$Matches[1] } else { 0 }
    $failedCount = if ($summary -match '(\d+)\s+failed') { [int]$Matches[1] } else { 0 }
    if ($BaselineFailureFile) {
        if (-not (Test-Path -LiteralPath $BaselineFailureFile -PathType Leaf)) { throw "Baseline failure manifest not found: $BaselineFailureFile" }
        $baselineNodes = @(Get-Content -LiteralPath $BaselineFailureFile | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() } | Sort-Object -Unique)
        $baseJson = $baselineNodes | ConvertTo-Json -Compress
        $candJson = $failedNodes | ConvertTo-Json -Compress
        if ($baseJson -cne $candJson) {
            $baseOnly = @($baselineNodes | Where-Object { $failedNodes -cnotcontains $_ })
            $candOnly = @($failedNodes | Where-Object { $baselineNodes -cnotcontains $_ })
            throw "Candidate pytest failure set differs from predecessor. BASELINE_ONLY=[$($baseOnly -join ', ')] CANDIDATE_ONLY=[$($candOnly -join ', ')]"
        }
        Write-Host "PASS: pytest failure set matches predecessor baseline ($($failedNodes.Count) shared failures)."
    } elseif ($pytestExit -ne 0) {
        throw "Pytest failed with exit code $pytestExit."
    }

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
