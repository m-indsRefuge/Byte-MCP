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

$manifestPredecessorSha = $PredecessorSHA
if ($manifestPath -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    $baselineManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $baselinePredecessorSha = [string]$baselineManifest.predecessor_sha
    if ($baselinePredecessorSha -notmatch '^[0-9a-f]{40}$') {
        throw 'Baseline manifest predecessor SHA is invalid.'
    }
    if ($manifestPredecessorSha -and $manifestPredecessorSha -cne $baselinePredecessorSha) {
        throw 'Baseline manifest predecessor SHA does not match the requested predecessor.'
    }
    $manifestPredecessorSha = $baselinePredecessorSha
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
        $candidateManifest = if ($manifestPath) { "$manifestPath.candidate" } else { Join-Path $env:TEMP ("byte-pytest-" + [guid]::NewGuid().ToString() + '.json') }
        $oldPythonPath = $env:PYTHONPATH; $oldManifest = $env:BYTE_PYTEST_MANIFEST; $oldSha = $env:BYTE_PREDECESSOR_SHA
        $env:PYTHONPATH = Join-Path $PSScriptRoot ''; $env:BYTE_PYTEST_MANIFEST = $candidateManifest; $env:BYTE_PREDECESSOR_SHA = $manifestPredecessorSha
        $pytestOutput = @(& $Python '-m' 'pytest' '--tb=no' '-q' '-p' 'pytest_manifest' 2>&1 | ForEach-Object { $_.ToString() })
        $pytestExit = $LASTEXITCODE
        $env:PYTHONPATH = $oldPythonPath; $env:BYTE_PYTEST_MANIFEST = $oldManifest; $env:BYTE_PREDECESSOR_SHA = $oldSha
    }
    finally { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
    $pytestOutput | ForEach-Object { Write-Host $_ }
    if (-not (Test-Path -LiteralPath $candidateManifest -PathType Leaf)) { throw 'Structured pytest manifest was not generated.' }
    if ($manifestPredecessorSha) {
        $manifestCheck = & $Python '-c' "import json,sys; sys.path.insert(0,r'$PSScriptRoot'); from pytest_manifest import validate_manifest; validate_manifest(json.load(open(r'$candidateManifest')), r'$manifestPredecessorSha'); print('manifest-valid')"
    }
    else {
        $manifestCheck = & $Python '-c' "import json,sys; sys.path.insert(0,r'$PSScriptRoot'); from pytest_manifest import validate_manifest; validate_manifest(json.load(open(r'$candidateManifest'))); print('manifest-valid')"
    }
    if ($LASTEXITCODE -ne 0) { throw 'Candidate pytest manifest is malformed or has incorrect predecessor provenance.' }
    if ($manifestPath -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        $compare = & $Python '-c' "import json,sys; sys.path.insert(0,r'$PSScriptRoot'); from pytest_manifest import compare_manifests; compare_manifests(json.load(open(r'$manifestPath')),json.load(open(r'$candidateManifest'))); print('differential-valid')"
        if ($LASTEXITCODE -ne 0) { throw 'Structured predecessor differential qualification failed.' }
    } elseif ($manifestPath) { Copy-Item -LiteralPath $candidateManifest -Destination $manifestPath -Force }
    if ($pytestExit -ne 0 -and -not $manifestPath) { throw "Pytest failed with exit code $pytestExit." }

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
