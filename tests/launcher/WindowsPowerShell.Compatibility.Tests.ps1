Describe 'Windows PowerShell 5.1 compatibility' {
    It 'runs the launcher HTTP probe without relying on preloaded System.Net.Http types' {
        $platformScript = Join-Path $PSScriptRoot '../../scripts/Launcher.Platform.ps1'
        $commonScript = Join-Path $PSScriptRoot '../../scripts/Launcher.Common.ps1'

        $escapedPlatform = $platformScript.Replace("'", "''")
        $escapedCommon = $commonScript.Replace("'", "''")
        $command = @"
`$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. '$escapedPlatform'
. '$escapedCommon'
`$result = Invoke-LauncherHttpProbe -Uri 'http://127.0.0.1:65535' -TimeoutSeconds 1
if (`$result.reachable) { exit 3 }
exit 0
"@

        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $command
        $LASTEXITCODE | Should -Be 0
    }
}
