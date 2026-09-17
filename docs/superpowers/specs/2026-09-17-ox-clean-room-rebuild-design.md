# OX Clean-Room Rebuild Architecture

**Status:** Approved design for implementation planning

**Date:** 2026-09-17

**Design branch baseline:** `fb87e39d24ee2e74f648da0495059f147f30fb89`

> The implementation baseline must be re-verified immediately before implementation begins. This design branch starts from the latest converged NVIDIA-capable Byte-MCP lineage verified during design review; it does not authorize deployment or a live provider call.

## 1. Executive summary

The existing OX V1 and abandoned OX V2 implementations are to be fully archived and removed from the active Byte-MCP codebase. A new OX implementation will then be built from scratch as a small, synchronous, single-request adversarial code-review subsystem.

The new OX service has exactly two public MCP tools:

```text
ox_review(...)
ox_get_review(review_id)
```

One explicit user authorization for an OX review authorizes the complete lifecycle of exactly one review:

```text
validate scope
→ freeze exact repository snapshot
→ build immutable review packet
→ persist preparation evidence
→ consume one send opportunity
→ make at most one provider request
→ persist exact provider response
→ extract free-form assistant review
→ persist final review
→ return review
```

There is no second approval gate between preparation and transmission.

There is no automatic retry, continuation, revalidation, background worker, recovery daemon, interactive provider tool loop, or structured provider-response schema.

OX remains an independent adversarial code reviewer. The provider path remains Vercel AI Gateway → Z.AI/GLM using the same provider/model route already used by OX. The first implementation should keep the current fixed model profile unless a separately approved provider-profile change is made.

The implementation may reuse existing provider-neutral primitives that were successfully developed for NVIDIA, including canonical request identity, provider authorization objects, common attempt outcomes, and one-shot HTTP transport contracts where compatible. OX must not import NVIDIA code, and NVIDIA must not import OX.

## 2. Goals

The rebuild exists to restore OX as a dependable, bounded code-review capability while removing the architectural complexity that accumulated in V1 and the unfinished assumptions embedded in V2.

The primary goals are:

1. Make OX simple enough to reason about end to end.
2. Preserve a strict one-review / one-provider-request maximum.
3. Review the actual current code on disk, including dirty and untracked source state.
4. Allow both bounded reviews and full-repository reviews.
5. Restrict OX to repositories exposed by Byte-MCP beneath the approved `/AiProjects` root.
6. Freeze exactly what OX reviews before networking begins.
7. Preserve durable local evidence sufficient to audit what was reviewed and what the provider returned.
8. Return OX's natural free-form technical review without forcing a structured findings schema.
9. Reuse provider-neutral infrastructure only where it is genuinely shared and already proven.
10. Keep NVIDIA, Wolfram, and core Byte-MCP behavior unchanged.
11. Fail closed when scope, safety, identity, packet size, or transmission state is uncertain.
12. Keep the implementation substantially smaller and easier to operate than OX V1/V2.

## 3. Non-goals

The initial rebuild does not provide:

- General-purpose OX chat.
- Multi-turn provider conversations.
- Interactive provider access to Byte-MCP tools.
- Automatic follow-up questions.
- Automatic retries.
- A002-style retry identities.
- Continuation or revalidation workflows.
- Background jobs or queues.
- Provider-result polling.
- Restart recovery that restores send authority.
- Semantic parsing of OX's review into findings, severity enums, decisions, or JSON schemas.
- Silent packet truncation, summarization, file dropping, or multi-call splitting.
- Review of arbitrary filesystem paths outside Byte-MCP's approved project root.
- Compatibility adapters for OX V1/V2 runtime execution.
- Automatic migration or reinterpretation of V1/V2 evidence.

## 4. Full V1/V2 archive-and-remove boundary

### 4.1 Archival requirement

Before new OX production code is introduced, the implementation campaign must establish exact archival identities for both old generations.

Preserve at minimum:

- Exact final V1 source commit/ref identity.
- Exact final V1 evidence inventory and hashes already captured by the project.
- Exact abandoned V2 source/design/probe identity.
- Historical V1/V2 specs, plans, and qualification artifacts through immutable Git history and/or clearly named archival refs.

The purpose is historical and forensic preservation, not runtime compatibility.

