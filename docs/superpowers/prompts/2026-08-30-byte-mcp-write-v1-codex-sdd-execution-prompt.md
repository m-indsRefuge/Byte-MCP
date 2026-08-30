# Codex Execution Prompt — Byte-MCP Write V1

You are the controller for a security-sensitive implementation of Byte-MCP Write V1.

Use the Superpowers workflow. The approved architecture and implementation plan already exist; do not re-architect them unless execution proves a real contradiction. Your job is to execute the approved plan efficiently, with disciplined subagent use, TDD, review gates, durable progress tracking, and exact-head verification.

## Authoritative inputs

Repository: `m-indsRefuge/Byte-MCP`

Start from branch: `orchestration/byte-mcp-write-v1-codex`

Create implementation branch/worktree: `build/byte-mcp-write-v1`

Spec:

`docs/superpowers/specs/2026-08-30-byte-mcp-write-v1-design.md`

Implementation plan:

`docs/superpowers/plans/2026-08-30-byte-mcp-write-v1-implementation-plan.md`

The spec is binding authority. The plan is the implementation argument. If they conflict, rule in favor of the spec, record the ruling in the SDD ledger, and continue unless every safe path forward is guesswork.

## Required Superpowers skills

Use these skills at the appropriate points:

1. `using-git-worktrees` — create or verify an isolated implementation worktree before any production edit.
2. `subagent-driven-development` — controller workflow for all implementation tasks.
3. `test-driven-development` — RED before production code for every feature/repair.
4. `systematic-debugging` — diagnose root cause before fixes when tests or behavior fail.
5. `requesting-code-review` — fresh task reviewer after every task and broad reviewer at the end.
6. `verification-before-completion` — never claim a gate passed without fresh command evidence.
7. `finishing-a-development-branch` — only after the implementation and acceptance gates are genuinely complete.

## Budget discipline

This run is intentionally constrained. Plan and execute so that roughly half of the normal Codex allowance remains in reserve when the local implementation work is complete.

Do not spend usage re-planning an architecture that is already approved. Spend the constrained allowance on implementation, tests, review, and repair.

Budget priorities:

- 5%: controller preflight, worktree, ledger, baseline.
- 60%: implementation + focused RED/GREEN tests.
- 15%: per-task independent reviews.
- 10%: adversarial/full-gate verification and broad final review.
- 10%: repair contingency.

If the repair contingency is consumed, conserve usage by reducing redundant exploration and report verbosity — never by skipping TDD, required review, security tests, or verification.

Usage-saving rules:

- Read the spec and plan once during controller preflight; subagents read task briefs, not the whole plan.
- Use `scripts/sdd-workspace` and `scripts/task-brief` from the Superpowers SDD skill.
- Store detailed worker/reviewer output in files under the SDD workspace. Return only compact status to the controller.
- Never paste accumulated task history into later subagent prompts.
- Never dispatch two implementation subagents in parallel. The transaction subsystem is coupled and parallel implementers create merge/conflict overhead.
- Implementer subagents must not spawn their own subagents or reviewers.
- Do not perform duplicate reviews. One task reviewer is the gate; one final whole-branch reviewer is the final gate.
- Use the least expensive model tier that is genuinely adequate. Turn count matters more than nominal token price.
- Do not repeatedly run the complete repository suite after every small RED/GREEN cycle. Run focused tests for the task, then the exact full gates specified by the plan.
- Do not browse/research externally unless a concrete implementation blocker requires it.
- Do not rewrite stable existing code merely for style.

## Controller preflight — target 10 minutes

This section should take about 10 minutes of active work.

1. Confirm repository/branch state and fetch latest refs.
2. Use `using-git-worktrees` to create or verify an isolated worktree on `build/byte-mcp-write-v1` from the current orchestration branch.
3. Run the repository baseline gate before edits: `./scripts/Check.ps1` on Windows/pwsh.
4. Initialize the SDD workspace and ledger for the canonical implementation plan.
5. Read the spec and canonical implementation plan once.
6. Perform the required SDD cross-task/interface preflight scan and write the table/rulings into the ledger.
7. Create controller todos for Tasks 1–14.

If the baseline is red, stop implementation and diagnose before proceeding.

## Subagent protocol

For every implementation task:

1. Record `BASE=$(git rev-parse HEAD)`.
2. Generate that task's brief with the Superpowers `task-brief` helper.
3. Dispatch exactly one fresh implementer subagent.
4. Tell the implementer to read the task brief first, implement only that task, run its RED/GREEN commands, commit its work, self-review, and write the detailed report to the SDD report file.
5. After DONE, generate the review package from BASE..HEAD.
6. Dispatch a fresh task reviewer subagent with the brief, report, review package, and global constraints.
7. Require both spec-compliance and code-quality approval.
8. For Critical/Important findings, follow the SDD fix loop: rounds 1–3 resume the original implementer; rounds 4–5 use a fresh, more capable implementer. Re-review every fix round.
9. Record all completions, findings, rulings, commits, and time variance in the ledger.
10. Proceed automatically to the next task when the review gate is clean. Do not ask the human whether to continue.

Stop only for the Superpowers stop classes: irreversible/destructive action, security-sensitive external action, side effect outside the isolated worktree such as push/publish/merge, or a plan defect so severe that every safe path is guesswork.

## Model-tier guidance

Choose the model explicitly for every subagent.

Use a fast/low-cost implementation model for tightly specified mechanical work. Use a standard reasoning model for integration/concurrency/security work. Use the strongest available reasoning model only where the risk justifies it and for final whole-branch review.

Suggested tiers by task:

- Task 1 policy/settings/errors: fast-to-standard implementer; standard reviewer.
- Task 2 path authority/hard-link/reparse protection: standard implementer; high-judgment reviewer.
- Task 3 operation/manifest contracts: standard implementer; standard reviewer.
- Task 4 staging/recovery/integrity: standard/high implementer; high-judgment reviewer.
- Task 5 durable journal + OS locking: standard/high implementer; high-judgment reviewer.
- Task 6 prepare orchestration: standard implementer; standard/high reviewer.
- Task 7 commit/rollback engine: high-capability implementer; high-capability reviewer.
- Task 8 move/delete/restore: standard/high implementer; high-capability reviewer.
- Task 9 crash reconciliation/RECOVERY_REQUIRED: high-capability implementer; high-capability reviewer.
- Task 10 service/audit semantics: standard/high implementer; high-capability reviewer.
- Task 11 MCP surface/annotations: standard implementer; standard reviewer.
- Task 12 launcher enablement: fast-to-standard implementer; standard reviewer.
- Task 13 adversarial/failure-injection gate: high-capability implementer; high-capability reviewer.
- Task 14 docs/local acceptance preparation: standard implementer; standard reviewer.
- Final whole-branch review: strongest available reviewer.

Do not use the strongest model by default for every task; reserve it for concurrency, rollback, crash recovery, adversarial review, and final review.

## Time guide

These are planning targets, not deadlines. They include one implementation pass, focused RED/GREEN tests, and one clean task review. A necessary fix loop may extend them. Never trade correctness for the clock.

If a task exceeds roughly 1.5× its guide, stop spending blindly: inspect the ledger, identify whether the delay is context, test design, implementation complexity, or a plan defect, then apply the smallest corrective ruling.

### Subsystem A — Authority contracts — target 45 minutes

You are building the operator-policy and filesystem-authority foundation.

- Task 1: Policy/settings/errors/fixtures — about 12 minutes.
- Task 2: Write path authority, Windows aliases, hard links, reparse denial — about 15 minutes.
- Task 3: Operations, patches, manifest conflict/dependency contracts — about 18 minutes.

Exit condition: policy fingerprinting, protected-root behavior, path denial, structured patches, and one-project manifests are independently green and reviewed.

### Subsystem B — Integrity primitives — target 35 minutes

You are building the protected state primitives that later transactions rely on.

- Task 4: UTF-8 profiles, same-pass snapshots, staging, directory digests, recovery/retention — about 20 minutes.
- Task 5: Durable journal and OS-backed per-project writer locks — about 15 minutes.

Exit condition: staged/recovery bytes are integrity-bound, journals are durable, and cross-process locking is proven on supported platforms.

### Subsystem C — Transaction engine — target 90 minutes

You are building the core mutation authority. This is the highest-risk section and should receive the largest share of reasoning usage.

- Task 6: Prepare orchestration — about 18 minutes.
- Task 7: Commit create/replace/patch + stale-state defense + rollback — about 27 minutes.
- Task 8: Same-project move, recoverable delete, restore — about 20 minutes.
- Task 9: Restart reconciliation and `RECOVERY_REQUIRED` — about 25 minutes.

