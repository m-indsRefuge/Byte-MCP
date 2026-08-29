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
