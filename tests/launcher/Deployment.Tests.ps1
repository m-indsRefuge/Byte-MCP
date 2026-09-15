BeforeAll {
    . "$PSScriptRoot/../../scripts/Deployment.Common.ps1"
    function New-PromotionSnapshot {
        param([string] $Head = ('a' * 40), [int] $ProcessId = 10)
        [pscustomobject]@{
            repo_path = 'C:\deployment-test\runtime'; head = $Head; status = 'READY'
            tools = @('fetch', 'search'); server_pid = $ProcessId; server_started = '2026-01-01'
        }
    }
}

Describe 'Deployment path and identity boundaries' {
    It 'rejects a relative runtime path' {
        { Resolve-DeploymentPath '.\runtime' } | Should -Throw '*absolute local path*'
    }
    It 'rejects UNC and short-name aliases' {
        { Resolve-DeploymentPath '\\server\runtime' } | Should -Throw
        { Resolve-DeploymentPath 'C:\PROGRA~1\runtime' } | Should -Throw
    }
    It 'rejects candidate nested within production' {
        { Assert-DeploymentIsolation 'C:\runtime' 'C:\runtime\candidate' 'C:\runtime\candidate\.venv\Scripts\python.exe' } | Should -Throw '*overlap*'
    }
    It 'rejects production nested within candidate' {
        { Assert-DeploymentIsolation 'C:\candidate\runtime' 'C:\candidate' 'C:\candidate\.venv\Scripts\python.exe' } | Should -Throw '*overlap*'
    }
    It 'rejects a candidate venv resolving to the production venv' {
        { Assert-DeploymentIsolation 'C:\runtime' 'C:\candidate' 'C:\runtime\.venv\Scripts\python.exe' } | Should -Throw '*candidate-derived*'
    }
    It 'accepts only the explicitly candidate-derived Python' {
        { Assert-DeploymentIsolation 'C:\runtime' 'C:\candidate' 'C:\candidate\.venv\Scripts\python.exe' } | Should -Not -Throw
    }
    It 'rejects an existing reparse-point ancestor' {
        Mock Test-Path { $true }
        Mock Get-Item { [pscustomobject]@{ Attributes = [IO.FileAttributes]::ReparsePoint } }
        { Resolve-DeploymentPath 'C:\alias\candidate\.venv' } | Should -Throw '*reparse point*'
    }
    It 'fails on post-start repo-path mismatch' {
        $snapshot = New-PromotionSnapshot
        $snapshot.repo_path = 'C:\wrong'
        { Assert-DeploymentRuntime $snapshot 'C:\deployment-test\runtime' ('a' * 40) @('fetch', 'search') } | Should -Throw '*repo-path mismatch*'
    }
    It 'fails on post-start HEAD mismatch' {
        { Assert-DeploymentRuntime (New-PromotionSnapshot) 'C:\deployment-test\runtime' ('b' * 40) @('fetch', 'search') } | Should -Throw '*HEAD*'
    }
    It 'fails when runtime is not READY' {
        $snapshot = New-PromotionSnapshot
        $snapshot.status = 'DEGRADED'
        { Assert-DeploymentRuntime $snapshot 'C:\deployment-test\runtime' ('a' * 40) @('fetch', 'search') } | Should -Throw '*not READY*'
    }
    It 'requires exact tool names, including case' {
        { Assert-DeploymentToolSet @('Fetch') @('fetch') } | Should -Throw '*tool surface*'
    }
    It 'captures the expected tool delta' {
        $delta = Get-DeploymentToolDelta @('fetch', 'search') @('fetch', 'context') @('context') @('search')
        $delta.added | Should -Be @('context')
        $delta.removed | Should -Be @('search')
    }
    It 'rejects unexpected additions and removals' {
        { Get-DeploymentToolDelta @('fetch') @('fetch', 'unexpected') @() @() } | Should -Throw
        { Get-DeploymentToolDelta @('fetch', 'search') @('fetch') @() @() } | Should -Throw
    }
    It 'rejects duplicate expected delta entries' {
        { Get-DeploymentToolDelta @('fetch') @('fetch', 'search') @('search', 'search') @() } | Should -Throw
    }
}

