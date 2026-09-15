Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')

function Resolve-DeploymentPath {
    param([Parameter(Mandatory)][string] $Path)
    # Reject aliases rather than trying to reason about junctions, UNC, or 8.3 names.
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path -match '[~*?]' -or
        $Path.Substring(2).Contains(':')) { throw "Deployment requires an absolute local path: $Path" }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Deployment path contains a reparse point: $cursor"
            }
        }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    $full
}

function Test-DeploymentPathWithin {
    param([string] $Path, [string] $Root)
    $Path.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-DeploymentIsolation {
    param([string] $RuntimeRepo, [string] $CandidateRepo, [string] $PythonPath)
    $runtime = Resolve-DeploymentPath $RuntimeRepo
    $candidate = Resolve-DeploymentPath $CandidateRepo
    $python = Resolve-DeploymentPath $PythonPath
    if ((Test-DeploymentPathWithin $candidate $runtime) -or
        (Test-DeploymentPathWithin $runtime $candidate)) { throw 'Candidate and production paths overlap.' }
    $expected = Resolve-DeploymentPath (Join-Path $candidate '.venv\Scripts\python.exe')
    if ($python -ine $expected) { throw 'Qualification Python must be candidate-derived .venv\Scripts\python.exe.' }
    if (Test-DeploymentPathWithin $python $runtime) { throw 'Qualification Python resolves inside production.' }
}

function New-DeploymentContext {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $RuntimeRepo,
        [string] $StateRoot = (Join-Path $env:USERPROFILE '.byte-mcp'),
        [ValidateRange(1024, 65535)][int] $McpPort = 8000,
        [ValidateRange(1024, 65535)][int] $TunnelPort = 8080,
        [ValidateSet('ScheduledTask', 'LocalProcess')][string] $SupervisorKind = 'ScheduledTask',
        [string] $SupervisorName = 'Byte-MCP Daemon',
        [ValidateSet('Production', 'Disposable')][string] $Mode = 'Production',
        [string] $BaselineFailureFile
    )

    $runtime = Resolve-DeploymentPath $RuntimeRepo
    $state = Resolve-DeploymentPath $StateRoot
    $productionRuntime = Resolve-DeploymentPath 'C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon'
    $productionState = Resolve-DeploymentPath (Join-Path $env:USERPROFILE '.byte-mcp')

    $inferredDisposable = $false
    if ($SupervisorKind -eq 'LocalProcess' -and $SupervisorName -ieq 'Byte-MCP Daemon' -and
        -not $PSBoundParameters.ContainsKey('SupervisorName')) { $SupervisorName = 'rehearsal-supervisor' }
    if ($Mode -eq 'Production' -and $SupervisorKind -eq 'LocalProcess') {
        $Mode = 'Disposable'
        $inferredDisposable = $true
        if ($SupervisorKind -eq 'LocalProcess' -and $SupervisorName -ieq 'Byte-MCP Daemon') { $SupervisorName = 'rehearsal-supervisor' }
    }
    if ($Mode -eq 'Disposable') {
        if ($runtime -ieq $productionRuntime) { throw 'Disposable context cannot use the production runtime.' }
        if ($state -ieq $productionState) { throw 'Disposable context cannot use the production state root.' }
        if ($McpPort -eq 8000) { throw 'Disposable context cannot use the production MCP port.' }
        if ($TunnelPort -eq 8080) { throw 'Disposable context cannot use the production tunnel port.' }
        if ($SupervisorKind -eq 'ScheduledTask') { throw 'Disposable context cannot use a scheduled task supervisor.' }
        if ($SupervisorName -ieq 'Byte-MCP Daemon') { throw 'Disposable context cannot use the production supervisor.' }
    }
    else {
        if ($runtime -ine $productionRuntime) { throw 'Production context must use the production runtime.' }
        if ($state -ine $productionState) { throw 'Production context cannot use a non-production state root.' }
        if ($McpPort -ne 8000) { throw 'Production context must use the production MCP port.' }
        if ($TunnelPort -ne 8080) { throw 'Production context must use the production tunnel port.' }
        if ($SupervisorKind -ne 'ScheduledTask' -or $SupervisorName -cne 'Byte-MCP Daemon') {
            throw 'Production context must use the production scheduled-task supervisor.'
        }
    }

    [pscustomobject]@{
        Mode = $Mode
        RuntimeRepo = $runtime
        StateRoot = $state
        LauncherStatePath = Join-Path $state 'runtime\launcher-state.json'
        McpPort = $McpPort
        TunnelPort = $TunnelPort
        SupervisorKind = $SupervisorKind
        SupervisorName = $SupervisorName
        BaselineFailureFile = $BaselineFailureFile
        Supervisor = $null
    }
}