### 4.2 Active-tree removal

Remove from the active implementation:

```text
src/byte_mcp/ox/
src/byte_mcp/ox_v2/
```

as they exist before the rebuild, along with:

- Old OX execution tests that exist only to exercise V1/V2 behavior.
- Temporary V2 lifetime-probe code and registrations.
- V1/V2 MCP execution registrations.
- V1 background job/runtime ownership machinery.
- Continuation/revalidation/retry surfaces.
- Obsolete active documentation that could be mistaken for the governing OX architecture.

Historical material remains available through Git history/archive refs. A small archival pointer may remain in current documentation.

### 4.3 No compatibility layer

The new `src/byte_mcp/ox/` directory is a new implementation with no execution imports from the archived OX generations.

`ox_get_review()` reads only new-generation OX review evidence.

Historical V1/V2 retrieval, if ever desired, must be implemented as a separately reviewed archival/offline capability and must not keep legacy execution machinery alive.

## 5. Public product contract

### 5.1 Tool surface

Expose exactly two OX MCP tools:

```text
ox_review(...)
ox_get_review(review_id)
```

No other OX runtime tools are part of the initial release.

### 5.2 Approval model

User approval for one OX review authorizes the whole review lifecycle, including the single provider request.

There is no PREPARE → second approval → SEND sequence.

Approval is bounded to one review invocation. It does not create standing permission for future OX calls.

### 5.3 Retry policy

One approved review may initiate at most one outbound OX provider request.

If transmission definitely fails before any provider request could have begun, record a definite failure.

If transmission may have begun and the final outcome cannot be established, record `OUTCOME_UNKNOWN` and stop.

Never retry automatically. Never resume a partial request. Never reconnect in order to obtain a result. Never initiate a second POST under the same review identity.

A later review requires fresh user authorization and a new review identity.

## 6. Review scope and repository authority

### 6.1 Byte-MCP root boundary

OX may inspect only repositories that Byte-MCP exposes beneath the approved `/AiProjects` project root.

The caller selects a repository through a Byte-MCP-controlled alias/identifier, not by providing an arbitrary filesystem path.

Absolute local paths must not be transmitted to the provider.

### 6.2 Supported review modes

The first release supports both:

1. **Bounded review** — selected subsystem, path set, or bounded change area.
2. **Full-repository review** — all eligible material in the approved repository snapshot.

Bounded scope must remain bounded. Byte-MCP may include explicitly associated context such as adjacent tests or project configuration only under deterministic snapshot policy. It must never silently expand a bounded request into a full repository review.

### 6.3 Current filesystem state is authoritative

OX reviews the code as it exists at review time, not only committed Git state.

Eligible snapshot content may include:

- committed tracked files;
- staged edits;
- unstaged edits;
- relevant untracked source/test/config/documentation files.

Git metadata may annotate artifact state, but file bytes on disk at snapshot time are the content authority.

A file edit after snapshot freeze must not alter the review packet.

## 7. New OX package architecture

The intended module structure is:

```text
src/byte_mcp/
    providers/                 # existing shared provider-neutral primitives
    ox/                        # new implementation only
        __init__.py
        models.py
        scope.py
        snapshot.py
        packet.py
        evidence.py
        client.py
        service.py
        runtime.py
```

Responsibilities:

### `models.py`

Small immutable OX-specific records and closed state/outcome values. Do not create a broad framework.

### `scope.py`

Resolve repository aliases and review mode inside Byte-MCP authority. Enforce `/AiProjects` containment and bounded path selection. Reject arbitrary external paths.

### `snapshot.py`

Enumerate eligible material, reject boundary escapes, freeze exact current bytes, classify exclusions, compute artifact digests, and produce an immutable snapshot manifest.

### `packet.py`

Construct one deterministic bounded review packet from already frozen snapshot bytes. It must never reread the working tree.

### `evidence.py`

Maintain simple durable per-review filesystem evidence. Use atomic write/seal behavior where necessary. Do not introduce SQLite unless implementation evidence proves the file model cannot satisfy the approved contract.

### `client.py`

Own OX-specific provider request assembly and provider-envelope handling. Provider output remains natural free-form assistant text.

### `service.py`

Own the synchronous end-to-end lifecycle: scope → snapshot → packet → evidence → single send → exact response persistence → free-form review extraction → finalization.