Describe 'Promotion transaction with isolated boundary doubles' {
    BeforeEach {
        $script:events = [Collections.Generic.List[string]]::new()
        $script:head = 'a' * 40
        $script:receipt = $null
        $script:supervisorRunning = $true
        $script:parameters = @{
            RuntimeRepo = 'C:\deployment-test\runtime'; ExpectedPredecessor = ('a' * 40)
            TargetCommit = ('b' * 40); CandidateRepo = 'C:\deployment-test\candidate'; Apply = $true
        }
        Mock Assert-DeploymentClean {}
        Mock Get-DeploymentRuntime { New-PromotionSnapshot $script:head }
        Mock Get-DeploymentHead { if ($Repo -like '*candidate') { 'b' * 40 } else { $script:head } }
        Mock Get-DeploymentSupervisor { [pscustomobject]@{ task_name = 'fake'; arguments = 'fake'; execute = 'fake'; process_id = 101; created = 1 } }
        Mock Get-DeploymentVenvIdentity { 'original-venv' }
        Mock New-DeploymentCandidate { $script:events.Add('candidate') }
        Mock Invoke-DeploymentQualification { $script:events.Add('qualify') }
        Mock Get-DeploymentTools { @('fetch', 'search') }
        Mock Write-DeploymentReceipt { $script:receipt = $Receipt | ConvertTo-Json -Depth 8 | ConvertFrom-Json }
        Mock New-DeploymentRollbackRef { $script:events.Add('rollback-ref'); 'refs/byte-mcp/rollback/test' }
        Mock Suspend-DeploymentSupervisor { $script:events.Add('suspend'); $script:supervisorRunning = $false }
        Mock Suspend-DeploymentRecoverySupervisor { $script:events.Add('recovery-suspend'); $script:supervisorRunning = $false }
        Mock Assert-DeploymentSupervisorStopped { if ($script:supervisorRunning) { throw 'not quiescent' } }
        Mock Stop-DeploymentRuntime { $script:events.Add('stop') }
        Mock Set-DeploymentHead { $script:events.Add("checkout:$Target"); $script:head = $Target }
        Mock Resume-DeploymentSupervisor { $script:events.Add('resume'); $script:supervisorRunning = $true }
        Mock Wait-DeploymentRuntime { $script:events.Add("verify:$ExpectedHead"); New-PromotionSnapshot $ExpectedHead 20 }
        Mock Get-ScheduledTask { [pscustomobject]@{ State = $(if ($script:supervisorRunning) { 'Running' } else { 'Disabled' }) } }
        # These are forbidden in transaction tests, even if a seam is accidentally bypassed.
        Mock Invoke-DeploymentNative { throw 'Unexpected native/provider-capable operation in isolated transaction test.' }
    }

    It 'stops on wrong runtime path before constructing a candidate' {
        Mock Get-DeploymentRuntime { $s = New-PromotionSnapshot; $s.repo_path = 'C:\wrong'; $s }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*repo-path mismatch*'
        Should -Invoke New-DeploymentCandidate -Times 0
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
    }
    It 'stops on wrong predecessor SHA before constructing a candidate' {
        $script:head = 'c' * 40
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*HEAD*'
        Should -Invoke New-DeploymentCandidate -Times 0
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
    }
    It 'stops on dirty production without attempting cleanup' {
        Mock Assert-DeploymentClean { throw 'Production/worktree is dirty' }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*dirty*'
        Should -Invoke New-DeploymentCandidate -Times 0
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
    }
    It 'stops on non-READY runtime' {
        Mock Get-DeploymentRuntime { $s = New-PromotionSnapshot; $s.status = 'DEGRADED'; $s }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*not READY*'
        Should -Invoke New-DeploymentCandidate -Times 0
    }
    It 'leaves production untouched on candidate qualification failure' {
        Mock Invoke-DeploymentQualification { throw 'Ruff gate failed' }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*Ruff*'
        Should -Invoke New-DeploymentRollbackRef -Times 0
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
        Should -Invoke Stop-DeploymentRuntime -Times 0
        Should -Invoke Set-DeploymentHead -Times 0
    }
    It 'leaves production untouched on unexpected tool delta' {
        Mock Get-DeploymentTools { @('fetch', 'search', 'unexpected') }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*tool surface*'
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
        Should -Invoke Set-DeploymentHead -Times 0
    }
    It 'defaults to qualification only without explicit Apply' {
        $parameters.Remove('Apply')
        $result = Invoke-ByteMcpPromotion @parameters
        $result.result | Should -Be 'QUALIFIED_ONLY'
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
        Should -Invoke New-DeploymentRollbackRef -Times 0
    }
    It 'orders qualification and rollback ref before mutation and restores supervisor after success' {
        $result = Invoke-ByteMcpPromotion @parameters
        $result.result | Should -Be 'PROMOTED'
        $script:events[0..4] | Should -Be @('candidate', 'qualify', 'rollback-ref', 'suspend', 'stop')
        $script:head | Should -Be ('b' * 40)
        $script:supervisorRunning | Should -BeTrue
        Should -Invoke Resume-DeploymentSupervisor -Times 2 -Exactly
        Should -Invoke Invoke-DeploymentNative -Times 0
    }
    It 'automatically restores predecessor on failed candidate startup' {
        Mock Wait-DeploymentRuntime {
            if ($ExpectedHead -eq ('b' * 40)) { throw 'startup failed' }
            New-PromotionSnapshot $ExpectedHead 30
        }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*outcome=ROLLED_BACK*'
        $script:head | Should -Be ('a' * 40)
        $script:receipt.result | Should -Be 'ROLLED_BACK'
        $script:receipt.rollback.status | Should -Be 'READY'
        $script:supervisorRunning | Should -BeTrue
        Should -Invoke Set-DeploymentHead -Times 1 -ParameterFilter { $Target -eq ('a' * 40) }
    }
    It 'rolls back a post-start repo-path or HEAD verification failure' -ForEach @('repo-path mismatch', 'HEAD mismatch') {
        Mock Wait-DeploymentRuntime {
            if ($ExpectedHead -eq ('b' * 40)) { throw 'post-start identity mismatch' }
            New-PromotionSnapshot $ExpectedHead 30
        }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*ROLLED_BACK*'
        $script:head | Should -Be ('a' * 40)
        $script:supervisorRunning | Should -BeTrue
    }
    It 'restores supervisor after partially failed suspension' {
        Mock Suspend-DeploymentSupervisor { $script:supervisorRunning = $false; throw 'partial suspension' }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*FAILED_BEFORE_CHECKOUT*'
        $script:supervisorRunning | Should -BeTrue
        Should -Invoke Set-DeploymentHead -Times 0
        Should -Invoke Wait-DeploymentRuntime -Times 1 -ParameterFilter { $ExpectedHead -eq ('a' * 40) }
    }
    It 'reports rollback failure without claiming predecessor READY' {
        Mock Wait-DeploymentRuntime { throw 'runtime unavailable' }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*ROLLBACK_NOT_READY*'
        $script:receipt.result | Should -Be 'ROLLBACK_NOT_READY'
        $script:supervisorRunning | Should -BeTrue
    }
    It 'refuses to overwrite unexpected lineage during rollback' {
        Mock Wait-DeploymentRuntime { $script:head = 'c' * 40; throw 'external checkout change' }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*ROLLBACK_NOT_READY*'
        Should -Invoke Set-DeploymentHead -Times 0 -ParameterFilter { $Target -eq ('a' * 40) }
    }
    It 'fails before mutation if production venv changed during qualification' {
        Mock Get-DeploymentVenvIdentity { if ($script:events.Contains('qualify')) { 'changed' } else { 'original-venv' } }
        { Invoke-ByteMcpPromotion @parameters } | Should -Throw '*venv changed*'
        Should -Invoke Suspend-DeploymentSupervisor -Times 0
    }
}