Exit condition: prepare never mutates live projects; commit is idempotent and hash-bound; rollback restores exact pre-state; interrupted commits reconcile deterministically or fail closed.

### Subsystem D — Service and operator boundary — target 45 minutes

You are connecting the engine to Byte-MCP without broadening authority.

- Task 10: Write service, audit finalization, status, terminal cleanup — about 18 minutes.
- Task 11: Exactly three MCP mutation tools, annotations, capability metadata, smoke discovery — about 15 minutes.
- Task 12: Operator-only policy enablement and launcher environment — about 12 minutes.

Exit condition: write authority remains opt-in/operator-controlled, audit semantics are safe after ambiguous/final states, and no direct write/delete/move/policy bypass exists.

### Subsystem E — Adversarial/full deterministic gate — target 30 minutes

You are attacking the completed subsystem rather than adding convenience features.

- Task 13: Authority attacks, binary/limit matrix, race injection, rollback/restart matrix, deterministic E2E — about 30 minutes.

Exit condition: focused adversarial suite and full `./scripts/Check.ps1` are green from fresh evidence.

### Subsystem F — Documentation and local acceptance preparation — target 20 minutes active work

You are preparing the implementation for external CI/live acceptance, not declaring it accepted.

- Task 14 local/documentation portion — about 20 minutes active work.

External CI waiting time and real ChatGPT/tunnel canary time are not part of the active engineering estimate.

At the first action that would push a branch, enable Write V1 on Nolan's real machine, mutate the real `AIProjects` canary through ChatGPT, publish, merge, or otherwise create an external/security-sensitive side effect, STOP and present the exact evidence/state to the human for approval.

## Final review — target 20 minutes

After Tasks 1–13 and the local-only portion of Task 14 are complete:

1. Determine merge base against the branch this implementation started from.
2. Generate one full review package for MERGE_BASE..HEAD.
3. Dispatch one strongest-available whole-branch reviewer using the Superpowers requesting-code-review workflow.
4. Point the reviewer at every deferred minor and every `Ruling:` ledger entry.
5. If findings exist, dispatch exactly one consolidated fix subagent for the whole final finding set, then exactly one scoped re-review.
6. Run fresh exact-head verification after any final fixes.
7. Produce a compact controller report: commits, full test evidence, remaining parked findings/rulings, elapsed-time variance, and the next external action requiring human approval.

Do not merge, push, enable the live write policy, or perform the real ChatGPT canary without explicit human approval.

## TDD and debugging rules

- No production behavior without a failing test first.
- A regression repair begins with a test reproducing the defect.
- Do not modify a test merely because the production implementation is inconvenient.
- On failure, classify and reproduce before changing code.
- After three unsuccessful repair attempts on the same root cause, question the approach rather than stacking patches.
- Focused tests prove the task; `./scripts/Check.ps1` proves the repository gate when the plan requires it.

## Security invariants that must never be traded for speed

- Byte cannot modify `AIProjects/Byte-MCP` through Write V1.
- Byte cannot modify its own policy/private state.
- Existing-file mutations require the exact prior SHA-256.
- Cross-project movement is denied.
- Binary/opaque mutation is denied.
- Deletes are recoverable; permanent purge is not an MCP tool.
- Prepare precedes every commit.
- Recovery is created before existing-state mutation.
- Commit is durable/idempotent.
- Uncertain rollback leads to `RECOVERY_REQUIRED`, not guessing.
- No shell/process/Git/registry/arbitrary HTTP/computer-use authority is added.
- Existing read tools keep their authority boundary.

## Completion boundary

Your local implementation session is complete only when:

- all locally executable plan tasks have passed their task reviews;
- the full repository gate is freshly green;
- the whole-branch review is complete and any required fixes are verified;
- the SDD ledger is complete and contains every ruling;
- the implementation branch is clean;
- you have stopped before the first external/security-sensitive rollout action and asked the human for approval.

Do not describe Write V1 as accepted merely because implementation is green. Acceptance still requires exact-head CI plus the real ChatGPT -> Secure MCP Tunnel canary and intentional-denial checks from Task 14.

Begin now with the Superpowers worktree setup and SDD controller preflight.