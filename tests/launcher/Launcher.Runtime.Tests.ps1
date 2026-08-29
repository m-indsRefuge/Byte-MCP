BeforeAll {
    . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"

    $script:runtimePaths = [PSCustomObject]@{
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

    function New-RuntimeTestState {
        New-LauncherState -RepoPath 'C:\repo' -Mode 'background' `
            -ServerPid 101 -ServerExecutable 'C:\Python\python.exe' -ServerStartedAtUtc '2026-08-29T10:00:00Z' `
            -TunnelPid 202 -TunnelExecutable 'C:\OpenAI\tunnel-client.exe' -TunnelStartedAtUtc '2026-08-29T10:00:01Z'
    }
}

Describe 'Launcher process ownership and state classification' {
    It 'accepts a process only when PID, executable path, and start time all match' {
        $record = [PSCustomObject]@{
            pid = 101
            executable_path = 'C:\Python\python.exe'
            started_at_utc = '2026-08-29T10:00:00.0000000Z'
        }
        $process = [PSCustomObject]@{
            Id = 101
            Path = 'C:\Python\python.exe'
            StartTime = [datetime]'2026-08-29T10:00:00Z'
        }

        Test-LauncherProcessIdentity -Record $record -Process $process | Should -BeTrue
    }

    It 'rejects PID reuse when executable identity differs' {
        $record = [PSCustomObject]@{
            pid = 101
            executable_path = 'C:\Python\python.exe'
            started_at_utc = '2026-08-29T10:00:00.0000000Z'
        }
        $process = [PSCustomObject]@{
            Id = 101
            Path = 'C:\Other\python.exe'
            StartTime = [datetime]'2026-08-29T10:00:00Z'
        }

        Test-LauncherProcessIdentity -Record $record -Process $process | Should -BeFalse
    }

    It 'rejects PID reuse when process start time differs' {
        $record = [PSCustomObject]@{
            pid = 101
            executable_path = 'C:\Python\python.exe'
            started_at_utc = '2026-08-29T10:00:00.0000000Z'
        }
        $process = [PSCustomObject]@{
            Id = 101
            Path = 'C:\Python\python.exe'
            StartTime = [datetime]'2026-08-29T10:01:00Z'
        }

        Test-LauncherProcessIdentity -Record $record -Process $process | Should -BeFalse
    }

    It 'classifies a missing state file as absent' {
        $path = Join-Path $TestDrive 'missing-state.json'
        Get-LauncherStateClassification -StatePath $path | Should -Be 'absent'
    }

    It 'classifies malformed JSON as malformed' {
        $path = Join-Path $TestDrive 'malformed-state.json'
        Set-Content -LiteralPath $path -Value '{not-json'
        Get-LauncherStateClassification -StatePath $path | Should -Be 'malformed'
    }

    It 'classifies state as stale when a recorded process identity does not verify' {
        $path = Join-Path $TestDrive 'stale-state.json'
        Write-LauncherState -State (New-RuntimeTestState) -Path $path

        Mock Get-Process {
            $requestedId = [int]$PesterBoundParameters['Id']
            if ($requestedId -eq 101) {
                return [PSCustomObject]@{ Id = 101; Path = 'C:\Wrong\python.exe'; StartTime = [datetime]'2026-08-29T10:00:00Z' }
            }
            [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = [datetime]'2026-08-29T10:00:01Z' }
        }

        Get-LauncherStateClassification -StatePath $path | Should -Be 'stale'
    }

    It 'classifies state as active only when both child identities verify' {
        $path = Join-Path $TestDrive 'active-state.json'
        Write-LauncherState -State (New-RuntimeTestState) -Path $path

        Mock Get-Process {
            $requestedId = [int]$PesterBoundParameters['Id']
            if ($requestedId -eq 101) {
                return [PSCustomObject]@{ Id = 101; Path = 'C:\Python\python.exe'; StartTime = [datetime]'2026-08-29T10:00:00Z' }
            }
            [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = [datetime]'2026-08-29T10:00:01Z' }
        }

        Get-LauncherStateClassification -StatePath $path | Should -Be 'active'
    }
}

Describe 'Launcher health probes and read-only status' {
    It 'treats the reachable raw MCP endpoint as live even when it returns HTTP 406' {
        Mock Invoke-LauncherHttpProbe {
            [PSCustomObject]@{ reachable = $true; status_code = 406; body = '' }
        }

        Test-ByteMcpEndpoint | Should -BeTrue
    }

    It 'requires exact tunnel health and readiness responses' {
        Mock Invoke-LauncherHttpProbe {
            $uri = [string]$PesterBoundParameters['Uri']
            if ($uri -like '*/healthz') {
                return [PSCustomObject]@{ reachable = $true; status_code = 200; body = 'live' }
            }
            [PSCustomObject]@{ reachable = $true; status_code = 200; body = 'ready' }
        }

        Test-TunnelHealth | Should -BeTrue
        Test-TunnelReady | Should -BeTrue
    }

    It 'reports READY only when both managed processes and every probe pass' {
        Mock Test-ManagedServerProcess { $true }
        Mock Test-ByteMcpEndpoint { $true }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $true }
        Mock Test-TunnelReady { $true }

        (Get-ByteMcpStatus -State (New-RuntimeTestState)).Overall | Should -Be 'READY'
    }

    It 'reports DEGRADED when any required runtime probe fails' {
        Mock Test-ManagedServerProcess { $true }
        Mock Test-ByteMcpEndpoint { $true }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $true }
        Mock Test-TunnelReady { $false }

        (Get-ByteMcpStatus -State (New-RuntimeTestState)).Overall | Should -Be 'DEGRADED'
    }

    It 'provides an observational status entry point that does not mutate launcher state' {
        $statusScript = Join-Path $PSScriptRoot '../../scripts/Status-ByteMCP.ps1'
        Test-Path -LiteralPath $statusScript -PathType Leaf | Should -BeTrue

        $content = Get-Content -LiteralPath $statusScript -Raw
        $content | Should -Not -Match 'Write-LauncherState'
        $content | Should -Not -Match 'Remove-Item[^\r\n]*StateFile'
    }
}