Describe 'Real Git promotion preserves a production environment' {
    It 'checks out and rolls back code without recreating or changing venv files' {
        $repo = Join-Path $TestDrive 'runtime'
        New-Item -ItemType Directory -Path $repo | Out-Null
        Invoke-DeploymentNative git @('init', '--quiet', $repo)
        Set-Content -LiteralPath (Join-Path $repo '.gitignore') -Value '.venv/'
        Set-Content -LiteralPath (Join-Path $repo 'code.txt') -Value 'predecessor'
        Invoke-DeploymentGit $repo @('add', '.')
        Invoke-DeploymentGit $repo @('-c', 'user.name=Deployment Test', '-c', 'user.email=deployment-test@example.invalid', 'commit', '--quiet', '-m', 'predecessor')
        $before = Get-DeploymentHead $repo
        Set-Content -LiteralPath (Join-Path $repo 'code.txt') -Value 'candidate'
        Invoke-DeploymentGit $repo @('add', 'code.txt')
        Invoke-DeploymentGit $repo @('-c', 'user.name=Deployment Test', '-c', 'user.email=deployment-test@example.invalid', 'commit', '--quiet', '-m', 'candidate')
        $target = Get-DeploymentHead $repo
        Set-DeploymentHead $repo $target $before
        New-Item -ItemType Directory -Path (Join-Path $repo '.venv\Scripts') | Out-Null
        Set-Content -LiteralPath (Join-Path $repo '.venv\Scripts\python.exe') -Value 'protected-test-marker'
        Set-Content -LiteralPath (Join-Path $repo '.venv\pyvenv.cfg') -Value 'protected-config-marker'
        $venv = Get-DeploymentVenvIdentity $repo
        $rollbackRef = New-DeploymentRollbackRef $repo $before
        Set-DeploymentHead $repo $before $target
        Get-Content -LiteralPath (Join-Path $repo 'code.txt') | Should -Be 'candidate'
        Set-DeploymentHead $repo $target $before
        Get-Content -LiteralPath (Join-Path $repo 'code.txt') | Should -Be 'predecessor'
        Get-DeploymentVenvIdentity $repo | Should -BeExactly $venv
        (Invoke-DeploymentGit $repo @('rev-parse', $rollbackRef)).Trim() | Should -Be $before
        { Assert-DeploymentClean $repo } | Should -Not -Throw
    }
}