function Get-DeploymentContext {
    param([string] $RuntimeRepo, [pscustomobject] $Context)
    if ($null -ne $Context) { return $Context }
    $resolved = Resolve-DeploymentPath $RuntimeRepo
    $production = Resolve-DeploymentPath 'C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon'
    if ($resolved -ieq $production) { return New-DeploymentContext -RuntimeRepo $resolved }
    [pscustomobject]@{
        Mode = 'Legacy'; RuntimeRepo = $resolved; StateRoot = Resolve-DeploymentPath (Join-Path $env:USERPROFILE '.byte-mcp')
        LauncherStatePath = Join-Path (Resolve-DeploymentPath (Join-Path $env:USERPROFILE '.byte-mcp')) 'runtime\launcher-state.json'
        McpPort = 8000; TunnelPort = 8080; SupervisorKind = 'ScheduledTask'; SupervisorName = 'Byte-MCP Daemon'
        BaselineFailureFile = $null; Supervisor = $null
    }
}

function Invoke-DeploymentNative {
    param([string] $FilePath, [string[]] $Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Native deployment gate failed: $FilePath (exit $LASTEXITCODE)" }
}

function Invoke-DeploymentGit {
    param([string] $Repo, [string[]] $Arguments)
    Invoke-DeploymentNative 'git' (@('-C', $Repo) + $Arguments)
}

function Get-DeploymentHead {
    param([string] $Repo)
    (Invoke-DeploymentGit $Repo @('rev-parse', '--verify', 'HEAD')).Trim()
}

function Assert-DeploymentClean {
    param([string] $Repo)
    $root = Resolve-DeploymentPath ((Invoke-DeploymentGit $Repo @('rev-parse', '--show-toplevel')).Trim())
    if ($root -ine (Resolve-DeploymentPath $Repo)) { throw 'Runtime path must be the exact Git checkout root.' }
    $dirty = @(Invoke-DeploymentGit $Repo @('status', '--porcelain=v1', '--untracked-files=all'))
    if ($dirty.Count) { throw "Production/worktree is dirty; no automatic cleanup is permitted: $($dirty -join '; ')" }
}

function Get-DeploymentVenvIdentity {
    param([string] $RuntimeRepo)
    $venv = Resolve-DeploymentPath (Join-Path $RuntimeRepo '.venv')
    $python = Resolve-DeploymentPath (Join-Path $venv 'Scripts\python.exe')
    $config = Resolve-DeploymentPath (Join-Path $venv 'pyvenv.cfg')
    [ordered]@{
        path = $venv
        created = (Get-Item -LiteralPath $venv).CreationTimeUtc.Ticks
        python_hash = (Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash
        config_hash = (Get-FileHash -LiteralPath $config -Algorithm SHA256).Hash
    } | ConvertTo-Json -Compress
}

function Get-DeploymentTools {
    param([string] $Repo, [string] $PythonPath, [switch] $Live, [pscustomobject] $Context)
    $arguments = @('-B', (Join-Path $PSScriptRoot 'deployment_probe.py'), '--repo', $Repo)
    if ($Live) {
        $arguments += '--live'
        if ($null -ne $Context) { $arguments += @('--live-url', "http://127.0.0.1:$($Context.McpPort)/mcp") }
    }
    $result = (Invoke-DeploymentNative $PythonPath $arguments) | ConvertFrom-Json
    if ((Resolve-DeploymentPath $result.repo_path) -ine (Resolve-DeploymentPath $Repo)) {
        throw 'Tool probe repository identity mismatch.'
    }
    $names = @($result.tools)
    if ($names.Count -eq 0 -or $names.Count -ne $result.tool_count -or
        @($names | Sort-Object -Unique).Count -ne $names.Count) { throw 'Malformed tool surface.' }
    foreach ($name in $names) {
        if ($name -isnot [string] -or $name -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Malformed tool name.' }
    }
    $names | Sort-Object -CaseSensitive
}

function Assert-DeploymentToolSet {
    param([string[]] $Actual, [string[]] $Expected)
    if (($Actual | Sort-Object -CaseSensitive | ConvertTo-Json -Compress) -cne
        ($Expected | Sort-Object -CaseSensitive | ConvertTo-Json -Compress)) {
        throw "Unexpected tool surface. Expected=[$($Expected -join ',')]; Actual=[$($Actual -join ',')]"
    }
}

function Get-DeploymentToolDelta {
    param([string[]] $Before, [string[]] $Candidate, [string[]] $ExpectedAdded, [string[]] $ExpectedRemoved)
    $added = @($Candidate | Where-Object { $Before -cnotcontains $_ })
    $removed = @($Before | Where-Object { $Candidate -cnotcontains $_ })
    Assert-DeploymentToolSet $added @($ExpectedAdded)
    Assert-DeploymentToolSet $removed @($ExpectedRemoved)
    [pscustomobject]@{ before = @($Before); candidate = @($Candidate); added = $added; removed = $removed }
}

function Get-DeploymentRuntime {
    param([string] $RuntimeRepo, [pscustomobject] $Context)
    $context = Get-DeploymentContext $RuntimeRepo $Context
    $state = Read-LauncherState -Path $context.LauncherStatePath
    if ((Resolve-DeploymentPath $state.repo_path) -ine $context.RuntimeRepo) {
        throw 'Managed launcher repo_path differs from the explicit runtime path.'
    }
    $serverProcess = $false
    $tunnelProcess = $false
    foreach ($role in @('server', 'tunnel')) {
        $record = $state.$role
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
        if ($null -ne $process -and (Test-LauncherProcessIdentity -Record $record -Process $process)) {
            if ($role -eq 'server') { $serverProcess = $true } else { $tunnelProcess = $true }
        }
    }
    $mcp = (Invoke-LauncherHttpProbe -Uri "http://127.0.0.1:$($context.McpPort)/mcp").reachable
    $tunnelHealth = Invoke-LauncherHttpProbe -Uri "http://127.0.0.1:$($context.TunnelPort)/healthz"
    $tunnelReady = Invoke-LauncherHttpProbe -Uri "http://127.0.0.1:$($context.TunnelPort)/readyz"
    $ready = $serverProcess -and $tunnelProcess -and $mcp -and
        $tunnelHealth.status_code -eq 200 -and $tunnelHealth.body -eq 'live' -and
        $tunnelReady.status_code -eq 200 -and $tunnelReady.body -eq 'ready'
    if (-not $ready) { throw 'Deployment runtime is not READY.' }
    $listeners = @(Get-NetTCPConnection -LocalPort $context.McpPort -State Listen -ErrorAction Stop |
        Where-Object LocalAddress -EQ '127.0.0.1' | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($listeners.Count -ne 1 -or $listeners[0] -ne $state.server.pid) {
        throw 'Live MCP listener does not belong to the recorded managed server.'
    }
    [pscustomobject]@{
        repo_path = $state.repo_path
        head = Get-DeploymentHead $context.RuntimeRepo
        status = if ($ready) { 'READY' } else { 'DEGRADED' }
        server_pid = $state.server.pid
        server_started = $state.server.started_at_utc
        tools = @(Get-DeploymentTools $context.RuntimeRepo (Join-Path $context.RuntimeRepo '.venv\Scripts\python.exe') -Live -Context $context)
    }
}

function Assert-DeploymentRuntime {
    param($Snapshot, [string] $RuntimeRepo, [string] $ExpectedHead, [string[]] $ExpectedTools)
    if ((Resolve-DeploymentPath $Snapshot.repo_path) -ine (Resolve-DeploymentPath $RuntimeRepo)) {
        throw 'Post-start runtime repo-path mismatch.'
    }
    if ($Snapshot.head -cne $ExpectedHead) { throw 'Runtime HEAD differs from expected predecessor/target SHA.' }
    if ($Snapshot.status -cne 'READY') { throw 'Runtime is not READY.' }
    Assert-DeploymentToolSet @($Snapshot.tools) $ExpectedTools
}

function Get-LocalSupervisorInspection {
    param([pscustomobject] $Context)
    $statePath = Join-Path $Context.StateRoot 'supervisor.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw 'Local rehearsal supervisor state is absent.' }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.pid)" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        $scriptPath = [regex]::Escape((Join-Path $PSScriptRoot 'RehearsalSupervisor.ps1'))
        $matches = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -and $_.CommandLine -match $scriptPath -and
            $_.CommandLine -match [regex]::Escape($Context.RuntimeRepo)
        })
        if ($matches.Count -eq 1) {
            $process = $matches[0]
            $state.pid = [int]$process.ProcessId
            $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
        }
    }
    if ($null -eq $process -or -not $process.CommandLine -or
        $process.CommandLine -notmatch [regex]::Escape((Join-Path $PSScriptRoot 'RehearsalSupervisor.ps1'))) {
        throw 'Local rehearsal supervisor process is not running.'
    }
    [pscustomobject]@{
        kind = 'LocalProcess'; task_name = $Context.SupervisorName; process_id = [int]$state.pid
        created = $process.CreationDate; arguments = $process.CommandLine
        execute = $process.Name; state_path = $statePath; Context = $Context
    }
}

function New-DeploymentSupervisor {
    param([Parameter(Mandatory)][pscustomobject] $Context)
    $supervisor = [pscustomobject]@{
        Kind = $Context.SupervisorKind; Name = $Context.SupervisorName
        StatePath = if ($Context.SupervisorKind -eq 'LocalProcess') { Join-Path $Context.StateRoot 'supervisor.json' } else { $null }
        Context = $Context
    }
    $supervisor | Add-Member ScriptMethod Inspect { Get-LocalSupervisorInspection -Context $this.Context }
    $supervisor | Add-Member ScriptMethod Suspend { Suspend-LocalDeploymentSupervisor -Supervisor (Get-LocalSupervisorInspection -Context $this.Context) }
    $supervisor | Add-Member ScriptMethod Resume { Resume-LocalDeploymentSupervisor -Context $this.Context }
    $supervisor
}

function Start-LocalDeploymentSupervisor {
    param([Parameter(Mandatory)][pscustomobject] $Context)
    New-Item -ItemType Directory -Force -Path $Context.StateRoot | Out-Null
    $python = Join-Path $Context.RuntimeRepo '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Rehearsal runtime Python is missing: $python" }
    $pwsh = @((Get-Command pwsh -CommandType Application -ErrorAction Stop).Source)[0]
    $script = Join-Path $PSScriptRoot 'RehearsalSupervisor.ps1'
    $arguments = @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$script,
        '-RuntimeRepo',$Context.RuntimeRepo,'-StateRoot',$Context.StateRoot,'-PythonPath',$python,
        '-McpPort',[string]$Context.McpPort,'-TunnelPort',[string]$Context.TunnelPort)
    Start-Process -FilePath $pwsh -ArgumentList $arguments -WindowStyle Hidden | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        try { return (Get-LocalSupervisorInspection -Context $Context) }
        catch { if ([DateTime]::UtcNow -ge $deadline) { throw }; Start-Sleep -Milliseconds 250 }
    } while ($true)
}

