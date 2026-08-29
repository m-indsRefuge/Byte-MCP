BeforeAll {
    . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"
    . "$PSScriptRoot/../../scripts/Launcher.Ownership.ps1"

    $script:ownershipPaths = [PSCustomObject]@{
        RepoRoot          = 'C:\repo'
        PythonPath        = 'C:\repo\.venv\Scripts\python.exe'
        LocalRoot         = 'C:\Users\test\.byte-mcp'
        RootsFile         = 'C:\Users\test\.byte-mcp\roots.web.json'
        AuditFile         = 'C:\Users\test\.byte-mcp\audit.web.jsonl'
        CredentialFile    = 'C:\Users\test\.byte-mcp\credentials\tunnel-runtime-key.dpapi'
        RuntimeDir        = 'C:\Users\test\.byte-mcp\runtime'
        StateFile         = 'C:\Users\test\.byte-mcp\runtime\launcher-state.json'
        LogsDir           = 'C:\Users\test\.byte-mcp\logs'
        ServerStdOut      = 'C:\Users\test\.byte-mcp\logs\byte-mcp-server.log'
        ServerStdErr      = 'C:\Users\test\.byte-mcp\logs\byte-mcp-server.err.log'
        TunnelStdOut      = 'C:\Users\test\.byte-mcp\logs\tunnel-client.log'
        TunnelStdErr      = 'C:\Users\test\.byte-mcp\logs\tunnel-client.err.log'
        TunnelProfile     = 'byte-mcp-local'
        TunnelProfileFile = 'C:\Users\test\AppData\Roaming\tunnel-client\byte-mcp-local.yaml'
    }
}

Describe 'Launcher live server ownership' {
    BeforeEach {
        Mock Get-NetTCPConnection {
            [PSCustomObject]@{
                LocalAddress = '127.0.0.1'
                LocalPort = 8000
                State = 'Listen'
                OwningProcess = 25520
            }
        }
        Mock Get-Process {
            [PSCustomObject]@{
                Id = 25520
                Path = 'C:\Python312\python.exe'
                StartTime = [datetime]'2026-08-29T13:26:34Z'
            }
        } -ParameterFilter { $Id -eq 25520 }
        Mock Get-CimInstance {
            [PSCustomObject]@{
                ProcessId = 25520
                ParentProcessId = 38800
                ExecutablePath = 'C:\Python312\python.exe'
            }
        }
    }

    It 'records the actual port 8000 listener process instead of the venv redirector' {
        $script:writtenState = $null

        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Get-LauncherStateClassification { 'absent' }
        Mock Get-LauncherPortConflicts { @() }
        Mock Rotate-LauncherLog {}
        Mock Start-LauncherServerProcess {
            [PSCustomObject]@{
                Id = 38800
                Path = 'C:\repo\.venv\Scripts\python.exe'
                StartTime = [datetime]'2026-08-29T13:26:34Z'
            }
        }
        Mock Wait-ByteMcpEndpoint { $true }
        Mock Start-LauncherTunnelProcess {
            [PSCustomObject]@{
                Id = 40508
                Path = 'C:\OpenAI\tunnel-client.exe'
                StartTime = [datetime]'2026-08-29T13:26:36Z'
            }
        }
        Mock Wait-TunnelHealth { $true }
        Mock Wait-TunnelReady { $true }
        Mock Write-LauncherState { $script:writtenState = $State }

        $null = Start-ByteMcpBackgroundStack -Paths $script:ownershipPaths -StartupTimeoutSeconds 5

        $script:writtenState | Should -Not -BeNullOrEmpty
        $script:writtenState.server.pid | Should -Be 25520
        $script:writtenState.server.executable_path | Should -Be 'C:\Python312\python.exe'
    }

    It 'stops the actual foreground listener as well as the venv redirector' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Start-LauncherForegroundServer {
            [PSCustomObject]@{
                Id = 38800
                Path = 'C:\repo\.venv\Scripts\python.exe'
                StartTime = [datetime]'2026-08-29T13:26:34Z'
            }
        }
        Mock Wait-ByteMcpEndpoint { $true }
        Mock Start-LauncherForegroundTunnel {
            [PSCustomObject]@{
                Id = 40508
                Path = 'C:\OpenAI\tunnel-client.exe'
                StartTime = [datetime]'2026-08-29T13:26:36Z'
            }
        }
        Mock Wait-TunnelHealth { $true }
        Mock Wait-TunnelReady { $true }
        Mock Wait-Process {}
        Mock Stop-LauncherCreatedProcess {}

        Start-ByteMcpForegroundStack -Paths $script:ownershipPaths -StartupTimeoutSeconds 5

        Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 25520 } -Times 1
        Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 38800 } -Times 1
    }
}
