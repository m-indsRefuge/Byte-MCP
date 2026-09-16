[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "Launcher.Nvidia.ps1")


function Assert-NvidiaPersistentEnvironmentAbsent {
    [CmdletBinding()]
    param()

    $UserValue = [Environment]::GetEnvironmentVariable(
        "NVIDIA_API_KEY",
        "User"
    )
    $MachineValue = [Environment]::GetEnvironmentVariable(
        "NVIDIA_API_KEY",
        "Machine"
    )

    if (-not [string]::IsNullOrEmpty($UserValue)) {
        throw "NVIDIA_CREDENTIAL_USER_ENV_PRESENT"
    }
    if (-not [string]::IsNullOrEmpty($MachineValue)) {
        throw "NVIDIA_CREDENTIAL_MACHINE_ENV_PRESENT"
    }
}


Assert-NvidiaPersistentEnvironmentAbsent

$CredentialPath = Get-NvidiaCredentialPath

if (Test-Path -LiteralPath $CredentialPath -PathType Leaf) {
    Remove-Item -LiteralPath $CredentialPath -Force
}

if (Test-Path -LiteralPath $CredentialPath) {
    throw "NVIDIA_CREDENTIAL_REMOVAL_FAILED"
}

Assert-NvidiaPersistentEnvironmentAbsent

Write-Host "NVIDIA_CREDENTIAL_REMOVAL=PASS"
Write-Host "CREDENTIAL_FILE_PRESENT=NO"
Write-Host "NVIDIA_API_KEY_USER=ABSENT"
Write-Host "NVIDIA_API_KEY_MACHINE=ABSENT"
Write-Host "PROVIDER_CALLS=0"
Write-Host "DAEMON_RESTART_REQUIRED=YES"
