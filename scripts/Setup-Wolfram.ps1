[CmdletBinding()]
param(
    [switch] $ReplaceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Platform.ps1')
. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')
. (Join-Path $PSScriptRoot 'Launcher.Wolfram.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE
$paths = Add-WolframLauncherPaths -Paths $paths -UserProfile $env:USERPROFILE

Assert-ByteMcpLauncherPrerequisites -Paths $paths -SkipCredentialCheck
Assert-CredentialWriteAllowed `
    -Path $paths.WolframCredentialFile `
    -ReplaceCredential:$ReplaceCredential

$credential = Read-Host 'Paste the Wolfram|Alpha LLM API AppID' -AsSecureString
Protect-ByteMcpCredential -Credential $credential -Path $paths.WolframCredentialFile
$null = Unprotect-ByteMcpCredential -Path $paths.WolframCredentialFile

Write-Host 'PASS: Wolfram AppID setup complete'
