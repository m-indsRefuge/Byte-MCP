Describe 'Setup-Wolfram command contract' {
    BeforeAll {
        $setupScript = Join-Path $PSScriptRoot '../../scripts/Setup-Wolfram.ps1'
    }

    It 'exists and accepts only explicit replacement authority' {
        Test-Path -LiteralPath $setupScript -PathType Leaf | Should -BeTrue
        $command = Get-Command -Name $setupScript -ErrorAction Stop
        $command.Parameters.Keys | Should -Contain 'ReplaceCredential'
        $command.Parameters.Keys | Should -Not -Contain 'AppId'
        $command.Parameters.Keys | Should -Not -Contain 'ApiKey'
        $command.Parameters.Keys | Should -Not -Contain 'Credential'
    }

    It 'uses a secure Wolfram AppID prompt and DPAPI helpers' {
        $content = Get-Content -LiteralPath $setupScript -Raw
        $content | Should -Match "Read-Host\s+'Paste the Wolfram\|Alpha LLM API AppID'\s+-AsSecureString"
        $content | Should -Match 'Protect-ByteMcpCredential'
        $content | Should -Match 'Unprotect-ByteMcpCredential'
        $content | Should -Match 'WolframCredentialFile'
        $content | Should -Not -Match 'WOLFRAM_APP_ID\s*='
    }

    It 'loads platform common and Wolfram launcher modules in order' {
        $content = Get-Content -LiteralPath $setupScript -Raw
        $platformIndex = $content.IndexOf('Launcher.Platform.ps1')
        $commonIndex = $content.IndexOf('Launcher.Common.ps1')
        $wolframIndex = $content.IndexOf('Launcher.Wolfram.ps1')
        $platformIndex | Should -BeGreaterThan -1
        $commonIndex | Should -BeGreaterThan $platformIndex
        $wolframIndex | Should -BeGreaterThan $commonIndex
    }
}
