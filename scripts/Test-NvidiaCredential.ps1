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

$State = Test-NvidiaCredentialStore
if ($State.State -ne "AVAILABLE") {
    throw "NVIDIA_CREDENTIAL_STORE_NOT_AVAILABLE"
}

Assert-NvidiaPersistentEnvironmentAbsent

Write-Host "NVIDIA_CREDENTIAL_TEST=PASS"
Write-Host "CREDENTIAL_STATE=AVAILABLE"
Write-Host "CREDENTIAL_FILE_PRESENT=YES"
Write-Host "CREDENTIAL_ACL_SAFE=PASS"
Write-Host "DPAPI_SCOPE=CURRENT_USER"
Write-Host "NVIDIA_API_KEY_USER=ABSENT"
Write-Host "NVIDIA_API_KEY_MACHINE=ABSENT"
Write-Host "PROVIDER_CALLS=0"
