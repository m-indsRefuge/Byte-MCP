# OX Validation V1 — Codex Execution Brief

Execute the approved OX validation implementation for `m-indsRefuge/Byte-MCP` using the committed design and implementation plan as binding authority.

Read these first:

- `docs/superpowers/specs/2026-08-29-ox-integration-design.md`
- `docs/superpowers/plans/2026-08-29-ox-validation-v1-implementation-plan.md`

Use the `superpowers:subagent-driven-development` workflow and `superpowers:using-git-worktrees` before implementation. Work in an isolated feature worktree/branch; do not implement directly on `main`. Run a clean baseline before changing code. Maintain the SDD progress ledger so the run can resume safely after compaction.

**You have a usage budget of 35% with which to finish this task, please ensure that you plan accordingly**

Treat 35% as a hard ceiling, not a target. Optimize for delivering the maximum verified implementation within that budget. Use inexpensive/fast subagents for mechanical, tightly specified tasks; standard-capability subagents for multi-file integration and task review; reserve the most capable model only for work that genuinely requires high judgment, difficult debugging, late fix-loop escalation, or the final whole-branch review. Avoid redundant exploration, duplicate reviews, unnecessary re-reading, and speculative refactoring.

The implementation plan contains the authoritative task order and exact contracts. Follow TDD inside each bounded task, commit independently testable progress frequently, and perform the required task-scoped review before moving to the next task. Do not silently weaken the design to save usage.

Priority under budget pressure:

1. Preserve all security and trust-boundary invariants from the spec.
2. Complete the core OX subsystem and four MCP tool contracts.
3. Keep all existing Byte-MCP local tools/regression tests green.
4. Complete deterministic tests, lint, compile, and dependency-integrity gates.
5. Complete broad whole-branch review and repair Critical/Important findings where budget permits.
6. Defer only non-load-bearing polish/minor findings with explicit ledger entries and a precise handoff for Byte_Coding.

If the remaining budget becomes too small to safely finish the next bounded task, do not start an unfinishable subsystem. Finish the current task to a clean testable commit, update the ledger, run the strongest verification affordable without exceeding the ceiling, and produce a handoff identifying: completed tasks/commits, exact tests run and results, open findings, next task, and any rulings made.

Security and side-effect gates:

- Never print, log, persist, commit, or otherwise expose `AI_GATEWAY_API_KEY`.
- Automated tests must use fakes/`httpx.MockTransport`; do not spend real Vercel/Z.AI credits during implementation.
- Do not make the first live Vercel/OX API call. Stop at the live-canary gate and report that Nolan's explicit approval is required before any real outbound transmission.
- Do not transmit private repository content externally.
- Do not merge/push implementation to shared `main` or publish/release without explicit approval.
- Do not introduce provider abstraction, autonomous loops, arbitrary subprocess execution, repository mutation authority, or unapproved scope expansion.

The fixed provider contract remains Vercel AI Gateway -> Z.AI only -> `zai/glm-5.3-flash`, with `providerOptions.gateway.only=["zai"]` in every provider request.

At completion, report concise evidence: branch/worktree, commit range, tasks completed, test/lint/compile/pip-check results, whole-branch review verdict, deferred findings/rulings, approximate budget consumed if visible, and whether the implementation is ready for Byte_Coding review and the human-approved live canary.
