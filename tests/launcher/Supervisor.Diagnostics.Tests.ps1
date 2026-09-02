BeforeAll {
    . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"

    function New-DiagnosticsTestState {
        New-LauncherState -RepoPath 'C:\repo' -Mode 'background' `
            -ServerPid 101 -ServerExecutable 'C:\Python\python.exe' -ServerStartedAtUtc '2026-08-29T10:00:00Z' `
            -TunnelPid 202 -TunnelExecutable 'C:\OpenAI\tunnel-client.exe' -TunnelStartedAtUtc '2026-08-29T10:00:01Z'
    }

    function Set-AllReadinessMocks {
        Mock Test-ManagedServerProcess { $true }
        Mock Test-ByteMcpEndpoint { $true }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $true }
        Mock Test-TunnelReady { $true }
    }
}

Describe 'Q03D exact readiness diagnostics' {
    BeforeEach {
        Set-AllReadinessMocks
    }

    It 'reports no failed components when every readiness component passes' {
        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents).Count | Should -Be 0
        $status.Overall | Should -Be 'READY'
    }

    It 'reports ServerProcess exactly when only the managed server identity fails' {
        Mock Test-ManagedServerProcess { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @('ServerProcess')
        $status.Overall | Should -Be 'DEGRADED'
    }

    It 'reports McpEndpoint exactly when only the MCP endpoint fails' {
        Mock Test-ByteMcpEndpoint { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @('McpEndpoint')
        $status.Overall | Should -Be 'DEGRADED'
    }

    It 'reports TunnelProcess exactly when only the managed tunnel identity fails' {
        Mock Test-ManagedTunnelProcess { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @('TunnelProcess')
        $status.Overall | Should -Be 'DEGRADED'
    }

    It 'reports TunnelHealth exactly when only tunnel liveness fails' {
        Mock Test-TunnelHealth { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @('TunnelHealth')
        $status.Overall | Should -Be 'DEGRADED'
    }

    It 'reports TunnelReady exactly when only tunnel readiness fails' {
        Mock Test-TunnelReady { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @('TunnelReady')
        $status.Overall | Should -Be 'DEGRADED'
    }

    It 'reports multiple failed components in the locked readiness evaluation order' {
        Mock Test-ManagedServerProcess { $false }
        Mock Test-ByteMcpEndpoint { $false }
        Mock Test-ManagedTunnelProcess { $true }
        Mock Test-TunnelHealth { $false }
        Mock Test-TunnelReady { $false }

        $status = Get-ByteMcpStatus -State (New-DiagnosticsTestState)

        @($status.FailedComponents) | Should -Be @(
            'ServerProcess',
            'McpEndpoint',
            'TunnelHealth',
            'TunnelReady'
        )
    }
}

Describe 'Q03D tracked supervisor source and cadence contract' {
    BeforeAll {
        $script:supervisorPath = Join-Path $PSScriptRoot '../../scripts/ByteMCP-Supervisor.ps1'
        $script:supervisorExists = Test-Path -LiteralPath $script:supervisorPath -PathType Leaf
        $script:supervisorText = if ($script:supervisorExists) {
            Get-Content -LiteralPath $script:supervisorPath -Raw
        }
        else {
            ''
        }
    }

    It 'has a tracked canonical supervisor source in the repository' {
        $script:supervisorExists | Should -BeTrue
    }

    It 'preserves the 30-second normal health-check default and cadence' {
        $script:supervisorText | Should -Match '\[int\]\s+\$HealthCheckSeconds\s*=\s*30'
        $script:supervisorText | Should -Match 'Start-Sleep\s+-Seconds\s+\$HealthCheckSeconds'
    }

    It 'logs the exact failed readiness components when repairing a DEGRADED active stack' {
        $script:supervisorText | Should -Match 'FailedComponents'
        $script:supervisorText | Should -Match 'failed='
        $script:supervisorText | Should -Match 'Repair-Stack\s+-Reason'
    }

    It 'retains the existing startup timeout default' {
        $script:supervisorText | Should -Match '\[int\]\s+\$StartupTimeoutSeconds\s*=\s*60'
    }
}
