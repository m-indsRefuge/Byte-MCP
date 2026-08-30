BeforeAll {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $platformScript = Join-Path $repoRoot 'scripts\Launcher.Platform.ps1'
}

Describe 'Windows PowerShell compatibility' {
    It 'initializes IsWindows under Windows PowerShell 5.1 strict mode' {
        $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $command = @"
Set-StrictMode -Version Latest
. '$platformScript'
if (-not `$IsWindows) { exit 2 }
"@

        & $windowsPowerShell -NoProfile -NonInteractive -Command $command

        $LASTEXITCODE | Should -Be 0
    }

    It 'loads platform compatibility before Check.ps1 reads IsWindows' {
        $content = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts\Check.ps1') -Raw
        $platformIndex = $content.IndexOf('Launcher.Platform.ps1')
        $isWindowsIndex = $content.IndexOf('$IsWindows')

        $platformIndex | Should -BeGreaterThan -1
        $isWindowsIndex | Should -BeGreaterThan $platformIndex
    }

    It 'loads platform compatibility before Check-Launcher.ps1 reads IsWindows' {
        $content = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts\Check-Launcher.ps1') -Raw
        $platformIndex = $content.IndexOf('Launcher.Platform.ps1')
        $isWindowsIndex = $content.IndexOf('$IsWindows')

        $platformIndex | Should -BeGreaterThan -1
        $isWindowsIndex | Should -BeGreaterThan $platformIndex
    }
}