Describe 'Launcher transactional background startup' {
    It 'rotates only one previous log generation' {
        $path = Join-Path $TestDrive 'launcher.log'
        $previous = "$path.previous"
        Set-Content -LiteralPath $path -Value 'current'
        Set-Content -LiteralPath $previous -Value 'older'

        Rotate-LauncherLog -Path $path

        Test-Path -LiteralPath $path | Should -BeFalse
        (Get-Content -LiteralPath $previous -Raw).Trim() | Should -Be 'current'
        Test-Path -LiteralPath "$previous.previous" | Should -BeFalse
    }

    It 'injects server environment only for child creation and restores the parent process' {
        $priorHost = [Environment]::GetEnvironmentVariable('BYTE_MCP_HOST', 'Process')
        [Environment]::SetEnvironmentVariable('BYTE_MCP_HOST', 'parent-sentinel', 'Process')
        $script:observedServerHost = $null

        try {
            Mock Start-Process {
                $script:observedServerHost = [Environment]::GetEnvironmentVariable('BYTE_MCP_HOST', 'Process')
                [PSCustomObject]@{ Id = 101; Path = 'C:\repo\.venv\Scripts\python.exe'; StartTime = Get-Date }
            }

            $null = Start-LauncherServerProcess -Paths $script:runtimePaths

            $script:observedServerHost | Should -Be '127.0.0.1'
            [Environment]::GetEnvironmentVariable('BYTE_MCP_HOST', 'Process') | Should -Be 'parent-sentinel'
        }
        finally {
            [Environment]::SetEnvironmentVariable('BYTE_MCP_HOST', $priorHost, 'Process')
        }
    }

    It 'injects the decrypted Runtime API key only during tunnel child creation and restores the parent value' {
        $priorKey = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process')
        [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'parent-sentinel', 'Process')
        $script:observedTunnelKey = $null

        try {
            Mock Unprotect-ByteMcpCredential { ConvertTo-SecureString 'child-secret' -AsPlainText -Force }
            Mock Get-TunnelClientPath { 'C:\Tools\tunnel-client.exe' }
            Mock Start-Process {
                $script:observedTunnelKey = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process')
                [PSCustomObject]@{ Id = 202; Path = 'C:\Tools\tunnel-client.exe'; StartTime = Get-Date }
            }

            $null = Start-LauncherTunnelProcess -Paths $script:runtimePaths

            $script:observedTunnelKey | Should -Be 'child-secret'
            [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'Process') | Should -Be 'parent-sentinel'
        }
        finally {
            [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY', $priorKey, 'Process')
        }
    }

    It 'does not create a duplicate stack when the existing managed stack is READY' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Get-LauncherStateClassification { 'active' }
        Mock Read-LauncherState { New-RuntimeTestState }
        Mock Get-ByteMcpStatus { [PSCustomObject]@{ Overall = 'READY' } }
        Mock Start-LauncherServerProcess {}

        $result = Start-ByteMcpBackgroundStack -Paths $script:runtimePaths -StartupTimeoutSeconds 5

        Should -Invoke Start-LauncherServerProcess -Times 0
        $result.Overall | Should -Be 'READY'
    }

    It 'rejects unmanaged listener conflicts before starting any child process' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Get-LauncherStateClassification { 'absent' }
        Mock Get-NetTCPConnection {
            [PSCustomObject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8000; State = 'Listen'; OwningProcess = 999 }
        }
        Mock Start-LauncherServerProcess {}

        { Start-ByteMcpBackgroundStack -Paths $script:runtimePaths -StartupTimeoutSeconds 5 } |
            Should -Throw '*port*'
        Should -Invoke Start-LauncherServerProcess -Times 0
    }

    It 'rolls back both children in reverse order when tunnel readiness fails' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Get-LauncherStateClassification { 'absent' }
        Mock Get-NetTCPConnection { $null }
        Mock Rotate-LauncherLog {}
        Mock Start-LauncherServerProcess { [PSCustomObject]@{ Id = 101; Path = 'C:\Python\python.exe'; StartTime = Get-Date } }
        Mock Wait-ByteMcpEndpoint { $true }
        Mock Start-LauncherTunnelProcess { [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = Get-Date } }
        Mock Wait-TunnelHealth { $true }
        Mock Wait-TunnelReady { $false }
        Mock Stop-LauncherCreatedProcess {}
        Mock Write-LauncherState {}

        { Start-ByteMcpBackgroundStack -Paths $script:runtimePaths -StartupTimeoutSeconds 1 } | Should -Throw

        Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 202 } -Times 1
        Should -Invoke Stop-LauncherCreatedProcess -ParameterFilter { $Process.Id -eq 101 } -Times 1
        Should -Invoke Write-LauncherState -Times 0
    }

    It 'writes managed state only after MCP, tunnel health, and tunnel readiness all succeed' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Get-LauncherStateClassification { 'absent' }
        Mock Get-NetTCPConnection { $null }
        Mock Rotate-LauncherLog {}
        Mock Start-LauncherServerProcess { [PSCustomObject]@{ Id = 101; Path = 'C:\Python\python.exe'; StartTime = [datetime]'2026-08-29T10:00:00Z' } }
        Mock Wait-ByteMcpEndpoint { $true }
        Mock Start-LauncherTunnelProcess { [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = [datetime]'2026-08-29T10:00:01Z' } }
        Mock Wait-TunnelHealth { $true }
        Mock Wait-TunnelReady { $true }
        Mock Write-LauncherState {}

        $result = Start-ByteMcpBackgroundStack -Paths $script:runtimePaths -StartupTimeoutSeconds 5

        Should -Invoke Wait-ByteMcpEndpoint -Times 1
        Should -Invoke Wait-TunnelHealth -Times 1
        Should -Invoke Wait-TunnelReady -Times 1
        Should -Invoke Write-LauncherState -Times 1
        $result.Overall | Should -Be 'READY'
    }

    It 'provides the background launcher entry point with foreground and timeout controls' {
        $startScript = Join-Path $PSScriptRoot '../../scripts/Start-ByteMCP.ps1'
        Test-Path -LiteralPath $startScript -PathType Leaf | Should -BeTrue

        $command = Get-Command -Name $startScript -ErrorAction Stop
        $command.Parameters.Keys | Should -Contain 'Foreground'
        $command.Parameters.Keys | Should -Contain 'StartupTimeoutSeconds'
    }
}