Describe 'Explicit deployment context boundary' {
    BeforeAll {
        $script:productionRuntime = 'C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon'
        $script:productionState = Join-Path $env:USERPROFILE '.byte-mcp'
    }

    It 'accepts explicit runtime, state root, ports, and supervisor configuration' {
        $context = New-DeploymentContext `
            -RuntimeRepo 'C:\rehearsal\daemon' `
            -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 18080 `
            -SupervisorKind 'LocalProcess' `
            -SupervisorName 'rehearsal-supervisor'

        $context.RuntimeRepo | Should -Be 'C:\rehearsal\daemon'
        $context.StateRoot | Should -Be 'C:\rehearsal\state'
        $context.LauncherStatePath | Should -Be 'C:\rehearsal\state\runtime\launcher-state.json'
        $context.McpPort | Should -Be 18000
        $context.TunnelPort | Should -Be 18080
        $context.SupervisorKind | Should -Be 'LocalProcess'
        $context.SupervisorName | Should -Be 'rehearsal-supervisor'
    }

    It 'preserves production defaults at the explicit production boundary' {
        $context = New-DeploymentContext -RuntimeRepo $productionRuntime

        $context.StateRoot | Should -Be $productionState
        $context.LauncherStatePath | Should -Be (Join-Path $productionState 'runtime\launcher-state.json')
        $context.McpPort | Should -Be 8000
        $context.TunnelPort | Should -Be 8080
        $context.SupervisorKind | Should -Be 'ScheduledTask'
        $context.SupervisorName | Should -Be 'Byte-MCP Daemon'
    }

    It 'rejects disposable state equal to production state' {
        { New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot $productionState `
            -McpPort 18000 -TunnelPort 18080 -SupervisorKind LocalProcess -Mode Disposable } |
            Should -Throw '*production state root*'
    }

    It 'rejects disposable runtime equal to production runtime' {
        { New-DeploymentContext -RuntimeRepo $productionRuntime -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 18080 -SupervisorKind LocalProcess -Mode Disposable } |
            Should -Throw '*production runtime*'
    }

    It 'rejects disposable production ports' {
        { New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot 'C:\rehearsal\state' `
            -McpPort 8000 -TunnelPort 18080 -SupervisorKind LocalProcess -Mode Disposable } |
            Should -Throw '*MCP port*'
        { New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 8080 -SupervisorKind LocalProcess -Mode Disposable } |
            Should -Throw '*tunnel port*'
    }

    It 'rejects disposable scheduled-task supervision and the production task name' {
        { New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 18080 -SupervisorKind ScheduledTask -Mode Disposable } |
            Should -Throw '*scheduled task*'
        { New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 18080 -SupervisorKind LocalProcess `
            -SupervisorName 'Byte-MCP Daemon' -Mode Disposable } |
            Should -Throw '*supervisor*'
    }

    It 'rejects production mode that silently points at rehearsal infrastructure' {
        { New-DeploymentContext -RuntimeRepo $productionRuntime -StateRoot 'C:\rehearsal\state' `
            -McpPort 8000 -TunnelPort 8080 -SupervisorKind ScheduledTask -Mode Production } |
            Should -Throw '*production state root*'
        { New-DeploymentContext -RuntimeRepo $productionRuntime -StateRoot $productionState `
            -McpPort 18000 -TunnelPort 8080 -SupervisorKind ScheduledTask -Mode Production } |
            Should -Throw '*MCP port*'
    }

    It 'exposes a real local supervisor implementation without scheduled-task APIs' {
        $context = New-DeploymentContext -RuntimeRepo 'C:\rehearsal\daemon' -StateRoot 'C:\rehearsal\state' `
            -McpPort 18000 -TunnelPort 18080 -SupervisorKind LocalProcess -Mode Disposable
        $supervisor = New-DeploymentSupervisor -Context $context

        $supervisor.Kind | Should -Be 'LocalProcess'
        $supervisor.StatePath | Should -Be 'C:\rehearsal\state\supervisor.json'
        $supervisor.PSObject.Methods.Name | Should -Contain 'Inspect'
        $supervisor.PSObject.Methods.Name | Should -Contain 'Suspend'
        $supervisor.PSObject.Methods.Name | Should -Contain 'Resume'
    }
}