function Suspend-LocalDeploymentSupervisor {
    param([Parameter(Mandatory)]$Supervisor)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Supervisor.process_id)" -ErrorAction Stop
    if ($null -eq $process -or $process.CreationDate -ne $Supervisor.created -or
        $process.CommandLine -cne $Supervisor.arguments) { throw 'Local supervisor identity changed.' }
    Stop-Process -Id $Supervisor.process_id -ErrorAction Stop
    Wait-Process -Id $Supervisor.process_id -Timeout 15 -ErrorAction SilentlyContinue
    if (Get-Process -Id $Supervisor.process_id -ErrorAction SilentlyContinue) { throw 'Local supervisor did not stop.' }
}

function Resume-LocalDeploymentSupervisor {
    param([Parameter(Mandatory)][pscustomobject] $Context)
    Start-LocalDeploymentSupervisor -Context $Context
}

function Get-DeploymentSupervisor {
    param([string] $RuntimeRepo, [string] $TaskName, [pscustomobject] $Context)
    $context = Get-DeploymentContext $RuntimeRepo $Context
    if ($context.SupervisorKind -eq 'LocalProcess') { return Get-LocalSupervisorInspection -Context $context }
    $TaskName = $context.SupervisorName
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop
    if (-not $task.Settings.Enabled -or [string]$task.State -ne 'Running') {
        throw 'Managed supervisor task must be enabled and running before promotion.'
    }
    $actions = @($task.Actions)
    if ($actions.Count -ne 1) { throw 'Expected exactly one managed supervisor action.' }
    $arguments = [string]$actions[0].Arguments
    $match = [regex]::Match($arguments, '(?i)(?:^|\s)-RuntimeRepo\s+"([^"]+)"(?:\s|$)')
    if (-not $match.Success -or
        (Resolve-DeploymentPath $match.Groups[1].Value) -ine (Resolve-DeploymentPath $RuntimeRepo)) {
        throw 'Supervisor RuntimeRepo differs from the explicit runtime path.'
    }
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -in @('pwsh.exe', 'powershell.exe') -and $_.CommandLine -and
        $_.CommandLine.EndsWith($arguments, [StringComparison]::Ordinal)
    })
    if ($processes.Count -ne 1) { throw 'Cannot establish unique managed supervisor process identity.' }
    [pscustomobject]@{
        kind = 'ScheduledTask'; task_name = $TaskName; arguments = $arguments; execute = $actions[0].Execute
        process_id = $processes[0].ProcessId; created = $processes[0].CreationDate; Context = $context
    }
}

