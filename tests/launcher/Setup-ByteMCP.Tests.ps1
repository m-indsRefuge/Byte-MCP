Describe 'Byte-MCP credential lifecycle' {
    BeforeAll {
        . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"
    }

    It 'round-trips a credential through Windows user-bound protection' -Skip:(!$IsWindows) {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        $secret = ConvertTo-SecureString 'test-secret-value' -AsPlainText -Force

        Protect-ByteMcpCredential -Credential $secret -Path $path
        $roundTrip = Unprotect-ByteMcpCredential -Path $path

        [System.Net.NetworkCredential]::new('', $roundTrip).Password |
            Should -Be 'test-secret-value'
        (Get-Content -LiteralPath $path -Raw) |
            Should -Not -Match 'test-secret-value'
    }

    It 'refuses accidental credential replacement' {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        Set-Content -LiteralPath $path -Value 'existing'

        { Assert-CredentialWriteAllowed -Path $path -ReplaceCredential:$false } |
            Should -Throw '*already exists*'
    }

    It 'allows explicit credential replacement' {
        $path = Join-Path $TestDrive 'runtime-key.dpapi'
        Set-Content -LiteralPath $path -Value 'existing'

        { Assert-CredentialWriteAllowed -Path $path -ReplaceCredential:$true } |
            Should -Not -Throw
    }
}

Describe 'Setup-ByteMCP command contract' {
    BeforeAll {
        $setupScript = Join-Path $PSScriptRoot '../../scripts/Setup-ByteMCP.ps1'
    }

    It 'exists as the launcher setup entry point' {
        Test-Path -LiteralPath $setupScript -PathType Leaf | Should -BeTrue
    }

    It 'exposes ReplaceCredential without accepting an API key parameter' {
        $command = Get-Command -Name $setupScript -ErrorAction Stop

        $command.Parameters.Keys | Should -Contain 'ReplaceCredential'
        $command.Parameters.Keys | Should -Not -Contain 'ApiKey'
        $command.Parameters.Keys | Should -Not -Contain 'RuntimeApiKey'
        $command.Parameters.Keys | Should -Not -Contain 'Credential'
    }

    It 'collects the Runtime API key only through a secure prompt' {
        $content = Get-Content -LiteralPath $setupScript -Raw

        $content | Should -Match "Read-Host\s+'Paste the restricted Runtime API key'\s+-AsSecureString"
    }

    It 'checks prerequisites, replacement authority, protection, and round-trip validation' {
        $content = Get-Content -LiteralPath $setupScript -Raw

        $content | Should -Match 'Assert-ByteMcpLauncherPrerequisites\s+-Paths\s+\$paths\s+-SkipCredentialCheck'
        $content | Should -Match 'Assert-CredentialWriteAllowed\s+-Path\s+\$paths\.CredentialFile\s+-ReplaceCredential:\$ReplaceCredential'
        $content | Should -Match 'Protect-ByteMcpCredential\s+-Credential\s+\$credential\s+-Path\s+\$paths\.CredentialFile'
        $content | Should -Match '\$null\s*=\s*Unprotect-ByteMcpCredential\s+-Path\s+\$paths\.CredentialFile'
    }
}