### `runtime.py`

Lazy initialization/configuration for the Byte-MCP server. OX configuration failure must not block core Byte-MCP, NVIDIA, or Wolfram startup.

## 8. Shared provider primitives

OX may reuse proven provider-neutral code under `byte_mcp.providers` where the contract fits without weakening OX requirements.

Expected reusable concepts include:

- canonical prepared-request identity;
- request SHA-256 binding;
- safe provider authorization wrappers;
- common attempt outcome vocabulary;
- transport observations;
- exactly-one-execution primitives where they match OX's required transport semantics.

However, shared infrastructure does not mean shared review behavior.

```text
OX ──────┐
         ├── byte_mcp.providers
NVIDIA ──┘
```

Rules:

- OX must not import NVIDIA packages.
- NVIDIA must not import OX packages.
- OX must not invoke Wolfram.
- Provider-neutral changes must preserve existing NVIDIA behavior.
- If OX requires a provider-neutral change that breaks NVIDIA's established contract, stop for architecture review instead of modifying NVIDIA to fit OX.

OX-specific streaming/persistence behavior may remain specialized if the existing shared transport cannot satisfy it safely.

## 9. Snapshot policy

### 9.1 Eligible material

The snapshotter should include bounded textual project material useful for code review, including where applicable:

- source code;
- tests;
- project configuration;
- packaging/build definitions;
- schemas/migrations;
- scripts;
- technical documentation;
- repository-owned prompts/instructions that affect software behavior;
- other textual artifacts directly relevant to the selected scope.

Do not rely on a narrow extension whitelist. Use deterministic text eligibility plus explicit exclusions and hard size bounds.

### 9.2 Hard exclusions

The following categories must not enter an OX packet:

- `.env` and environment-secret files;
- known credentials/secrets files;
- private keys and private certificates;
- `.git` internals;
- virtual environments;
- dependency directories such as `node_modules`;
- caches;
- compiled/build/dist output;
- coverage output;
- IDE/runtime caches;
- binary objects;
- databases;
- archives;
- large media/assets;
- Byte-MCP provider/review evidence stores;
- other configured sensitive path patterns.

The exact exclusion policy must be versioned and test-covered.

### 9.3 Symlinks, junctions, and submodules

Symlinks and junctions must not be followed during snapshot collection. Boundary-escape attempts fail closed.

Submodule contents are not recursively imported automatically. A submodule may be represented as metadata only; its contents require an independently approved repository that Byte-MCP exposes under the project root.

### 9.4 Artifact identity

Every included artifact binds at least:

```text
logical_repository_path
byte_length
content_sha256
content_classification
optional_git_state
```

No absolute local filesystem path is required in provider material.

### 9.5 Snapshot identity

The snapshot digest must bind:

- repository identity;
- review mode/scope;
- snapshot policy version;
- deterministic sorted artifact inventory;
- artifact paths;
- byte lengths;
- artifact content hashes.

Changing one byte, adding/deleting a file, changing path inventory, or changing scope must produce a different snapshot identity.

## 10. Secret and privacy protection

Use layered protection.

### 10.1 Sensitive-path exclusion

Known-sensitive files are rejected/excluded before entering the review packet.

### 10.2 Local packet safety scan

After packet construction but before the send opportunity is consumed, run a bounded fail-closed local safety scan for strong secret indicators such as private-key material and explicitly configured provider credentials.

This scan is a safety control, not a claim that all possible secrets can be detected.

### 10.3 Exact credential exclusion

Load the OX/Vercel credential only during transmission preflight.

Before consuming send authority, compare the exact credential against the frozen packet/request material. If the exact credential appears anywhere in provider-bound evidence:

```text
STOP
provider requests = 0
```

Do not silently redact and continue.

### 10.4 Public/logging privacy

Ordinary MCP results and logs must not expose:

- provider credentials;
- authorization headers;
- raw request bodies;
- raw provider envelopes;
- absolute local filesystem paths;
- arbitrary exception strings;
- environment/proxy values;
- raw snapshot contents except the final free-form review when returned intentionally.

## 11. Packet contract

OX receives one frozen packet and no tools.

Conceptually:

```text
SYSTEM:
You are OX, an independent adversarial code reviewer.
Review only the frozen repository material supplied here.
Identify correctness, security, reliability, regression,
architecture, edge-case, and testing concerns.
Respond naturally as a technical reviewer.

USER:
review objective
scope description
snapshot identity
bounded repository metadata

--- FILE: relative/path.py ---
<exact frozen content>

--- FILE: tests/test_path.py ---
<exact frozen content>
...
```

The final wording may be refined during implementation planning, but these properties are fixed:

- one provider request;
- no provider tool loop;
- no structured-output requirement;
- no semantic response schema;
- provider reviews only supplied frozen evidence;
- provider response is natural free-form prose.

The packet is built only from stored frozen snapshot bytes.

## 12. Oversize behavior

Full-repository review must be truthful.

If the full eligible snapshot/serialized request exceeds the hard configured packet/request budget:

```text
STOP LOCALLY
provider requests = 0
```

Tell the caller a bounded review is required.

Never silently:

- truncate code;
- summarize files;
- rank/drop allegedly less-important files;
- split one review into multiple provider calls;
- call a partial packet a full-repository review.

The same fail-closed principle applies to bounded reviews that exceed the configured limit.

## 13. Provider path and response contract

### 13.1 Provider route

Keep the existing OX provider route:

```text
Byte-MCP → Vercel AI Gateway → Z.AI/GLM
```

Do not change provider/model route during the architecture rebuild unless separately reviewed.

### 13.2 Synchronous ownership

`ox_review` is synchronous from the MCP caller's perspective.

```text
authorize
→ snapshot
→ prepare
→ persist
→ send once
→ persist response
→ extract review
→ finalize
→ return
```

No worker, queue, delayed provider job, heartbeat process, or background ownership system.

### 13.3 Free-form response

OX's assistant reply is intentionally free-form.

Do not require:

- JSON;
- finding arrays;
- severity enums;
- pass/fail decisions;
- a predefined prose template.

A valid response must only satisfy protocol/delivery requirements sufficient to establish one non-empty assistant review.

Byte-MCP may store safe transport metadata around the review, but it must not semantically rewrite or normalize OX's review.

## 14. Evidence model

### 14.1 Storage style

Use a simple per-review local filesystem store under the Byte-MCP application data area rather than SQLite.

Conceptual layout:

```text
%LOCALAPPDATA%\Byte-MCP\ox\reviews\OX-000001\
    review.json
    snapshot.json
    packet.bin
    request.bin
    response.bin
    review.txt
```

Exact filenames may be refined in the implementation plan, but the evidence categories are fixed.

### 14.2 Evidence contents

Preserve at minimum:

- review identity;
- repository alias;
- review mode/scope;
- snapshot policy version;
- snapshot manifest/inventory;
- snapshot SHA-256;
- exact packet bytes;
- packet SHA-256;
- exact serialized provider request bytes;
- request SHA-256;
- provider/model route;
- start/finish timestamps;
- bounded transport observation;
- attempt outcome;
- exact provider response bytes when received;
- exact decoded free-form OX review when valid.

### 14.3 Immutability and atomicity

Use temporary-file + atomic-replace/seal patterns where necessary.

Frozen artifacts must not be rewritten after they become authoritative for a provider call.

Once transmission begins, no cleanup/rewrite operation may restore send authority for that review.

### 14.4 Review identifier

Use a fresh new-generation OX review sequence such as:

```text
OX-000001
OX-000002
...
```

Review IDs are bookkeeping identifiers; cryptographic identity is carried by snapshot/request digests.

## 15. State and failure semantics

### 15.1 Conceptual live lifecycle

```text
PREPARING
→ READY
→ SENDING
→ COMPLETED | FAILED | OUTCOME_UNKNOWN
```

`SENDING` is process-local/live presentation only and is not trusted after restart.

### 15.2 Durable projection

```text
no provider attempt recorded      → READY
attempt with successful terminal  → COMPLETED
attempt with definite failure     → FAILED
attempt without trustworthy final → OUTCOME_UNKNOWN
```

Preparation failures before a provider attempt may be represented as local review failures without consuming provider authority.

### 15.3 Success criteria

A provider attempt reaches `COMPLETED` only when all required delivery evidence is durable, including:

- HTTP exchange completed under the accepted provider protocol;
- response remained within bounds;
- exact response evidence was durably persisted;
- response envelope could be decoded sufficiently to identify one assistant result;
- assistant review text is non-empty;
- `review.txt` was persisted;
- final metadata was persisted.

This validates delivery, not the correctness of OX's technical judgment.

### 15.4 Definite local/pre-network failures

Examples include:

- invalid repository/scope;
- repository outside Byte-MCP authority;
- path escape or unsupported link/junction;
- unsafe material detection;
- packet/request too large;
- missing credential;
- exact credential in provider-bound material;
- snapshot/request identity mismatch;
- local persistence failure before send authority is consumed;
- definite connect failure where request transmission is known not to have begun;
- completed provider rejection;
- complete provider response that cannot yield valid non-empty assistant text.

Pre-network failures make zero provider calls.

### 15.5 Ambiguous transmission failures

If request transmission may have begun and final provider outcome is uncertain, record `OUTCOME_UNKNOWN`.

Examples include:

- write interruption;
- read timeout;
- remote disconnect;
- absolute deadline;
- process cancellation;
- MCP/Web UI disconnect;
- process crash after transmission begins;
- response-size abort after remote interaction begins;
- local persistence failure after transmission may have begun.

For every such case:

```text
NO RETRY
NO RESUME
NO SECOND POST
```

### 15.6 Restart behavior

Restart performs no provider networking, automatic resend, automatic replay, automatic result retrieval, or authority restoration.

If a review has evidence that its provider attempt began but lacks a trustworthy final outcome, `ox_get_review()` reports `OUTCOME_UNKNOWN`.

Crash may lose convenience, but must never create new provider authority.

## 16. Response evidence ordering

Preserve canonical provider evidence before interpretation.

Normal success ordering:

```text
receive exact response bytes
→ persist response.bin
→ decode provider envelope
→ extract non-empty assistant text
→ persist review.txt
→ persist terminal COMPLETED metadata
→ return review
```

If response parsing fails after raw response evidence is already durable, retain `response.bin` unchanged for diagnosis.

Do not repair or rewrite canonical raw response evidence.

## 17. `ox_get_review` contract

`ox_get_review(review_id)` performs zero networking and zero provider activity.

Return safe bounded information such as:

```text
review_id
state
repository alias
review mode/scope summary
snapshot_sha256
request_sha256
provider/model
timestamps
transport outcome
safe byte counts
free-form review text when COMPLETED
```

Do not return through the ordinary MCP surface:

- provider credentials;
- absolute filesystem paths;
- raw snapshot contents;
- raw request body;
- raw provider envelope;
- arbitrary raw exception text.

Restricted evidence remains available locally for forensic/operator inspection.

## 18. Logging contract

Logs contain identities and closed/bounded metadata, not content.

Acceptable examples:

```text
review_id=OX-000014
state=COMPLETED
request_sha256=<digest>
response_bytes=48217
elapsed_ms=18432
```

Do not log prompt bodies, authorization data, raw provider response text, repository source contents, secret values, or arbitrary transport exception strings.

## 19. Concurrency and send authority

The synchronous product model does not require a global background worker or queue, but duplicate concurrent execution must still be impossible.

Use a bounded exclusive per-review claim/lock around send authority.

The implementation must prove that two concurrent attempts against one review identity cannot produce two provider requests.

A process crash after send authority is consumed does not release that authority.

Do not introduce a complex lease/recovery protocol unless testing proves the simple local claim model cannot satisfy these requirements; such a discovery requires architecture review before changing the design.

## 20. Integration boundary

After the rebuild, the expected active server surface contains:

```text
core Byte-MCP tools
wolfram_query
nvidia_review
nvidia_get_review
ox_review
ox_get_review
```

No V1/V2 OX execution tools, lifetime probe, continuation/revalidation, recovery, or retry tools remain.

OX runtime/configuration must load lazily so OX failure cannot prevent the core server from starting.

## 21. Implementation campaign model

This project is intentionally the first substantial Byte/Nolan build where the assistant executes a complete approved implementation plan rather than requiring human confirmation after every small file edit.

After the final specification and implementation plan are approved, one explicit implementation authorization permits the assistant to carry the codebase through all provider-free implementation slices without repeated micro-approval.

The assistant continues automatically unless:

1. implementation would contradict the approved design;
2. tests disprove an architectural assumption;
3. a security/cost/authority boundary must change;
4. a consequential boundary is reached, including runtime promotion or a live paid OX provider request.

Major implementation slices:

```text
Slice 1: archive/remove V1 + V2 and establish clean package boundary
Slice 2: scope + snapshot + exclusions + deterministic hashes
Slice 3: packet + evidence + immutable request preparation
Slice 4: OX client + one-shot synchronous provider path
Slice 5: service + ox_review + ox_get_review
Slice 6: crash/failure/security/concurrency qualification
Slice 7: operator docs + final provider-free candidate
```

## 22. Plan reconciliation checkpoints

After each major slice, reconcile implementation against this specification:

```text
What did the approved plan require?
What now exists?
What tests prove it?
Did implementation add anything not authorized?
Did an assumption change?
What remains?
```

If the implementation still matches the approved contract and tests pass, continue without additional user approval.

If it does not, stop and return for architecture review.

## 23. Required failure-aware documentation

Maintain a living OX `FAILURE_MAP.md` during implementation.

For each significant failure boundary, document:

- observable symptom;
- likely cause categories;
- first diagnostics;
- propagation path;
- safe recovery;
- data/evidence risk;
- explicit do-not-retry/do-not-delete warnings where relevant;
- related tests.

A major subsystem slice is not complete until its significant failure surfaces are represented in the failure map.

## 24. Provider-free qualification

No live OX, Z.AI, Vercel, NVIDIA, Wolfram, or other provider request is authorized during implementation or local qualification.

Use mocks and loopback HTTP servers for provider-path tests.

The test suite must prove at least:

- repository outside `/AiProjects` rejected;
- arbitrary filesystem path rejected;
- symlink/junction escape rejected;
- sensitive files excluded/rejected under policy;
- dirty/staged/untracked eligible code included correctly;
- snapshot change changes identity;
- packet uses frozen bytes only;
- full-repo oversize fails with zero provider calls;
- bounded oversize fails with zero provider calls;
- credential-in-packet fails with zero provider calls;
- request identity mismatch fails with zero provider calls;
- exactly one HTTP request maximum;
- redirect is not followed;
- definite pre-send connect failure is safely classified;
- write/read/disconnect/deadline uncertainty becomes `OUTCOME_UNKNOWN`;
- no automatic retry occurs;
- exact response is durable before review extraction;
- malformed/empty provider output never becomes `COMPLETED`;
- concurrent duplicate execution cannot produce two sends;
- restart never restores send authority;
- `ox_get_review` performs zero networking;
- public results/logs do not leak credentials or absolute local paths;
- OX imports no NVIDIA execution code;
- OX never invokes Wolfram;
- NVIDIA regression suite remains unchanged/passing;
- Wolfram regression suite remains unchanged/passing;
- core Byte-MCP read tools remain unchanged/passing;
- active MCP surface is exact.

## 25. Final provider-free gate

Before runtime promotion is even proposed, require fresh evidence from the exact candidate:

```text
python package/dependency health
compileall
Ruff lint
Ruff format check for changed Python
full pytest
OX-specific failure/security/concurrency suite
V1/V2 absence guard
NVIDIA regression suite
Wolfram regression suite
exact MCP surface test
Windows launcher/runtime qualification
clean worktree
exact candidate commit SHA
```

Also perform a final specification reconciliation:

- Was exactly the approved OX capability built?
- Is any old OX execution path still active?
- Was any unapproved tool/capability added?
- Can any provider-bearing path send more than once per review?
- Are failure semantics proven rather than assumed?
- Is the new implementation materially simpler than V1/V2?

## 26. Runtime promotion and live-call boundaries

Implementation authorization does **not** authorize runtime promotion or a paid OX provider request.

### Boundary 1 — Runtime promotion

After full provider-free qualification, present the exact candidate commit and fresh gate evidence.

Runtime promotion requires separate explicit user authorization.

Promote with OX provider activity disabled or otherwise guaranteed not to execute during deployment verification.

Verify at minimum:

- deployed exact candidate identity;
- clean runtime;
- runtime READY/active;
- exact expected MCP tool surface;
- core Byte-MCP behavior intact;
- NVIDIA behavior intact;
- Wolfram behavior intact;
- OX local/provider-free surfaces intact;
- zero provider calls during promotion verification.

