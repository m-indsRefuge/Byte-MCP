[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $PythonPath,
    [Parameter(Mandatory)][string] $ProductionRepo,
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $StateRoot,
    [string] $BaselineFailureFile,
    [string] $BaselineManifestFile,
    [string] $PredecessorSHA,
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
$manifestPath = if ($BaselineManifestFile) { $BaselineManifestFile } elseif ($BaselineFailureFile) { $BaselineFailureFile } else { $null }
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
    $failed = @($pytestOutput | Where-Object { $_ -match '^FAILED\s+(.+?)(?:\s+-\s+(.*))?$' } | ForEach-Object {
        [pscustomobject]@{ node_id=$Matches[1].Trim(); signature=(($Matches[2] ?? '') -replace '\s+',' ').Trim() }
    })
    $failedNodes = @($failed.node_id | Sort-Object -Unique)
    $collect = @(& $Python '-m' 'pytest' '--collect-only' '-q' 2>$null | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match '::' -and $_ -notmatch '^=+' } | Sort-Object -Unique)
    $summary = ($pytestOutput | Where-Object { $_ -match '\d+\s+passed|\d+\s+failed' } | Select-Object -Last 1)
    $passedCount = if ($summary -match '(\d+)\s+passed') { [int]$Matches[1] } else { 0 }
    $failedCount = if ($summary -match '(\d+)\s+failed') { [int]$Matches[1] } else { 0 }
    $manifest = [ordered]@{ predecessor_sha=$PredecessorSHA; collected_nodes=@($collect); failing_nodes=@($failed); passed_count=$passedCount; failed_count=$failedCount; collected_count=@($collect).Count }
    if ($manifestPath -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        $baseline = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($PredecessorSHA -and $baseline.predecessor_sha -and $baseline.predecessor_sha -cne $PredecessorSHA) { throw 'Predecessor SHA differs from accepted pytest manifest lineage.' }
        if ([int]$baseline.collected_count -ne @($baseline.collected_nodes).Count -or
            [int]$baseline.passed_count + [int]$baseline.failed_count -gt [int]$baseline.collected_count) { throw 'Baseline pytest manifest counts are inconsistent.' }
        $missing = @($baseline.collected_nodes | Where-Object { $collect -notcontains $_ })
        if ($missing.Count) { throw "Candidate pytest collection lost predecessor tests: $($missing -join ', ')" }
        $baseFails = @($baseline.failing_nodes | ForEach-Object { $_.node_id })
        $candOnly = @($failedNodes | Where-Object { $baseFails -notcontains $_ })
        if ($candOnly.Count -or (@($baseFails | Where-Object { $failedNodes -notcontains $_ }).Count)) { throw 'Candidate pytest failure set differs from predecessor manifest.' }
        foreach($b in @($baseline.failing_nodes)) { $c=$failed | Where-Object node_id -eq $b.node_id; if ($null -eq $c -or $c.signature -cne $b.signature) { throw "Inherited pytest failure signature drift: $($b.node_id)" } }
        if ($passedCount + $failedCount -gt $collect.Count -or $failedCount -ne $failed.Count) { throw 'Candidate pytest manifest counts are inconsistent.' }
        Write-Host "PASS: structured pytest manifest matches predecessor ($($failedNodes.Count) shared failures)."
    } elseif ($manifestPath) {
        $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
        Write-Host "PASS: predecessor pytest manifest recorded."
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
