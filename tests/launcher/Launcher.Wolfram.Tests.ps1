Describe 'Wolfram launcher extension' {
    BeforeAll {
        . "$PSScriptRoot/../../scripts/Launcher.Platform.ps1"
        . "$PSScriptRoot/../../scripts/Launcher.Common.ps1"
        . "$PSScriptRoot/../../scripts/Launcher.Wolfram.ps1"

        function New-WolframRuntimePaths {
            $paths = [PSCustomObject]@{
                RepoRoot       = 'C:\repo'
                PythonPath     = 'C:\repo\.venv\Scripts\python.exe'
                LocalRoot      = 'C:\Users\test\.byte-mcp'
                ServerStdOut   = 'C:\Users\test\.byte-mcp\logs\byte-mcp-server.log'
                ServerStdErr   = 'C:\Users\test\.byte-mcp\logs\byte-mcp-server.err.log'
            }
            Add-WolframLauncherPaths -Paths $paths -UserProfile 'C:\Users\test'
        }
    }

    It 'adds machine-local Wolfram credential and usage paths' {
        $paths = New-WolframRuntimePaths
        $paths.WolframCredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\wolfram-appid.dpapi'
        $paths.WolframUsageFile | Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
        (Get-ByteMcpWolframServerEnvironment -UserProfile 'C:\Users\test').BYTE_MCP_WOLFRAM_USAGE_FILE |
            Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
    }

    It 'scrubs an inherited Wolfram AppID when no dedicated credential exists' {
        $prior = [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process')
        [Environment]::SetEnvironmentVariable('WOLFRAM_APP_ID', 'parent-sentinel', 'Process')
        $script:observed = 'not-called'
        try {
            Mock Test-Path {
                if ($LiteralPath -like '*wolfram-appid.dpapi') {
                    return $false
                }
                if ($LiteralPath -like 'Env:*') {
                    $name = ([string] $LiteralPath).Substring(4)
                    return $null -ne [Environment]::GetEnvironmentVariable($name, 'Process')
                }
                throw "Unexpected Test-Path call in Wolfram launcher test: $LiteralPath"
            }
            Mock Get-ByteMcpServerEnvironment { @{} }
            Mock Start-Process {
                $script:observed = [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process')
                [PSCustomObject]@{ Id = 101; Path = 'C:\repo\.venv\Scripts\python.exe'; StartTime = Get-Date }
            }

            $null = Start-LauncherServerProcess -Paths (New-WolframRuntimePaths)

            $script:observed | Should -BeNullOrEmpty
            [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process') | Should -Be 'parent-sentinel'
        }
        finally {
            [Environment]::SetEnvironmentVariable('WOLFRAM_APP_ID', $prior, 'Process')
        }
    }

    It 'injects the DPAPI-protected Wolfram AppID only during child creation' {
        $prior = [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process')
        [Environment]::SetEnvironmentVariable('WOLFRAM_APP_ID', 'parent-sentinel', 'Process')
        $script:observed = $null
        try {
            Mock Test-Path {
                if ($LiteralPath -like '*wolfram-appid.dpapi') {
                    return $true
                }
                if ($LiteralPath -like 'Env:*') {
                    $name = ([string] $LiteralPath).Substring(4)
                    return $null -ne [Environment]::GetEnvironmentVariable($name, 'Process')
                }
                throw "Unexpected Test-Path call in Wolfram launcher test: $LiteralPath"
            }
            Mock Get-ByteMcpServerEnvironment { @{} }
            Mock Unprotect-ByteMcpCredential { ConvertTo-SecureString 'child-wolfram-secret' -AsPlainText -Force }
            Mock Start-Process {
                $script:observed = [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process')
                [PSCustomObject]@{ Id = 101; Path = 'C:\repo\.venv\Scripts\python.exe'; StartTime = Get-Date }
            }

            $null = Start-LauncherServerProcess -Paths (New-WolframRuntimePaths)

            $script:observed | Should -Be 'child-wolfram-secret'
            [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process') | Should -Be 'parent-sentinel'
        }
        finally {
            [Environment]::SetEnvironmentVariable('WOLFRAM_APP_ID', $prior, 'Process')
        }
    }

    It 'uses the same injection boundary in foreground mode' {
        $script:observed = $null
        Mock Test-Path {
            if ($LiteralPath -like '*wolfram-appid.dpapi') {
                return $true
            }
            if ($LiteralPath -like 'Env:*') {
                $name = ([string] $LiteralPath).Substring(4)
                return $null -ne [Environment]::GetEnvironmentVariable($name, 'Process')
            }
            throw "Unexpected Test-Path call in Wolfram launcher test: $LiteralPath"
        }
        Mock Get-ByteMcpServerEnvironment { @{} }
        Mock Unprotect-ByteMcpCredential { ConvertTo-SecureString 'child-wolfram-secret' -AsPlainText -Force }
        Mock Start-Process {
            $script:observed = [Environment]::GetEnvironmentVariable('WOLFRAM_APP_ID', 'Process')
            [PSCustomObject]@{ Id = 101; Path = 'C:\repo\.venv\Scripts\python.exe'; StartTime = Get-Date }
        }

        $null = Start-LauncherForegroundServer -Paths (New-WolframRuntimePaths)

        $script:observed | Should -Be 'child-wolfram-secret'
    }
}