Describe 'Launcher foreground troubleshooting mode' {
    It 'never writes managed launcher state in foreground mode' {
        Mock Assert-ByteMcpLauncherPrerequisites {}
        Mock Start-LauncherForegroundServer { [PSCustomObject]@{ Id = 101; Path = 'C:\Python\python.exe'; StartTime = Get-Date } }
        Mock Wait-ByteMcpEndpoint { $true }
        Mock Start-LauncherForegroundTunnel { [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = Get-Date } }
        Mock Wait-TunnelHealth { $true }
        Mock Wait-TunnelReady { $true }
        Mock Wait-Process {}
        Mock Stop-LauncherCreatedProcess {}
        Mock Write-LauncherState {}

        Start-ByteMcpForegroundStack -Paths $script:runtimePaths -StartupTimeoutSeconds 1

        Should -Invoke Write-LauncherState -Times 0
    }
}

Describe 'Launcher verified and idempotent shutdown' {
    It 'is safe when no managed state exists' {
        Mock Get-LauncherStateClassification { 'absent' }
        { Stop-ByteMcpManagedStack -StatePath (Join-Path $TestDrive 'missing.json') } | Should -Not -Throw
    }

    It 'never stops a process whose recorded identity cannot be verified' {
        $statePath = Join-Path $TestDrive 'active.json'
        $script:managedState = New-RuntimeTestState
        Write-LauncherState -State $script:managedState -Path $statePath

        Mock Get-LauncherStateClassification { 'active' }
        Mock Read-LauncherState { $script:managedState }
        Mock Get-Process {
            [PSCustomObject]@{ Id = 202; Path = 'C:\Other\tunnel-client.exe'; StartTime = Get-Date }
        }
        Mock Test-LauncherProcessIdentity { $false }
        Mock Stop-Process {}

        { Stop-ByteMcpManagedStack -StatePath $statePath } | Should -Throw '*unverified*'
        Should -Invoke Stop-Process -Times 0
    }

    It 'stops verified tunnel then server and removes state only after listeners are gone' {
        $statePath = Join-Path $TestDrive 'verified.json'
        $script:managedState = New-RuntimeTestState
        Write-LauncherState -State $script:managedState -Path $statePath
        $script:stopOrder = @()

        Mock Get-LauncherStateClassification { 'active' }
        Mock Read-LauncherState { $script:managedState }
        Mock Get-Process {
            $requestedId = [int]$PesterBoundParameters['Id']
            if ($requestedId -eq 202) {
                return [PSCustomObject]@{ Id = 202; Path = 'C:\OpenAI\tunnel-client.exe'; StartTime = [datetime]'2026-08-29T10:00:01Z' }
            }
            [PSCustomObject]@{ Id = 101; Path = 'C:\Python\python.exe'; StartTime = [datetime]'2026-08-29T10:00:00Z' }
        }
        Mock Test-LauncherProcessIdentity { $true }
        Mock Stop-Process {
            $script:stopOrder += [int]$PesterBoundParameters['Id']
        }
        Mock Wait-Process {}
        Mock Confirm-LauncherListenersStopped { $true }

        Stop-ByteMcpManagedStack -StatePath $statePath

        $script:stopOrder | Should -Be @(202, 101)
        Test-Path -LiteralPath $statePath | Should -BeFalse
    }

    It 'refuses shutdown when launcher state is malformed' {
        Mock Get-LauncherStateClassification { 'malformed' }
        Mock Stop-Process {}

        { Stop-ByteMcpManagedStack -StatePath 'C:\state.json' } |
            Should -Throw '*Launcher state is malformed*'
        Should -Invoke Stop-Process -Times 0
    }

    It 'refuses shutdown when launcher state is stale' {
        Mock Get-LauncherStateClassification { 'stale' }
        Mock Stop-Process {}

        { Stop-ByteMcpManagedStack -StatePath 'C:\state.json' } |
            Should -Throw '*Launcher state is stale*'
        Should -Invoke Stop-Process -Times 0
    }

    It 'provides a stop entry point and never falls back to killing by executable name' {
        $stopScript = Join-Path $PSScriptRoot '../../scripts/Stop-ByteMCP.ps1'
        Test-Path -LiteralPath $stopScript -PathType Leaf | Should -BeTrue

        $content = Get-Content -LiteralPath $stopScript -Raw
        $content | Should -Not -Match 'Stop-Process\s+-Name'
    }
}
