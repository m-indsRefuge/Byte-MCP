[CmdletBinding()]
param(
    [switch] $Replace
)

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
$Exists = Test-Path -LiteralPath $CredentialPath -PathType Leaf

if ($Exists -and -not $Replace) {
    throw "NVIDIA_CREDENTIAL_ALREADY_EXISTS_USE_REPLACE"
}
if (-not $Exists -and $Replace) {
    throw "NVIDIA_CREDENTIAL_REPLACE_TARGET_ABSENT"
}

Write-Host "Enter the NVIDIA API key at the secure prompt."
Write-Host "The value will not be printed or persisted in User/Machine environment variables."

$SecureCredential = Read-Host "NVIDIA API key" -AsSecureString

try {
    Protect-NvidiaCredential `
        -Credential $SecureCredential `
        -Path $CredentialPath

    $State = Test-NvidiaCredentialStore -Path $CredentialPath
    if ($State.State -ne "AVAILABLE") {
        throw "NVIDIA_CREDENTIAL_POST_WRITE_VALIDATION_FAILED"
    }

    Assert-NvidiaPersistentEnvironmentAbsent
}
finally {
    $SecureCredential = $null
}

Write-Host ""
Write-Host "NVIDIA_CREDENTIAL_SETUP=PASS"
Write-Host "DPAPI_PROTECTED_CREDENTIAL=PASS"
Write-Host "DPAPI_SCOPE=CURRENT_USER"
Write-Host "PLAINTEXT_SECRET_FILE=NONE"
Write-Host "NVIDIA_API_KEY_USER=ABSENT"
Write-Host "NVIDIA_API_KEY_MACHINE=ABSENT"
Write-Host "PROVIDER_CALLS=0"
Write-Host "DAEMON_RESTART_REQUIRED=YES"

if ($Replace) {
    Write-Host "CREDENTIAL_ROTATED=PASS"
}
else {
    Write-Host "CREDENTIAL_ENROLLED=PASS"
}
