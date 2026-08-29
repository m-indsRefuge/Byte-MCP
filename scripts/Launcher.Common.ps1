Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ByteMcpLauncherPaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RepoRoot,
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'

    [PSCustomObject]@{
        RepoRoot          = $RepoRoot
        PythonPath        = Join-Path $RepoRoot '.venv\Scripts\python.exe'
        LocalRoot         = $localRoot
        RootsFile         = Join-Path $localRoot 'roots.web.json'
        AuditFile         = Join-Path $localRoot 'audit.web.jsonl'
        CredentialFile    = Join-Path $localRoot 'credentials\tunnel-runtime-key.dpapi'
        RuntimeDir        = Join-Path $localRoot 'runtime'
        StateFile         = Join-Path $localRoot 'runtime\launcher-state.json'
        LogsDir           = Join-Path $localRoot 'logs'
        ServerStdOut      = Join-Path $localRoot 'logs\byte-mcp-server.log'
        ServerStdErr      = Join-Path $localRoot 'logs\byte-mcp-server.err.log'
        TunnelStdOut      = Join-Path $localRoot 'logs\tunnel-client.log'
        TunnelStdErr      = Join-Path $localRoot 'logs\tunnel-client.err.log'
        TunnelProfile     = 'byte-mcp-local'
        TunnelProfileFile = Join-Path $env:APPDATA 'tunnel-client\byte-mcp-local.yaml'
    }
}

function Get-ByteMcpServerEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $UserProfile
    )

    $localRoot = Join-Path $UserProfile '.byte-mcp'

    @{
        BYTE_MCP_ROOTS_FILE               = Join-Path $localRoot 'roots.web.json'
        BYTE_MCP_AUDIT_FILE               = Join-Path $localRoot 'audit.web.jsonl'
        BYTE_MCP_HOST                     = '127.0.0.1'
        BYTE_MCP_PORT                     = '8000'
        BYTE_MCP_TRANSPORT                = 'streamable-http'
        BYTE_MCP_MAX_FILE_BYTES           = '1000000'
        BYTE_MCP_MAX_RESPONSE_CHARS       = '10000'
        BYTE_MCP_MAX_SEARCH_FILES         = '20000'
        BYTE_MCP_CONTENT_SEARCH_MAX_BYTES = '250000'
    }
}

function Get-TunnelClientPath {
    [CmdletBinding()]
    param()

    (Get-Command tunnel-client -CommandType Application -ErrorAction Stop).Source
}

function Assert-ByteMcpLauncherPrerequisites {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $Paths,
        [switch] $SkipCredentialCheck
    )

    if (-not $IsWindows) {
        throw 'Byte-MCP Launcher V1 requires Windows.'
    }

    if (-not (Test-Path -LiteralPath $Paths.RepoRoot -PathType Container)) {
        throw 'Byte-MCP repository path is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.PythonPath -PathType Leaf)) {
        throw 'Byte-MCP virtual environment Python is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.RootsFile -PathType Leaf)) {
        throw 'AIProjects-only roots.web.json is missing.'
    }

    if (-not (Test-Path -LiteralPath $Paths.TunnelProfileFile -PathType Leaf)) {
        throw 'Tunnel profile byte-mcp-local is missing.'
    }

    $null = Get-TunnelClientPath

    if (-not $SkipCredentialCheck -and -not (Test-Path -LiteralPath $Paths.CredentialFile -PathType Leaf)) {
        throw 'Encrypted tunnel Runtime API key is missing. Run Setup-ByteMCP.ps1.'
    }
}

function Assert-CredentialWriteAllowed {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [bool] $ReplaceCredential
    )

    if ((Test-Path -LiteralPath $Path -PathType Leaf) -and -not $ReplaceCredential) {
        throw 'Encrypted Runtime API key already exists. Use -ReplaceCredential to rotate it.'
    }
}

function Protect-ByteMcpCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [SecureString] $Credential,
        [Parameter(Mandatory)] [string] $Path
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $protected = ConvertFrom-SecureString -SecureString $Credential
    [System.IO.File]::WriteAllText(
        $Path,
        $protected,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Unprotect-ByteMcpCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Encrypted Runtime API key is missing.'
    }

    $protected = [System.IO.File]::ReadAllText($Path).Trim()
    ConvertTo-SecureString -String $protected
}

function New-LauncherChildRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [int] $ProcessId,
        [Parameter(Mandatory)] [string] $ExecutablePath,
        [Parameter(Mandatory)] [string] $StartedAtUtc
    )

    [PSCustomObject]@{
        pid = $ProcessId
        executable_path = [System.IO.Path]::GetFullPath($ExecutablePath)
        started_at_utc = ([datetime] $StartedAtUtc).ToUniversalTime().ToString('o')
    }
}

function New-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RepoPath,
        [Parameter(Mandatory)] [string] $Mode,
        [Parameter(Mandatory)] [int] $ServerPid,
        [Parameter(Mandatory)] [string] $ServerExecutable,
        [Parameter(Mandatory)] [string] $ServerStartedAtUtc,
        [Parameter(Mandatory)] [int] $TunnelPid,
        [Parameter(Mandatory)] [string] $TunnelExecutable,
        [Parameter(Mandatory)] [string] $TunnelStartedAtUtc
    )

    [PSCustomObject]@{
        schema_version = 1
        started_at_utc = [datetime]::UtcNow.ToString('o')
        mode = $Mode
        repo_path = $RepoPath
        root_profile = 'projects'
        tunnel_profile = 'byte-mcp-local'
        server = New-LauncherChildRecord -ProcessId $ServerPid -ExecutablePath $ServerExecutable -StartedAtUtc $ServerStartedAtUtc
        tunnel = New-LauncherChildRecord -ProcessId $TunnelPid -ExecutablePath $TunnelExecutable -StartedAtUtc $TunnelStartedAtUtc
    }
}

function Write-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [pscustomobject] $State,
        [Parameter(Mandatory)] [string] $Path
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    $tempPath = "$Path.tmp"
    $json = $State | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText(
        $tempPath,
        $json,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Read-LauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )

    try {
        $state = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Malformed launcher state: $($_.Exception.Message)"
    }

    if ($state.schema_version -ne 1) {
        throw 'Unsupported launcher state schema.'
    }

    $state
}
