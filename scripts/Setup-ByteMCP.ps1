[CmdletBinding()]
param(
    [switch] $ReplaceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE

Assert-ByteMcpLauncherPrerequisites -Paths $paths -SkipCredentialCheck
Assert-CredentialWriteAllowed -Path $paths.CredentialFile -ReplaceCredential:$ReplaceCredential

$credential = Read-Host 'Paste the restricted Runtime API key' -AsSecureString
Protect-ByteMcpCredential -Credential $credential -Path $paths.CredentialFile
$null = Unprotect-ByteMcpCredential -Path $paths.CredentialFile

Write-Host 'PASS: Byte-MCP launcher setup complete'