### Boundary 2 — First live OX review

After provider-free runtime promotion passes, stop again.

A later explicit instruction to run an OX review authorizes exactly one review under the approval model in this document.

The live canary then performs:

```text
scope validation
→ frozen snapshot
→ packet/request identity
→ exactly one provider request
→ durable response evidence
→ free-form OX review
→ final local evidence
```

No second approval is required inside that authorized review.

If the live provider outcome is ambiguous, do not retry. Inspect durable evidence and require a separately authorized new review for any later provider call.

## 27. Acceptance criteria

The clean-room rebuild is ready for runtime-promotion review only when all of the following are true:

1. V1 and abandoned V2 execution code are archived and absent from the active runtime tree.
2. The new OX package has no runtime dependency on archived OX code.
3. The only OX MCP tools are `ox_review` and `ox_get_review`.
4. OX can review both bounded and full repository scopes under `/AiProjects`.
5. OX snapshots current eligible filesystem state including relevant dirty/untracked code.
6. Snapshot identity is deterministic and cryptographically bound to scope/inventory/content.
7. Provider packet is built from frozen bytes only.
8. Sensitive material and exact provider credentials fail closed before transmission.
9. Oversize reviews fail locally without silent truncation and without provider calls.
10. One authorized review can issue at most one outbound provider request.
11. No automatic retry/reconnect/resume can create a second provider request.
12. Ambiguous post-send failures remain `OUTCOME_UNKNOWN` and consumed.
13. Exact response evidence is durable before free-form review extraction/final success.
14. OX provider output is accepted as free-form prose without a forced findings schema.
15. `ox_get_review` is local/read-only and provider-free.
16. The evidence store is inspectable, bounded, secret-safe, and survives restart without restoring send authority.
17. NVIDIA, Wolfram, and core Byte-MCP regressions pass unchanged.
18. `FAILURE_MAP.md` covers significant implemented failure boundaries.
19. Full provider-free qualification passes on the exact final candidate.
20. No live provider call or runtime promotion occurs without its separately required authorization.

## 28. Explicit design decisions frozen by this specification

The following choices are intentional and should not be reopened during implementation without architecture review:

- Full archive-and-remove of OX V1 and abandoned V2.
- Reuse proven provider-neutral primitives where compatible.
- Keep Vercel AI Gateway → Z.AI/GLM provider route.
- OX remains a code-review specialist.
- One user approval covers one entire review lifecycle.
- No automatic retry.
- OX may review current committed, staged, unstaged, and relevant untracked code.
- OX is restricted to Byte-MCP repositories under `/AiProjects`.
- Support both bounded and full-repository reviews.
- One frozen snapshot packet; no provider tool loop.
- OX response is free-form prose, not structured findings.
- Full local evidence retention.
- Synchronous execution.
- Exactly two OX tools: `ox_review` and `ox_get_review`.
- Oversize reviews fail closed rather than truncate/summarize/split.
- Simple per-review file evidence store rather than SQLite.
- Provider-free full implementation/qualification before runtime promotion.
- Runtime promotion and first live provider request remain separate explicit authorization boundaries.

## 29. Design self-review

- **Placeholder scan:** No implementation requirement in this design depends on a TBD/TODO placeholder. Concrete file limits, timeout constants, exact model/profile constants, and exact binary/text eligibility thresholds are intentionally left for the implementation plan to derive from current provider/runtime constraints while preserving the frozen fail-closed behavior.
- **Internal consistency:** One review authorization permits one synchronous provider request maximum; no second approval, retry, worker, recovery, continuation, or provider tool loop exists elsewhere in the design.
- **Scope:** The work is large but cohesive: one OX subsystem plus archival removal and regression protection. It is suitable for one implementation campaign divided into explicit slices.
- **Ambiguity:** The provider returns natural free-form prose. Byte-MCP validates transport/protocol delivery and non-empty assistant content only; it does not interpret semantic correctness as a success criterion.
- **Isolation:** OX and NVIDIA share only provider-neutral primitives. Neither imports the other, and OX never calls Wolfram.
- **Authority:** Implementation approval does not authorize runtime promotion or live provider calls.
