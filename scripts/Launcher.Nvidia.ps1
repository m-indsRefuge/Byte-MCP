Set-StrictMode -Version Latest

$script:NvidiaCredentialFileName = "nvidia-api-key.dpapi"
$script:NvidiaCredentialProtectionScope = "CurrentUser"


function Get-NvidiaCredentialPath {
    [CmdletBinding()]
    param()

    $HomePath = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::UserProfile
    )
    if ([string]::IsNullOrWhiteSpace($HomePath)) {
        throw "NVIDIA_CREDENTIAL_USER_PROFILE_UNAVAILABLE"
    }

    return [System.IO.Path]::Combine(
        $HomePath,
        ".byte-mcp",
        "secrets",
        $script:NvidiaCredentialFileName
    )
}


function Clear-NvidiaByteArray {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [byte[]] $Bytes
    )

    if ($null -ne $Bytes) {
        [Array]::Clear($Bytes, 0, $Bytes.Length)
    }
}


function Assert-NvidiaCredentialAclSafe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string] $Path
    )

    $Acl = Get-Acl -LiteralPath $Path -ErrorAction Stop

    foreach ($Rule in $Acl.Access) {
        if ($Rule.AccessControlType -ne "Allow") {
            continue
        }

        $Identity = [string] $Rule.IdentityReference.Value
        $RightsText = [string] $Rule.FileSystemRights
        $AllowsWrite = $RightsText -match (
            "Write|Modify|FullControl|CreateFiles|AppendData|" +
            "WriteData|ChangePermissions|TakeOwnership"
        )

        if (
            $AllowsWrite -and
            $Identity -match (
                "(?i)(^|\\)(Everyone|Users|Authenticated Users)$"
            )
        ) {
            throw "NVIDIA_CREDENTIAL_ACL_UNSAFE"
        }
    }
}


function Unprotect-NvidiaCredential {
    [CmdletBinding()]
    param(
        [string] $Path = (Get-NvidiaCredentialPath)
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "NVIDIA_CREDENTIAL_STORE_ABSENT"
    }

    Assert-NvidiaCredentialAclSafe -Path $Path

    [byte[]] $CipherBytes = $null
    [byte[]] $PlainBytes = $null

    try {
        $CipherBytes = [System.IO.File]::ReadAllBytes($Path)
        if ($CipherBytes.Length -eq 0) {
            throw "NVIDIA_CREDENTIAL_STORE_EMPTY"
        }

        $PlainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $CipherBytes,
            $null,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )

        if ($null -eq $PlainBytes -or $PlainBytes.Length -eq 0) {
            throw "NVIDIA_CREDENTIAL_DECRYPTED_EMPTY"
        }

        $PlainText = [System.Text.Encoding]::UTF8.GetString($PlainBytes)
        if ([string]::IsNullOrWhiteSpace($PlainText)) {
            throw "NVIDIA_CREDENTIAL_DECRYPTED_EMPTY"
        }

        return $PlainText
    }
    finally {
        Clear-NvidiaByteArray -Bytes $PlainBytes
        Clear-NvidiaByteArray -Bytes $CipherBytes
    }
}


function Protect-NvidiaCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Security.SecureString] $Credential,

        [string] $Path = (Get-NvidiaCredentialPath)
    )

    $Directory = Split-Path -Parent $Path
    if ([string]::IsNullOrWhiteSpace($Directory)) {
        throw "NVIDIA_CREDENTIAL_DIRECTORY_INVALID"
    }

    New-Item -ItemType Directory -Force -Path $Directory | Out-Null

    $TempPath = Join-Path $Directory (
        ([System.IO.Path]::GetFileName($Path)) +
        ".tmp." +
        [guid]::NewGuid().ToString("N")
    )

    $Bstr = [IntPtr]::Zero
    $PlainText = $null
    [byte[]] $PlainBytes = $null
    [byte[]] $CipherBytes = $null
    $VerifiedPlainText = $null
    $BackupPath = $null

    try {
        $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
            $Credential
        )
        $PlainText = (
            [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
        )

        if ([string]::IsNullOrWhiteSpace($PlainText)) {
            throw "NVIDIA_CREDENTIAL_EMPTY"
        }

        $PlainBytes = [System.Text.Encoding]::UTF8.GetBytes($PlainText)

        $CipherBytes = (
            [System.Security.Cryptography.ProtectedData]::Protect(
                $PlainBytes,
                $null,
                [System.Security.Cryptography.DataProtectionScope]::CurrentUser
            )
        )

        if ($null -eq $CipherBytes -or $CipherBytes.Length -eq 0) {
            throw "NVIDIA_CREDENTIAL_PROTECT_FAILED"
        }

        [System.IO.File]::WriteAllBytes($TempPath, $CipherBytes)
        Assert-NvidiaCredentialAclSafe -Path $TempPath

        $VerifiedPlainText = Unprotect-NvidiaCredential -Path $TempPath
        if ([string]::IsNullOrWhiteSpace($VerifiedPlainText)) {
            throw "NVIDIA_CREDENTIAL_TEMP_VERIFY_FAILED"
        }
        $VerifiedPlainText = $null

        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            $BackupPath = Join-Path $Directory (
                ([System.IO.Path]::GetFileName($Path)) +
                ".backup." +
                [guid]::NewGuid().ToString("N")
            )

            [System.IO.File]::Replace(
                $TempPath,
                $Path,
                $BackupPath
            )
        }
        else {
            [System.IO.File]::Move(
                $TempPath,
                $Path
            )
        }

        Assert-NvidiaCredentialAclSafe -Path $Path

        $VerifiedPlainText = Unprotect-NvidiaCredential -Path $Path
        if ([string]::IsNullOrWhiteSpace($VerifiedPlainText)) {
            throw "NVIDIA_CREDENTIAL_FINAL_VERIFY_FAILED"
        }
        $VerifiedPlainText = $null

        if (
            $null -ne $BackupPath -and
            (Test-Path -LiteralPath $BackupPath -PathType Leaf)
        ) {
            Remove-Item -LiteralPath $BackupPath -Force
            $BackupPath = $null
        }
    }
    finally {
        if (Test-Path -LiteralPath $TempPath) {
            Remove-Item -LiteralPath $TempPath -Force -ErrorAction SilentlyContinue
        }

        $VerifiedPlainText = $null
        $PlainText = $null

        Clear-NvidiaByteArray -Bytes $PlainBytes
        Clear-NvidiaByteArray -Bytes $CipherBytes

        if ($Bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
        }
    }
}