function Suspend-DeploymentSupervisor {
    param($Supervisor)
    if ($Supervisor.kind -eq 'LocalProcess') { Suspend-LocalDeploymentSupervisor -Supervisor $Supervisor; return }
    Disable-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop | Out-Null
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Supervisor.process_id)" -ErrorAction Stop
    if ($null -eq $process -or $process.CreationDate -ne $Supervisor.created -or
        -not $process.CommandLine.EndsWith($Supervisor.arguments, [StringComparison]::Ordinal)) {
        throw 'Supervisor process identity changed before suspension.'
    }
    # Kill only the verified supervisor, retaining the managed children for launcher shutdown.
    Stop-Process -Id $Supervisor.process_id -ErrorAction Stop
    Wait-Process -Id $Supervisor.process_id -Timeout 15 -ErrorAction SilentlyContinue
    $deadline = [datetime]::UtcNow.AddSeconds(15)
    do {
        try { Assert-DeploymentSupervisorStopped $Supervisor; return }
        catch { if ([datetime]::UtcNow -ge $deadline) { throw }; Start-Sleep -Milliseconds 200 }
    } while ($true)
}

function Suspend-DeploymentRecoverySupervisor {
    param([string] $RuntimeRepo, $Supervisor)
    if ($Supervisor.kind -eq 'LocalProcess') {
        if (Get-CimInstance Win32_Process -Filter "ProcessId = $($Supervisor.process_id)" -ErrorAction SilentlyContinue) {
            Suspend-DeploymentSupervisor $Supervisor
        }
        return
    }
    $task = Get-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -cne $Supervisor.arguments -or
        $task.Actions[0].Execute -cne $Supervisor.execute) { throw 'Supervisor task action changed before rollback.' }
    if ([string]$task.State -eq 'Running') {
        Suspend-DeploymentSupervisor (Get-DeploymentSupervisor $RuntimeRepo $Supervisor.task_name)
    }
    else {
        # Startup may have failed before the supervisor became a running process.
        Disable-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop | Out-Null
        Assert-DeploymentSupervisorStopped $Supervisor
    }
}

