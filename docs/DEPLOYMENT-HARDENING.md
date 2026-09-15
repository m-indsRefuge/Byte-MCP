# Byte-MCP code promotion

This workflow is for explicitly authorized **code-only** promotions. Keep the reviewed
deployment scripts in a separate control worktree. Implementation/qualification of
these scripts does not authorize a live promotion. In particular, IDE-01 remains out
of scope for the deployment-hardening milestone.

## Two different validation operations

`Test-ByteMCPRuntime.ps1` is a read-only production health check. It binds the exact
checkout root, clean Git state, expected HEAD, launcher `repo_path`, managed process
identities, port 8000 owner, enabled/running supervisor task and exact MCP tool set.
Production Python imports the server from the expected source location. Discovery
uses MCP initialize/list_tools over the fixed loopback endpoint. It never invokes
MCP tools, providers, or development tooling.

`Check.ps1` is candidate engineering qualification. Its mandatory `-PythonPath` and
`-ProductionRepo` arguments prevent accidentally qualifying in production. The Python
path must be `<candidate>\.venv\Scripts\python.exe`; its prefix and server import
origin must match the candidate. Path guards reject overlap, junctions/reparse
points, UNC paths and short-name aliases. Shared managed launcher state is also
checked so a misleading `-ProductionRepo` cannot hide the active checkout.

PowerShell (Windows, PowerShell 7.4+ for deployment):

```powershell
$runtime = 'C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon'
$candidate = 'C:\path\to\isolated-hardening-worktree'
& "$candidate\scripts\Check.ps1" `
    -PythonPath "$candidate\.venv\Scripts\python.exe" `
    -ProductionRepo $runtime
```

Qualification runs pip dependency consistency, compilation, Ruff, full pytest,
Windows launcher/Pester tests, and provider-free import/exact tool discovery. Native
failures and empty/failed Pester runs fail the gate. No development packages are
installed into production. The promotion command creates a fresh candidate and
installs the project's declared `[dev]` extra there using `uv`.

## Promotion contract

`Promote-ByteMCP.ps1` requires `RuntimeRepo`, full 40-character
`ExpectedPredecessor`, full `TargetCommit`, and a nonexistent `CandidateRepo`.
`ExpectedAdded` and `ExpectedRemoved` default to empty sets. Omitting `-Apply`
performs qualification only. An invocation with `-Apply` requires separate Operator
authorization for that particular promotion.

1. Acquire a per-runtime mutex; verify production identity, clean state, READY,
   managed supervisor, tool set, and production venv identity.
2. Create the candidate from the exact predecessor, then check out the target.
   The target must descend from the predecessor. Dependency manifest/lock changes
   and tracked `.venv` paths are rejected; environment migrations need a separately
   reviewed workflow.
3. Create only the absolute candidate-derived venv. Run the complete qualification
   gate. Record pre-promotion/candidate/added/removed tools and reject unexpected
   deltas. Require candidate HEAD unchanged and its worktree clean.
4. Recheck live preconditions. Before stopping anything, create and verify a durable
   `refs/byte-mcp/rollback/<id>` ref to the exact predecessor and write a receipt.
5. Disable scheduled triggers, verify and stop only the supervisor process, and
   verify quiescence. Stop surviving managed components only after checking their
   executable/PID/start-time identities and listener ownership. This supports a
   partially failed startup without killing an unrelated process.
6. Check out the exact target with `--no-overwrite-ignore`. Never reset, stash,
   clean, force checkout, recreate the production venv, or install production
   dependencies. Restart through the unchanged registered supervisor action so
   existing startup/environment handling remains authoritative.
7. Require fresh managed process evidence, exact path/HEAD/READY/tool set, and
   restored/running supervisor. Verify production venv identity and clean state.

Failure after checkout triggers ownership-checked shutdown, exact predecessor
checkout, managed restart and predecessor READY/tool verification. A completed
rollback still returns an error and records `ROLLED_BACK`, never promotion success.
If recovery cannot be proven (for example, a foreign process takes a listener,
launcher state changes unexpectedly, or the predecessor cannot start), the receipt
records `ROLLBACK_NOT_READY`. The finally path still attempts supervisor restoration;
the error requires Operator attention. No claim of recovery is made in that state.

## Evidence and interruption

The candidate and `.venv\deployment-receipt.json` are retained. The receipt includes
runtime/candidate identities, predecessor/target SHAs, rollback ref, exact tool delta,
outcome, post-start/rollback evidence, and failure cause. Rollback refs are retained
independently of reflogs. This command never deletes candidate worktrees.

Normal exceptions are handled transactionally; OS termination or power loss cannot
execute `finally`. After interruption, inspect the receipt, rollback ref, task state,
launcher ownership and HEAD before taking an explicitly authorized recovery action.
Do not blindly retry or remove evidence. Do not run concurrent manual Git/launcher
mutations; the deployment mutex serializes this workflow, not arbitrary Operator
commands. Promotion code and test/dependency installation are trusted reviewed input,
not a sandbox for hostile code.

## Testing boundary

Pester exercises the transaction with fake runtime/supervisor boundaries, real path
guards, and disposable Git checkouts. Python tests exercise discovery and blocked
provider connections. Production health checks are read-only. Real supervisor
suspension/restart and an actual live promotion are deliberately not part of this
milestone's qualification.
