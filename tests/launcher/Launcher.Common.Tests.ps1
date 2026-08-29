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
}