function Assert-DeploymentSupervisorStopped {
    param($Supervisor)
    if ($Supervisor.kind -eq 'LocalProcess') {
        if (Get-CimInstance Win32_Process -Filter "ProcessId = $($Supervisor.process_id)" -ErrorAction SilentlyContinue) {
            throw 'Local rehearsal supervisor is not quiescent.'
        }
        return
    }
    $task = Get-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -and $_.CommandLine.EndsWith($Supervisor.arguments, [StringComparison]::Ordinal)
    })
    if ($task.Settings.Enabled -or [string]$task.State -eq 'Running' -or $processes.Count) {
        throw 'Supervisor is not quiescent; refusing live checkout mutation.'
    }
}

function Resume-DeploymentSupervisor {
    param($Supervisor)
    if ($Supervisor.kind -eq 'LocalProcess') { Resume-LocalDeploymentSupervisor -Context $Supervisor.Context | Out-Null; return }
    $task = Get-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -cne $Supervisor.arguments -or
        $task.Actions[0].Execute -cne $Supervisor.execute) { throw 'Supervisor task action changed during promotion.' }
    $existing = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -in @('pwsh.exe', 'powershell.exe') -and $_.CommandLine -and
        $_.CommandLine.EndsWith($Supervisor.arguments, [StringComparison]::Ordinal)
    })
    if ($existing.Count -gt 1) { throw 'Multiple managed supervisor processes exist during restoration.' }
    Enable-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop | Out-Null
    if ($existing.Count -eq 0) {
        Start-ScheduledTask -TaskName $Supervisor.task_name -TaskPath '\' -ErrorAction Stop
    }
    $deadline = [datetime]::UtcNow.AddSeconds(15)
    do {
        $running = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.Name -in @('pwsh.exe', 'powershell.exe') -and $_.CommandLine -and
            $_.CommandLine.EndsWith($Supervisor.arguments, [StringComparison]::Ordinal)
        })
        if ($running.Count -eq 1) { return }
        if ([datetime]::UtcNow -ge $deadline) { throw 'Supervisor did not restore to a unique running process.' }
        Start-Sleep -Milliseconds 200
    } while ($true)
}

function Stop-DeploymentRuntime {
    param([string] $RuntimeRepo, [pscustomobject] $Context)
    $context = Get-DeploymentContext $RuntimeRepo $Context
    $statePath = $context.LauncherStatePath
    if (-not (Test-Path -LiteralPath $statePath)) {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in @($context.McpPort, $context.TunnelPort) })
        if ($listeners.Count) { throw 'Listeners exist without managed launcher state.' }
        return
    }
    $stateHash = (Get-FileHash -LiteralPath $statePath).Hash
    $state = Read-LauncherState $statePath
    if ((Resolve-DeploymentPath $state.repo_path) -ine $context.RuntimeRepo) {
        throw 'Refusing shutdown of another managed checkout.'
    }
    # Validate every surviving process before stopping any; dead startup components are allowed.
    $owned = @()
    foreach ($role in @('tunnel', 'server')) {
        $record = $state.$role
        $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            if (-not (Test-LauncherProcessIdentity -Record $record -Process $process)) {
                throw "Refusing shutdown of unverified $role process."
            }
            $owned += $process.Id
        }
    }
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -in @($context.McpPort, $context.TunnelPort) })
    $unknownListeners = @($listeners | Where-Object {
        $_.OwningProcess -notin $owned -and
        -not ($context.SupervisorKind -eq 'LocalProcess' -and $_.LocalPort -eq $context.TunnelPort -and $_.OwningProcess -eq 4)
    })
    if ($unknownListeners.Count) {
        throw 'Unknown process owns a managed listener; refusing shutdown.'
    }
    foreach ($processId in $owned) {
        $record = @($state.tunnel, $state.server) | Where-Object pid -EQ $processId
        $process = Get-Process -Id $processId -ErrorAction Stop
        if (-not (Test-LauncherProcessIdentity -Record $record -Process $process)) {
            throw 'Managed process identity changed during shutdown.'
        }
        Stop-Process -Id $processId -ErrorAction Stop
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
    $remaining = @()
    $listenerDeadline = [datetime]::UtcNow.AddSeconds(10)
    do {
        $remaining = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in @($context.McpPort, $context.TunnelPort) })
        if (-not $remaining -or [datetime]::UtcNow -ge $listenerDeadline) { break }
        Start-Sleep -Milliseconds 200
    } while ($true)
    if ($remaining.Count) { throw 'Managed listeners failed to stop.' }
    if ((Get-FileHash -LiteralPath $statePath).Hash -cne $stateHash) {
        throw 'Launcher state changed during shutdown; preserving it.'
    }
    Remove-Item -LiteralPath $statePath -ErrorAction Stop
}

