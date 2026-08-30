Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Add-WolframLauncherPaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'
    if ($Paths.PSObject.Properties.Name -notcontains 'WolframCredentialFile') {
        $Paths | Add-Member -NotePropertyName WolframCredentialFile `
            -NotePropertyValue (Join-Path $localRoot 'credentials\wolfram-appid.dpapi')
    }
    if ($Paths.PSObject.Properties.Name -notcontains 'WolframUsageFile') {
        $Paths | Add-Member -NotePropertyName WolframUsageFile `
            -NotePropertyValue (Join-Path $localRoot 'wolfram\usage.json')
    }
    $Paths
}

function Get-ByteMcpWolframServerEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'
    @{
        BYTE_MCP_WOLFRAM_USAGE_FILE = Join-Path $localRoot 'wolfram\usage.json'
    }
}

function Get-ByteMcpCombinedServerEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $map = Get-ByteMcpServerEnvironment -UserProfile $UserProfile
    $map.BYTE_MCP_MAX_RESPONSE_CHARS = '60000'

    $wolframMap = Get-ByteMcpWolframServerEnvironment -UserProfile $UserProfile
    foreach ($name in $wolframMap.Keys) {
        $map[$name] = $wolframMap[$name]
    }

    $map
}

function Invoke-StartByteMcpServerWithWolfram {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [switch] $Foreground
    )

    $userProfile = Get-LauncherUserProfileFromPaths -Paths $Paths
    $map = Get-ByteMcpCombinedServerEnvironment -UserProfile $userProfile

    $names = @($map.Keys) + @('WOLFRAM_APP_ID')
    $prior = Get-LauncherProcessEnvironmentSnapshot -Names $names
    $secure = $null
    $plain = $null

    try {
        foreach ($name in $map.Keys) {
            [Environment]::SetEnvironmentVariable($name, $map[$name], 'Process')
        }

        if (Test-Path -LiteralPath $Paths.WolframCredentialFile -PathType Leaf) {
            $secure = Unprotect-ByteMcpCredential -Path $Paths.WolframCredentialFile
            $plain = [System.Net.NetworkCredential]::new('', $secure).Password
            [Environment]::SetEnvironmentVariable('WOLFRAM_APP_ID', $plain, 'Process')
        }
        else {
            Remove-Item -LiteralPath 'Env:\WOLFRAM_APP_ID' -ErrorAction SilentlyContinue
        }

        $arguments = @{
            FilePath = $Paths.PythonPath
            ArgumentList = @('-m', 'byte_mcp')
            WorkingDirectory = $Paths.RepoRoot
            PassThru = $true
        }
        if ($Foreground) {
            $arguments.NoNewWindow = $true
        }
        else {
            $arguments.RedirectStandardOutput = $Paths.ServerStdOut
            $arguments.RedirectStandardError = $Paths.ServerStdErr
        }
        Start-Process @arguments
    }
    finally {
        Restore-LauncherProcessEnvironment -Snapshot $prior
        $plain = $null
        $secure = $null
    }
}

function Start-LauncherServerProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    Invoke-StartByteMcpServerWithWolfram -Paths $Paths
}

function Start-LauncherForegroundServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths
    )

    Invoke-StartByteMcpServerWithWolfram -Paths $Paths -Foreground
}