function Test-NvidiaCredentialStore {
    [CmdletBinding()]
    param(
        [string] $Path = (Get-NvidiaCredentialPath)
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [pscustomobject]@{
            State = "ABSENT"
            Exists = $false
            AclSafe = $false
            ProtectionScope = $script:NvidiaCredentialProtectionScope
        }
    }

    $PlainText = $null

    try {
        Assert-NvidiaCredentialAclSafe -Path $Path
        $PlainText = Unprotect-NvidiaCredential -Path $Path

        if ([string]::IsNullOrWhiteSpace($PlainText)) {
            throw "NVIDIA_CREDENTIAL_DECRYPTED_EMPTY"
        }

        return [pscustomobject]@{
            State = "AVAILABLE"
            Exists = $true
            AclSafe = $true
            ProtectionScope = $script:NvidiaCredentialProtectionScope
        }
    }
    catch {
        return [pscustomobject]@{
            State = "INVALID"
            Exists = $true
            AclSafe = $false
            ProtectionScope = $script:NvidiaCredentialProtectionScope
        }
    }
    finally {
        $PlainText = $null
    }
}


function Import-NvidiaCredentialForChildProcess {
    [CmdletBinding()]
    param(
        [string] $Path = (Get-NvidiaCredentialPath)
    )

    $State = Test-NvidiaCredentialStore -Path $Path
    if ($State.State -ne "AVAILABLE") {
        return $false
    }

    $PlainText = $null

    try {
        $PlainText = Unprotect-NvidiaCredential -Path $Path
        if ([string]::IsNullOrWhiteSpace($PlainText)) {
            return $false
        }

        $env:NVIDIA_API_KEY = $PlainText
        return $true
    }
    finally {
        $PlainText = $null
    }
}


function Clear-NvidiaCredentialFromCurrentProcess {
    [CmdletBinding()]
    param()

    Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
}

function Invoke-StartByteMcpServerWithNvidia {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $Paths,

        [switch] $Foreground,

        [string] $CredentialPath = (Get-NvidiaCredentialPath)
    )

    $Injected = $false

    try {
        # The durable store is authoritative. Remove any stale process-scoped
        # value before evaluating it so an absent/invalid store cannot leak an
        # older bootstrap credential into the child.
        Clear-NvidiaCredentialFromCurrentProcess

        $Injected = Import-NvidiaCredentialForChildProcess `
            -Path $CredentialPath

        if ($Injected) {
            Write-Host "NVIDIA_CREDENTIAL_STATE=AVAILABLE"
        }
        else {
            $State = Test-NvidiaCredentialStore -Path $CredentialPath
            Write-Host "NVIDIA_CREDENTIAL_STATE=$($State.State)"
        }

        if ($Foreground) {
            Invoke-StartByteMcpServerWithWolfram `
                -Paths $Paths `
                -Foreground
        }
        else {
            Invoke-StartByteMcpServerWithWolfram `
                -Paths $Paths
        }
    }
    finally {
        # Start-Process has already inherited the process environment by the
        # time the delegated Wolfram launcher returns. Do not retain plaintext
        # NVIDIA credential material in the launcher process.
        Clear-NvidiaCredentialFromCurrentProcess
    }
}


function Start-LauncherServerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $Paths
    )

    Invoke-StartByteMcpServerWithNvidia -Paths $Paths
}


function Start-LauncherForegroundServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [pscustomobject] $Paths
    )

    Invoke-StartByteMcpServerWithNvidia `
        -Paths $Paths `
        -Foreground
}
