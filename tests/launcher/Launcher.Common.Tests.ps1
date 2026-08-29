Describe 'Launcher configuration contract' {
    BeforeAll {
        $commonScript = Join-Path $PSScriptRoot '../../scripts/Launcher.Common.ps1'
        if (Test-Path -LiteralPath $commonScript -PathType Leaf) {
            . $commonScript
        }
    }

    It 'uses the machine-local .byte-mcp runtime area' {
        $paths = Get-ByteMcpLauncherPaths -RepoRoot 'C:\repo' -UserProfile 'C:\Users\test'
        $paths.CredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
        $paths.StateFile | Should -Be 'C:\Users\test\.byte-mcp\runtime\launcher-state.json'
        $paths.TunnelProfile | Should -Be 'byte-mcp-local'
    }

    It 'builds the accepted AIProjects-only Byte-MCP environment' {
        $map = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
        $map.BYTE_MCP_ROOTS_FILE | Should -Be 'C:\Users\test\.byte-mcp\roots.web.json'
        $map.BYTE_MCP_AUDIT_FILE | Should -Be 'C:\Users\test\.byte-mcp\audit.web.jsonl'
        $map.BYTE_MCP_HOST | Should -Be '127.0.0.1'
        $map.BYTE_MCP_PORT | Should -Be '8000'
        $map.BYTE_MCP_TRANSPORT | Should -Be 'streamable-http'
        $map.BYTE_MCP_MAX_FILE_BYTES | Should -Be '1000000'
        $map.BYTE_MCP_MAX_RESPONSE_CHARS | Should -Be '10000'
        $map.BYTE_MCP_MAX_SEARCH_FILES | Should -Be '20000'
        $map.BYTE_MCP_CONTENT_SEARCH_MAX_BYTES | Should -Be '250000'
    }

    It 'resolves tunnel-client as an application executable' {
        Mock Get-Command {
            [PSCustomObject]@{ Source = 'C:\Tools\tunnel-client.exe' }
        } -ParameterFilter {
            $Name -eq 'tunnel-client' -and $CommandType -eq 'Application'
        }

        Get-TunnelClientPath | Should -Be 'C:\Tools\tunnel-client.exe'
    }

    It 'accepts complete prerequisites when credential checking is skipped' {
        $paths = [PSCustomObject]@{
            RepoRoot          = 'C:\repo'
            PythonPath        = 'C:\repo\.venv\Scripts\python.exe'
            RootsFile         = 'C:\Users\test\.byte-mcp\roots.web.json'
            CredentialFile    = 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
            TunnelProfileFile = 'C:\Users\test\AppData\Roaming\tunnel-client\byte-mcp-local.yaml'
        }

        Mock Test-Path { $true }
        Mock Get-TunnelClientPath { 'C:\Tools\tunnel-client.exe' }

        { Assert-ByteMcpLauncherPrerequisites -Paths $paths -SkipCredentialCheck } | Should -Not -Throw
    }

    It 'requires the encrypted credential by default' {
        $paths = [PSCustomObject]@{
            RepoRoot          = 'C:\repo'
            PythonPath        = 'C:\repo\.venv\Scripts\python.exe'
            RootsFile         = 'C:\Users\test\.byte-mcp\roots.web.json'
            CredentialFile    = 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
            TunnelProfileFile = 'C:\Users\test\AppData\Roaming\tunnel-client\byte-mcp-local.yaml'
        }

        Mock Test-Path {
            param($LiteralPath)
            $LiteralPath -ne $paths.CredentialFile
        }
        Mock Get-TunnelClientPath { 'C:\Tools\tunnel-client.exe' }

        { Assert-ByteMcpLauncherPrerequisites -Paths $paths } |
            Should -Throw '*Encrypted tunnel Runtime API key is missing*'
    }
}

Describe 'Launcher state contract' {
    BeforeAll {
        . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"
    }

    It 'serializes state without secret-bearing fields' {
        $state = New-LauncherState -RepoPath 'C:\repo' -Mode 'background' `
            -ServerPid 100 -ServerExecutable 'C:\Python\python.exe' -ServerStartedAtUtc '2026-08-29T10:00:00Z' `
            -TunnelPid 200 -TunnelExecutable 'C:\OpenAI\tunnel-client.exe' -TunnelStartedAtUtc '2026-08-29T10:00:01Z'

        ($state | ConvertTo-Json -Depth 5) | Should -Not -Match 'API_KEY|credential|secret|content|query|reference'
        $state.schema_version | Should -Be 1
        $state.root_profile | Should -Be 'projects'
        $state.tunnel_profile | Should -Be 'byte-mcp-local'
        $state.server.pid | Should -Be 100
        $state.tunnel.pid | Should -Be 200
    }
}