function Wait-DeploymentRuntime {
    param([string] $RuntimeRepo, [pscustomobject] $Context, [string] $ExpectedHead, [string[]] $ExpectedTools,
        [string] $TaskName, [int] $TimeoutSeconds = 90)
    $context = Get-DeploymentContext $RuntimeRepo $Context
    $deadline = [datetime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastFailure = 'No runtime evidence.'
    do {
        try {
             $snapshot = Get-DeploymentRuntime -RuntimeRepo $context.RuntimeRepo -Context $context
            Assert-DeploymentRuntime $snapshot $context.RuntimeRepo $ExpectedHead $ExpectedTools
            $null = Get-DeploymentSupervisor -Context $context
            return $snapshot
        }
        catch { $lastFailure = $_.Exception.Message }
        Start-Sleep -Seconds 1
    } while ([datetime]::UtcNow -lt $deadline)
    throw "Managed runtime did not reach the expected healthy state: $lastFailure"
}

function New-DeploymentCandidate {
    param([string] $RuntimeRepo, [string] $CandidateRepo, [string] $Predecessor, [string] $Target)
    if (Test-Path -LiteralPath $CandidateRepo) { throw 'Candidate directory must not already exist.' }
    # Explicit ancestry and environment compatibility; normal code promotions never install into production.
    Invoke-DeploymentGit $RuntimeRepo @('merge-base', '--is-ancestor', $Predecessor, $Target)
    $changed = @(Invoke-DeploymentGit $RuntimeRepo @('diff', '--name-only', $Predecessor, $Target))
    if (@($changed | Where-Object {
        $_ -match '(^|/)(pyproject\.toml|.*lock|requirements[^/]*|setup\.(py|cfg)|\.venv)(/|$)'
    }).Count) { throw 'Dependency/environment changes require a separate runtime migration.' }
    $tracked = @(Invoke-DeploymentGit $RuntimeRepo @('ls-tree', '-r', '--name-only', $Target))
    if (@($tracked | Where-Object { $_ -imatch '^\.venv(/|$)' }).Count) { throw 'Target tracks the protected production venv.' }
    Invoke-DeploymentGit $RuntimeRepo @('worktree', 'add', '--detach', $CandidateRepo, $Predecessor)
    Invoke-DeploymentGit $CandidateRepo @('checkout', '--no-overwrite-ignore', '--detach', $Target)
}

function Invoke-DeploymentQualification {
    param([string] $RuntimeRepo, [string] $CandidateRepo, [string] $PythonPath, [pscustomobject] $Context)
    Assert-DeploymentIsolation $RuntimeRepo $CandidateRepo $PythonPath
    if (Test-Path -LiteralPath (Join-Path $CandidateRepo '.venv')) {
        throw 'New candidate must not contain an existing virtual environment.'
    }
    $venv = Resolve-DeploymentPath (Join-Path $CandidateRepo '.venv')
    Invoke-DeploymentNative 'uv' @('venv', '--python', '3.12', '--seed', $venv)
    Assert-DeploymentIsolation $RuntimeRepo $CandidateRepo $PythonPath
    Invoke-DeploymentNative 'uv' @('pip', 'install', '--python', $PythonPath, '-e', "$CandidateRepo`[dev`]")
    # Use this reviewed gate, not an arbitrary candidate-supplied replacement.
    $check = @{ RepoRoot = $CandidateRepo; PythonPath = $PythonPath; ProductionRepo = $RuntimeRepo }
    if ($null -ne $Context) {
        $check.StateRoot = $Context.StateRoot
        $check.BaselineFailureFile = $Context.BaselineFailureFile
        $check.McpPort = $Context.McpPort
        $check.TunnelPort = $Context.TunnelPort
        $check.SupervisorName = $Context.SupervisorName
    }
    & (Join-Path $PSScriptRoot 'Check.ps1') @check
}

function Set-DeploymentHead {
    param([string] $RuntimeRepo, [string] $ExpectedHead, [string] $Target)
    Assert-DeploymentClean $RuntimeRepo
    if ((Get-DeploymentHead $RuntimeRepo) -cne $ExpectedHead) { throw 'Live HEAD changed before checkout.' }
    # No reset, clean, stash, force, dependency install, or venv creation in this path.
    Invoke-DeploymentGit $RuntimeRepo @('checkout', '--no-overwrite-ignore', '--detach', $Target)
    if ((Get-DeploymentHead $RuntimeRepo) -cne $Target) { throw 'Checkout did not reach expected HEAD.' }
}

function New-DeploymentRollbackRef {
    param([string] $RuntimeRepo, [string] $Predecessor)
    $ref = 'refs/byte-mcp/rollback/' + [guid]::NewGuid().ToString('N')
    Invoke-DeploymentGit $RuntimeRepo @('update-ref', $ref, $Predecessor, ('0' * 40))
    if ((Invoke-DeploymentGit $RuntimeRepo @('rev-parse', $ref)).Trim() -cne $Predecessor) {
        throw 'Durable rollback ref verification failed.'
    }
    $ref
}

function Write-DeploymentReceipt {
    param([string] $Path, $Receipt)
    # Retain candidate and receipt on all outcomes; never remove unexplained files.
    $json = $Receipt | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function Invoke-ByteMcpPromotion {
    param(
        [Parameter(Mandatory)][string] $RuntimeRepo,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $ExpectedPredecessor,
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $TargetCommit,
        [Parameter(Mandatory)][string] $CandidateRepo,
        [string[]] $ExpectedAdded = @(), [string[]] $ExpectedRemoved = @(),
        [string] $SupervisorTaskName = 'Byte-MCP Daemon', [switch] $Apply,
        [string] $StateRoot = (Join-Path $env:USERPROFILE '.byte-mcp'),
        [ValidateRange(1024,65535)][int] $McpPort = 8000,
        [ValidateRange(1024,65535)][int] $TunnelPort = 8080,
        [ValidateSet('ScheduledTask','LocalProcess')][string] $SupervisorKind = 'ScheduledTask',
        [string] $SupervisorName = $SupervisorTaskName,
        [ValidateSet('Production','Disposable')][string] $Mode = 'Production',
        [string] $BaselineFailureFile,
        [switch] $InjectPostStartFailure
    )
    $runtime = Resolve-DeploymentPath $RuntimeRepo
    $candidate = Resolve-DeploymentPath $CandidateRepo
    $productionRuntime = Resolve-DeploymentPath 'C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon'
    $legacyMockContext = $runtime -ine $productionRuntime -and -not $PSBoundParameters.ContainsKey('Mode') -and
        -not $PSBoundParameters.ContainsKey('StateRoot') -and -not $PSBoundParameters.ContainsKey('McpPort') -and
        -not $PSBoundParameters.ContainsKey('TunnelPort') -and -not $PSBoundParameters.ContainsKey('SupervisorKind') -and
        -not $PSBoundParameters.ContainsKey('SupervisorName')
    $context = if ($legacyMockContext) { $null } else {
        New-DeploymentContext -RuntimeRepo $runtime -StateRoot $StateRoot -McpPort $McpPort -TunnelPort $TunnelPort `
            -SupervisorKind $SupervisorKind -SupervisorName $SupervisorName -Mode $Mode -BaselineFailureFile $BaselineFailureFile
    }
    if ($InjectPostStartFailure -and $context.Mode -ne 'Disposable') { throw 'Post-start failure injection is permitted only in disposable mode.' }
    $python = Join-Path $candidate '.venv\Scripts\python.exe'
    Assert-DeploymentIsolation $runtime $candidate $python
    $mutexKey = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($runtime.ToLowerInvariant())))
    $mutex = [Threading.Mutex]::new($false, "Local\ByteMCP-Deployment-$mutexKey")
    $locked = $false
    try {
        try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] {
            throw 'A previous promotion was interrupted; inspect its durable receipt before retrying.'
        }
        if (-not $locked) { throw 'Another promotion owns this runtime.' }
        Assert-DeploymentClean $runtime
        $before = Get-DeploymentRuntime -RuntimeRepo $runtime -Context $context
        Assert-DeploymentRuntime $before $runtime $ExpectedPredecessor @($before.tools)
        $supervisor = Get-DeploymentSupervisor -RuntimeRepo $runtime -TaskName $SupervisorTaskName -Context $context
        $venvIdentity = Get-DeploymentVenvIdentity $runtime
        New-DeploymentCandidate $runtime $candidate $ExpectedPredecessor $TargetCommit | Out-Null
        $receiptPath = Join-Path $candidate '.venv\deployment-receipt.json'
        Invoke-DeploymentQualification -RuntimeRepo $runtime -CandidateRepo $candidate -PythonPath $python -Context $context | Out-Host
        Assert-DeploymentClean $candidate
        if ((Get-DeploymentHead $candidate) -cne $TargetCommit) { throw 'Candidate HEAD changed during qualification.' }
        $candidateTools = @(Get-DeploymentTools -Repo $candidate -PythonPath $python)
        $delta = Get-DeploymentToolDelta @($before.tools) $candidateTools $ExpectedAdded $ExpectedRemoved
        $receipt = [ordered]@{
            runtime_repo = $runtime; predecessor = $ExpectedPredecessor; target = $TargetCommit
            candidate_repo = $candidate; tool_delta = $delta; result = 'QUALIFIED_ONLY'
            rollback_ref = $null; production_venv_recreated = $false
        }
        Write-DeploymentReceipt $receiptPath $receipt
        if (-not $Apply) { return [pscustomobject]$receipt }
        # Revalidate after arbitrarily long qualification, before any live operation.
        Assert-DeploymentClean $runtime
        $fresh = Get-DeploymentRuntime -RuntimeRepo $runtime -Context $context
        Assert-DeploymentRuntime $fresh $runtime $ExpectedPredecessor @($before.tools)
        if ((Get-DeploymentVenvIdentity $runtime) -cne $venvIdentity) { throw 'Production venv changed during qualification.' }
        $supervisor = Get-DeploymentSupervisor -RuntimeRepo $runtime -TaskName $SupervisorTaskName -Context $context
        $receipt.rollback_ref = New-DeploymentRollbackRef $runtime $ExpectedPredecessor
        $receipt.result = 'PREPARED'
        Write-DeploymentReceipt $receiptPath $receipt
        $restoreSupervisor = $false
        $mutationAttempted = $false
        try {
            # Set restoration obligation before an operation that could partially succeed.
            $restoreSupervisor = $true
            Suspend-DeploymentSupervisor $supervisor
            Stop-DeploymentRuntime -RuntimeRepo $runtime -Context $context
            Assert-DeploymentSupervisorStopped $supervisor
            $receipt.result = 'PROMOTING'
            Write-DeploymentReceipt $receiptPath $receipt
            $mutationAttempted = $true
            Set-DeploymentHead $runtime $ExpectedPredecessor $TargetCommit
            Resume-DeploymentSupervisor $supervisor
            $after = Wait-DeploymentRuntime -RuntimeRepo $runtime -Context $context -ExpectedHead $TargetCommit -ExpectedTools $candidateTools -TaskName $SupervisorTaskName
            if ($InjectPostStartFailure) { throw 'Injected disposable post-start verification failure.' }
            if ($after.server_pid -eq $before.server_pid -and $after.server_started -eq $before.server_started) {
                throw 'Post-start evidence still identifies the predecessor process.'
            }
            if ((Get-DeploymentVenvIdentity $runtime) -cne $venvIdentity) { throw 'Production venv identity changed.' }
            Assert-DeploymentClean $runtime
            $receipt.result = 'PROMOTED'
            $receipt['post_start'] = $after
            Write-DeploymentReceipt $receiptPath $receipt
        }
        catch {
            $failure = $_.Exception.Message
            $receipt['failure'] = $failure
            if ($mutationAttempted) {
                try {
                    # The supervisor might already be stopped, or running after failed startup.
                    Suspend-DeploymentRecoverySupervisor $runtime $supervisor
                    Stop-DeploymentRuntime -RuntimeRepo $runtime -Context $context
                    $head = Get-DeploymentHead $runtime
                    if ($head -cne $ExpectedPredecessor -and $head -cne $TargetCommit) {
                        throw 'Unexpected live lineage during rollback; refusing overwrite.'
                    }
                    Set-DeploymentHead $runtime $head $ExpectedPredecessor
                    Resume-DeploymentSupervisor $supervisor
                    $rollback = Wait-DeploymentRuntime -RuntimeRepo $runtime -Context $context -ExpectedHead $ExpectedPredecessor -ExpectedTools @($before.tools) -TaskName $SupervisorTaskName
                    if ((Get-DeploymentVenvIdentity $runtime) -cne $venvIdentity) { throw 'Production venv identity changed during rollback.' }
                    $receipt.result = 'ROLLED_BACK'
                    $receipt['rollback'] = $rollback
                }
                catch {
                    $receipt.result = 'ROLLBACK_NOT_READY'
                    $receipt['rollback_failure'] = $_.Exception.Message
                }
            }
            else { $receipt.result = 'FAILED_BEFORE_CHECKOUT' }
            Write-DeploymentReceipt $receiptPath $receipt
            throw "Promotion failed: $failure; outcome=$($receipt.result); receipt=$receiptPath"
        }
        finally {
            if ($restoreSupervisor) {
                Resume-DeploymentSupervisor $supervisor
                # Failed suspension/stop also requires a healthy predecessor, not just task enablement.
                if (-not $mutationAttempted) {
                    $null = Wait-DeploymentRuntime -RuntimeRepo $runtime -Context $context -ExpectedHead $ExpectedPredecessor -ExpectedTools @($before.tools) -TaskName $SupervisorTaskName
                }
            }
        }
        [pscustomobject]$receipt
    }
    finally {
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
