# Byte-MCP OX Validation Integration — V1 Design

**Date:** 2026-08-29  
**Status:** Design approved in chat; awaiting review of this committed specification before implementation planning  
**Target repository:** `m-indsRefuge/Byte-MCP`  
**Baseline commit:** `ae154db8e0e7baeaecfa62d82d00944944353b91`

## 1. Purpose

Byte-MCP will gain a dedicated OX external-validation capability inside the existing MCP server. The capability lets Byte/ChatGPT submit bounded, immutable engineering review packets to OX (GLM-5.3-Flash), conduct evidence-backed follow-up discussion, adjudicate findings independently, and perform blind and targeted revalidation after remediation.

The integration is intentionally **OX-specific**. V1 is not a provider-agnostic model gateway, agent framework, autonomous coding system, or arbitrary remote-execution service.

The engineering loop is:

**Nolan → Byte implementation and deterministic verification → OX external validation → Byte evidence-based adjudication → remediation → deterministic regression gate → OX revalidation → Byte final technical recommendation → Nolan acceptance.**

Nolan retains final human authority over project direction, outbound repository transmission, and milestone acceptance. Byte owns technical review scope, evidence assembly under the deterministic protocol, finding adjudication, remediation, and technical recommendation. OX independently attempts to prove the implementation wrong.

## 2. V1 design principles

1. **One MCP server.** OX is a capability within Byte-MCP, not a separate server or repository.
2. **OX-specific implementation.** The integration is hardcoded for OX / GLM-5.3-Flash. No provider interfaces or multi-model abstraction are introduced.
3. **Hosted API only.** No local GLM inference path exists in V1.
4. **Read-only target repositories.** OX operations may inspect approved Git repositories but never write, patch, commit, delete, execute, or otherwise mutate them.
5. **Committed states only.** Reviews target exact Git commit SHAs, never mutable working-tree snapshots.
6. **Deterministic evidence.** Byte declares a bounded subsystem; Byte-MCP mechanically builds the mandatory review packet from a predeclared subsystem definition.
7. **Human approval before external repository transmission.** A preparation call cannot send repository content. Approval is bound to an exact manifest digest.
8. **Append-only canonical provenance.** Requests, responses, messages, lifecycle events, findings, adjudications, and revalidations remain historically inspectable.
9. **No autonomous loops.** Each outbound MCP action produces at most one provider response.
10. **No execution.** The OX subsystem runs no repository code, tests, builds, package managers, shells, or arbitrary subprocesses.
11. **Fail closed at the evidence boundary.** If required provenance cannot be persisted before transmission, nothing is sent.
12. **Existing Byte-MCP remains available without OX.** Missing or broken OX configuration must not disable the existing local read capability.
13. **No silent provider failover.** The model and provider route remain fixed to Z.AI-hosted GLM-5.3-Flash through Vercel AI Gateway.
14. **No silent retries.** Every additional provider attempt is explicit and evidenced.

## 3. Deployment architecture

Byte-MCP remains one Streamable HTTP MCP server.

```text
ChatGPT / Byte
       |
       | MCP
       v
+------------------------------------------------+
|                    Byte-MCP                    |
|                                                |
| Existing local read capability                 |
|   list_roots                                   |
|   list_directory                               |
|   search                                       |
|   fetch                                        |
|      -> FileService -> approved local roots    |
|                                                |
| OX validation capability                       |
|   ox_review                                    |
|   ox_continue                                  |
|   ox_revalidate                                |
|   ox_get_review                                |
|      -> OXReviewService                        |
|         -> approved Git repository reader      |
|         -> deterministic bundle builder        |
|         -> manifest/provenance                 |
|         -> append-only evidence store          |
|         -> message/finding validation          |
|         -> OXClient                            |
+----------------------------------|-------------+
                                   | HTTPS
                                   v
                         Vercel AI Gateway
                                   |
                     model = zai/glm-5.3-flash
                     provider allowlist = zai only
                                   |
                                   v
                                  Z.AI
                                   |
                                   v
                         GLM-5.3-Flash / OX
```

### 3.1 Capability isolation

The existing `FileService` remains responsible for Byte-MCP's current local filesystem tools. OX logic does not get added to the existing `service.py` as a catch-all.

The OX implementation lives under a dedicated package, approximately:

```text
src/byte_mcp/
├── server.py
├── service.py
├── settings.py
├── errors.py
└── ox/
    ├── __init__.py
    ├── runtime.py
    ├── settings.py
    ├── models.py
    ├── repositories.py
    ├── bundles.py
    ├── manifests.py
    ├── evidence.py
    ├── messages.py
    ├── findings.py
    ├── client.py
    └── service.py
```

Exact filenames may be reduced during implementation planning if a smaller decomposition is clearer. The service boundary is mandatory; the exact file count is not.

### 3.2 Optional OX lifecycle

Byte-MCP has two capability lifecycles:

- **Core local capability — required.** Existing Byte-MCP configuration and `FileService` validate before the server binds.
- **OX capability — optional/fail-isolated.** OX configuration may produce `AVAILABLE`, `DISABLED`, or `MISCONFIGURED` without taking down existing Byte-MCP tools.

`DISABLED` represents an intentionally absent `AI_GATEWAY_API_KEY`. `MISCONFIGURED` represents invalid OX repository/evidence configuration. Existing `list_roots`, `list_directory`, `search`, and `fetch` remain usable in either OX-unavailable state.

Startup validates local OX structure and credential presence/non-emptiness only. It does not call the provider just to validate the key. Real authentication occurs on the first outbound OX operation.

## 4. Fixed provider and credential boundary

### 4.1 Provider route

V1 uses Vercel AI Gateway only as the transport path to OX:

- OpenAI-compatible AI Gateway endpoint;
- fixed model `zai/glm-5.3-flash`;
- provider routing restricted to Z.AI only;
- no fallback to a different host;
- no model/provider parameter exposed through MCP.

If the approved Z.AI route is unavailable, the OX operation fails explicitly.

### 4.2 Credential

`AI_GATEWAY_API_KEY` is supplied only through the process environment.

It must never be committed, written to OX configuration, written to review evidence, written to Byte-MCP audit logs, returned through MCP, included in exception text, or included in serialized request/debug snapshots.

The authorization header is created only inside the narrow outbound client immediately before the HTTPS request. Automated tests use sentinel fake secrets and assert that those values never appear in persisted or returned data.

## 5. Approved repositories and immutable Git states

OX may inspect only explicitly configured local Git repositories. Public OX tools accept a repository alias, not an arbitrary filesystem path. Repository paths are validated independently of Byte-MCP's existing general roots.

Every review records an exact target commit SHA. Change reviews also record an explicit base commit SHA. Review artifacts are read from Git objects belonging to those commits, not from current working-tree contents.

V1 must not expose arbitrary Git subprocess execution. The implementation plan will choose the smallest constrained Git-reading approach that can read commits, trees, blobs, and diffs without enabling repository execution or mutation.

## 6. Deterministic subsystem definitions

A review caller may not hand-pick files at review time.

Each allowlisted repository has a predeclared, versioned subsystem registry identifying deterministic categories such as source roots/files, associated tests, boundary contracts/interfaces, required project/build/config context, and required contextual documentation.

Illustrative shape:

```json
{
  "repositories": {
    "byte-mcp": {
      "subsystems": {
        "filesystem-security": {
          "source_roots": ["src/byte_mcp/security.py", "src/byte_mcp/refs.py"],
          "test_roots": ["tests/test_security.py", "tests/test_refs.py"],
          "boundary_files": ["src/byte_mcp/errors.py", "src/byte_mcp/settings.py"],
          "context_files": ["pyproject.toml", "docs/SECURITY.md"]
        }
      }
    }
  }
}
```

This example does not lock the final subsystem taxonomy. The implementation plan will define the initial registry from the live repository.

Every prepared review records the subsystem ID, definition version, and SHA-256 of the exact definition used. Changing the definition after preparation invalidates prior approval.

V1 performs no AI-based scope inference, fuzzy test association, symbol-graph inference, or heuristic evidence trimming.

## 7. Mandatory review bundle

For the declared repository/subsystem/base/target state, Byte-MCP mechanically constructs all mandatory protocol categories:

1. repository identity and exact target/base commits;
2. exact subsystem definition and version/hash;
3. every source artifact required by that definition;
4. every associated test artifact required by that definition;
5. declared boundary/interface/configuration context;
6. a bounded deterministic repository tree;
7. exact base-to-target change evidence where a base commit exists;
8. caller-supplied deterministic verification evidence with provenance and hashes;
9. a manifest containing every transmitted artifact's logical path, category, byte length, and SHA-256.

If a mandatory artifact/category cannot be produced, preparation fails.

If the complete bundle exceeds the configured V1 bundle/context limit, Byte-MCP fails explicitly with size diagnostics. It never silently omits, summarizes, truncates, ranks, or discards required evidence.

If OX later requests source outside the approved scope, `ox_continue` cannot attach it. A justified scope expansion requires a newly prepared bundle and new human approval.

## 8. Deterministic verification evidence

Byte supplies verification evidence explicitly during review/revalidation preparation because OX-MCP itself does not execute tests/builds.

A verification record includes a stable ID, kind, command description, exit code, exact stdout/stderr or attached raw artifact, recorded timestamp, caller-supplied provenance, and SHA-256.

Byte-MCP preserves and hashes this evidence but never claims that it generated or independently verified it. Required evidence may not be fabricated, inferred, or silently omitted.

## 9. Evidence storage, append-only provenance, and concurrency

### 9.1 Storage location

OX evidence lives in a dedicated local application-data location **outside every allowlisted reviewed repository**. This is mandatory because Byte-MCP itself is expected to be a review target; conducting a review must not dirty or modify the target repository.

The implementation plan will choose a platform-appropriate user-data default and bounded override setting.

### 9.2 Evidence layout

Conceptually:

```text
<OX_EVIDENCE_ROOT>/
└── reviews/
    └── OX-000001/
        ├── review.json             # immutable review identity/preparation metadata
        ├── events.jsonl            # canonical append-only lifecycle events
        ├── manifest.json           # immutable approved packet manifest
        ├── verification/
        ├── bundles/
        ├── threads/
        │   ├── initial.jsonl
        │   ├── blind-revalidation.jsonl
        │   └── targeted-revalidation.jsonl
        ├── responses/
        ├── findings/
        ├── adjudication.jsonl      # append-only Byte adjudication events
        └── revalidations/
```

Canonical history is append-only. A derived/materialized summary cache may be rewritten atomically for efficient reads, but it is never canonical and must be reconstructible from immutable records plus `events.jsonl`.

V1 uses filesystem JSON/JSONL rather than a database.

### 9.3 Stable identities

Reviews receive stable IDs such as `OX-000001`; findings derive from a review (`OX-000001-F001`); revalidations derive from a review (`OX-000001-RV001`). IDs are references, not authentication tokens.

### 9.4 What remains immutable

Provider messages and raw responses are never rewritten. Byte adjudication is separate from OX's original claim. The evidence model preserves independently:

- what OX said;
- what evidence existed;
- what Byte concluded.

Atomic write/rename is used where needed to avoid torn immutable artifacts. Malformed/torn-record recovery must be explicit and conservative.

### 9.5 Single-process V1 and concurrent-call safety

V1 supports one Byte-MCP process owning a given OX evidence root. Multi-process shared-store operation is explicitly unsupported.

Within that process, evidence mutations and state transitions are serialized per review. ID allocation and the `PREPARED -> TRANSMITTING` claim must be atomic under the process lock. Two concurrent approval calls for the same prepared review cannot both reach the network: the first durable transition claims the attempt; the second sees a non-`PREPARED` state and fails.

This concurrency invariant is mandatory because duplicate approval races could otherwise duplicate code transmission and API spend.

## 10. Human approval and two-phase transmission

`ox_review` and `ox_revalidate` use a two-phase handshake.

### 10.1 Prepare phase

The first call validates repository, commits, subsystem, verification evidence, and size limits; constructs the packet locally; persists prepared evidence; computes the manifest digest; and returns a proposal.

It makes **zero provider/network calls**.

The proposal includes review/revalidation ID, repository/subsystem, target/base commit, objective, artifact count, total bytes, manifest SHA-256, fixed provider/model route, and `transmitted=false`.

### 10.2 Approval phase

After Nolan explicitly approves the exact proposal in ChatGPT, Byte calls the same high-level operation with the prepared ID and approval flag.

An approval-phase invocation must identify the existing prepared object; it may not simultaneously redefine repository, scope, commits, verification evidence, or other bundle-producing parameters.

Before transmission, Byte-MCP re-verifies the persisted manifest/digest and immutable target state. Any mismatch invalidates approval.

There is no one-call path that both prepares and transmits a new repository bundle.

The server cannot cryptographically prove the physical identity behind the MCP client. Enforcement is therefore layered:

- preparation can never transmit repository content;
- approval can transmit only the exact digest-bound prepared packet;
- the Byte/Nolan operating protocol permits that call only after Nolan's explicit approval;
- ChatGPT/MCP UI confirmation, when presented, is an additional safeguard rather than the sole gate.

### 10.3 What the approval covers

Approval covers the exact prepared repository bundle for that review/revalidation thread. Because the provider API may be stateless, subsequent `ox_continue` calls may need to resend the already-approved historical message context, including the original approved bundle. That retransmission is within the original scope approval.

`ox_continue` may not introduce any new repository artifact or expanded subsystem scope. New repository content requires a new preparation and approval.

A retry after `OUTCOME_UNKNOWN`, or any other explicit retry that would resend a repository bundle after an unsuccessful provider attempt, must be surfaced to Nolan and explicitly re-approved before the new attempt. There are no automatic retries.

## 11. MCP tool surface

V1 exposes exactly four OX tools.

### 11.1 `ox_review`

Starts or transmits a new review.

- New invocation: prepare only; zero network calls.
- Approval invocation: references an existing prepared review and sends exactly that packet.
- `approve=true` without a valid `PREPARED` review is rejected.

### 11.2 `ox_continue`

Continues the technical review process for an already transmitted review and has two explicit modes while remaining one MCP tool:

- **`message` mode:** append one Byte message, perform at most one provider request, preserve exactly one returned provider response, and maintain provider-native message order. The request may replay already-approved historical context as required by the API but cannot add new repository artifacts.
- **`adjudicate` mode:** append one or more structured Byte adjudication events locally, with zero provider calls. This records finding state/evidence/rationale without inventing a fifth public MCP tool.

The two modes are mutually exclusive in a single invocation. `adjudicate` records an engineering decision but does not alter or rewrite OX's original response.

### 11.3 `ox_revalidate`

Creates and conducts revalidation against a new committed remediation state.

- First invocation prepares only and returns a new digest-bound revalidation proposal.
- Approved invocation transmits that exact prepared state.
- Blind mode starts a genuinely fresh OX conversation with no original findings/remediation narrative foregrounded.
- After the blind pass, a targeted completeness pass may use the same already-approved remediation bundle and explicitly add the relevant original finding and Byte adjudication/remediation evidence. It does not silently add new repository files.
- If targeted completeness requires repository material outside the approved revalidation bundle, a new preparation/approval is required.

### 11.4 `ox_get_review`

Reads local review state and never contacts the provider. It may expose bounded views such as summary, findings, thread, manifest, adjudication, attempts, and revalidation without multiplying the public tool count.

## 12. MCP annotations

Existing local tools retain their current read-only/idempotent/local semantics.

OX tools do not inherit that annotation object blindly:

- `ox_get_review` is read-only and has no external side effect;
- `ox_continue` in adjudication mode has a local evidence side effect;
- `ox_review`, `ox_continue` in message mode, and `ox_revalidate` may consume API service and transmit already-approved data.

The exact annotation representation will be confirmed against the pinned MCP SDK during implementation planning. If one static annotation set must cover all modes of a tool, it must describe the most consequential supported behavior rather than understate it.

## 13. Review, attempt, revalidation, and finding states

Review lifecycle and finding lifecycle remain distinct.

### 13.1 Review/attempt lifecycle

Core progression:

```text
PREPARED
  -> TRANSMITTING
      -> REVIEWED              (attempt COMPLETED)
      -> FAILED                (attempt NOT_SENT or REJECTED)
      -> OUTCOME_UNKNOWN       (delivery/processing cannot be known)

REVIEWED
  -> continuation turns (review remains REVIEWED)
  -> REVALIDATION_PREPARED
      -> REVALIDATION_TRANSMITTING
          -> BLIND_REVALIDATED
              -> targeted completeness when required
                  -> REVALIDATED
          -> FAILED / OUTCOME_UNKNOWN
```

A blind pass may be sufficient only when the protocol marks targeted completeness unnecessary. Otherwise final `REVALIDATED` requires the targeted completeness step.

Impossible transitions are rejected. Failure never erases prepared evidence. Retry is a new explicit attempt with its own identity/evidence and, where repository retransmission occurs after an unsuccessful/unknown attempt, renewed human approval.

### 13.2 Finding lifecycle

A finding may progress through:

- `RAISED`
- `REPRODUCED`
- `CONFIRMED`
- `DISPROVED`
- `DEFERRED` / `UNRESOLVED`
- `REMEDIATED`
- `REVALIDATED`

Failure to reproduce is not equivalent to disproving. `DISPROVED` requires evidence satisfying the stated disproof condition or otherwise decisively refuting the claim.

## 14. OX messages and structured findings

### 14.1 Native message handling

The client uses the provider's native OpenAI-compatible message representation rather than inventing a parallel conversation protocol. Byte-MCP owns persistence/provenance; the API owns ordinary role/message semantics.

Each thread is stored append-only in exact order. Blind revalidation uses a fresh message sequence rather than asking OX to pretend prior context does not exist.

### 14.2 Structured finding contract

Formal OX reviews are instructed to return a strict, versioned finding schema containing at least:

- finding ID/key;
- category;
- severity;
- confidence;
- affected location;
- falsifiable claim;
- evidence;
- reproduction recipe;
- expected behavior;
- observed/predicted behavior;
- disproof condition;
- recommended investigation.

Where the fixed Vercel/Z.AI route reliably supports native JSON response mode, the client requests it and validates the returned JSON against the OX-MCP schema.

The raw provider response is always preserved. OX-MCP never silently rewrites malformed findings. Invalid output becomes an explicit protocol-format failure; a later explicit continuation may ask OX to resubmit correctly.

Private model reasoning/chain-of-thought is not part of the engineering evidence contract. Evidence depends on visible claims, reproducible/cited evidence, structured findings, and Byte's documented adjudication rationale.

## 15. Outbound API semantics

### 15.1 One narrow client

Only the dedicated OX client may make Vercel/Z.AI HTTP calls. It does not decide scope, grant approval, read arbitrary files, or mutate repository/evidence state outside its request/response responsibility.

### 15.2 Non-streaming V1

V1 uses non-streaming requests. One call yields one complete response before validation/persistence. Streaming and partial-response recovery are deferred.

### 15.3 Attempt identity before transmission

Every provider attempt receives durable identity before network transmission, including attempt ID, provider request ID where supported, review/revalidation ID, manifest SHA-256 where repository content is involved, message-history SHA-256, and timestamp.

A `TRANSMISSION_INTENT` lifecycle event is persisted before touching the network. Failure to persist it aborts transmission.

### 15.4 No automatic retries

There are no automatic retries for timeout, rate limit, overload, or other provider failure. Retrying is an explicit MCP operation/attempt. If the prior outcome was unknown or the retry would resend repository content after an unsuccessful attempt, renewed Nolan approval is required as defined in Section 10.3.

### 15.5 Attempt outcomes

Attempts distinguish at least:

- `NOT_SENT`
- `REJECTED`
- `COMPLETED`
- `OUTCOME_UNKNOWN`

A timeout/interruption after possible transmission is never falsely recorded as definitely not sent.

### 15.6 Bounds

The client uses bounded connect/read/write/pool timeouts and a bounded provider output-token ceiling. Safe ranges are server-side configuration/constants, not unbounded MCP parameters.

### 15.7 Usage telemetry

Successful responses preserve available prompt/input, completion/output, total, and cached-token usage metadata. V1 does not calculate currency cost because pricing can change.

## 16. Error model

OX failures are normalized into Byte-MCP domain errors rather than leaking raw HTTP, filesystem, Git, or serialization exceptions. Expected categories include:

- `OXUnavailableError`
- `OXConfigurationError`
- `OXApprovalError`
- `OXRepositoryError`
- `OXScopeError`
- `OXBundleError`
- `OXEvidenceError`
- `OXAuthenticationError`
- `OXPermissionError`
- `OXRequestError`
- `OXContextLimitError`
- `OXRateLimitError`
- `OXQuotaError`
- `OXProviderUnavailableError`
- `OXTransportError`
- `OXProtocolError`
- `OXFindingValidationError`

Safe provider status/code metadata may be retained. Secrets, authorization headers, and unsafe raw diagnostics are never returned through MCP.

## 17. Evidence/audit ordering

For an approved transmission:

```text
construct prepared packet
  -> persist immutable PREPARED evidence
  -> Nolan approval in Byte/Nolan workflow
  -> re-verify manifest digest
  -> atomically claim PREPARED -> TRANSMITTING
  -> persist TRANSMISSION_INTENT event
  -> perform one provider call
  -> persist exact response / attempt outcome
  -> validate and persist findings result
  -> append review lifecycle event
  -> write normal Byte-MCP audit entry
  -> return result to Byte
```

If the provider succeeds but durable response persistence fails, the system does not report a clean evidenced review. It returns an evidence/recovery error and retains whatever durable attempt state exists without inventing certainty.

The existing Byte-MCP audit and OX evidence have distinct purposes:

- Byte-MCP audit answers **what operation was requested/performed**.
- OX evidence answers **what exact engineering review was prepared/transmitted, what OX returned, and how findings were adjudicated/revalidated**.

## 18. Testing strategy

Implementation follows TDD. Automated tests never use the real Vercel/Z.AI API or Nolan's credential.

### 18.1 Unit contracts

Cover settings/runtime states, repository allowlist, IDs, subsystem-definition hashing, immutable Git reads, bundle construction, manifest hashing, findings schema, messages, evidence/event persistence, adjudication events, and legal state transitions.

### 18.2 Security invariants

Tests must prove:

- no API key persistence/leakage;
- no repository escape;
- no working-tree substitution for committed Git objects;
- no unapproved transmission;
- no digest-mismatch transmission;
- no approval invocation that changes bundle-defining parameters;
- no arbitrary continuation attachment/scope expansion;
- no execution/subprocess path through supported OX operations;
- no automatic retry;
- no provider fallback outside Z.AI;
- no evidence writes inside a reviewed repository;
- two concurrent approval calls cannot both reach the provider;
- a retry requiring renewed approval cannot transmit before that approval.

A fake OX client deliberately fails if reached, allowing forbidden transitions to prove they stop before the network boundary.

### 18.3 Review protocol

Cover:

- prepare makes zero HTTP calls;
- approve sends the exact prepared digest;
- `ox_continue(message)` preserves provider-native order and cannot expand scope;
- stateless replay resends only previously approved repository material;
- `ox_continue(adjudicate)` records local adjudication and performs zero HTTP calls;
- one outbound MCP action produces at most one response;
- blind revalidation uses fresh context;
- targeted completeness links intended findings/remediation evidence without adding unapproved files;
- malformed findings are preserved and surfaced as protocol failures.

### 18.4 Failure/recovery

Cover authentication/permission rejection, quota/rate limit, context-too-large, overload, deterministic `NOT_SENT`, `OUTCOME_UNKNOWN`, corrupt/torn evidence, response-persistence failure, and OX-disabled/misconfigured startup isolation.

### 18.5 Regression/integration

The full existing Byte-MCP suite remains green. With `AI_GATEWAY_API_KEY` absent, all existing local tools work while OX operations return a controlled unavailable state.

CI passes on supported Windows and Linux environments with existing lint/compile/dependency gates preserved.

## 19. Live acceptance sequence

Real credits are not used during automated development.

After deterministic and CI gates are green, perform one deliberately small non-sensitive canary through the real server:

1. prepare a tiny review;
2. inspect its manifest/digest;
3. obtain Nolan's explicit approval;
4. perform one real `zai/glm-5.3-flash` request through Vercel with Z.AI-only routing;
5. verify exact response/evidence persistence;
6. verify structured-finding behavior;
7. verify usage metadata;
8. verify no secret leakage;
9. call `ox_get_review`;
10. perform one explicit `ox_continue(message)` turn;
11. record one local `ox_continue(adjudicate)` event;
12. confirm all existing Byte-MCP local tools still work.

Before transmitting private repository content through Vercel/Z.AI, the live gate also includes a current review of relevant gateway/provider data-handling terms. The first canary does not require private source code.

## 20. Dogfood review and V1 completion gate

The first serious external target is the committed Byte-MCP OX subsystem itself.

1. Byte implements and deterministically verifies the OX subsystem.
2. The implementation is committed.
3. Byte-MCP prepares the OX-subsystem packet from that immutable commit.
4. Nolan approves the exact manifest.
5. OX performs the independent review.
6. Byte adjudicates every finding against the committed repository/evidence and records those adjudications locally.
7. Confirmed findings are remediated through the normal TDD workflow.
8. Full regression verification passes and the remediation is committed.
9. Byte-MCP prepares revalidation against that commit; Nolan approves the new manifest.
10. OX performs blind revalidation.
11. OX performs targeted completeness where required.
12. Byte issues the final technical recommendation.
13. Nolan performs final human acceptance.

V1 is not complete until:

- design/spec approved;
- TDD implementation complete;
- existing Byte-MCP regression suite green;
- new OX suite green;
- lint/compile/dependency gates green;
- Windows and Linux CI green;
- no real credential in repository/history/evidence;
- prepare/approve digest binding demonstrated;
- concurrent duplicate approval prevented;
- OX-disabled mode leaves core Byte-MCP functional;
- small live API canary succeeds;
- persistent multi-turn OX conversation demonstrated;
- local Byte adjudication recording demonstrated;
- blind revalidation demonstrated;
- OX independently reviews the committed OX subsystem;
- Byte adjudicates all findings;
- confirmed defects repaired and regression-tested;
- OX revalidates remediation;
- Nolan accepts the subsystem.

## 21. Explicit V1 non-goals

V1 does not include:

- provider/model abstraction;
- local GLM inference;
- autonomous model-to-model loops;
- arbitrary shell/test execution;
- OX write/patch/commit/delete authority;
- arbitrary filesystem access;
- automatic provider retries;
- streaming provider responses;
- database-backed evidence;
- automatic monetary cost calculation;
- AI-generated subsystem membership;
- silent bundle trimming/summarization;
- multi-process shared evidence-store support;
- background worker queues;
- a separate OX-MCP server or tunnel.

## 22. Deferred possibilities

Only after evidence demonstrates a need should later versions consider sandboxed independent test reproduction, richer deterministic dependency expansion, database indexing, evidence rotation/archive tooling, stronger cryptographic human-approval identity mechanisms, OX calibration metrics, known-defect canaries, historical meta-review, or alternative validators.

None should complicate V1 without demonstrated need.

## 23. Final architectural contract

Byte-MCP V1 will contain an isolated OX validation subsystem that sends only explicitly approved, deterministic, hash-bound review bundles from exact committed states of allowlisted repositories to fixed `zai/glm-5.3-flash` through Vercel AI Gateway restricted to Z.AI routing.

The subsystem does not execute repository code or mutate reviewed repositories. It preserves canonical append-only provenance outside every reviewed repository, serializes concurrent state mutations, uses provider-native message semantics and strict structured findings, records Byte adjudication separately, supports evidence-backed multi-turn discussion plus blind/targeted revalidation, and performs no hidden loops, failover, or automatic retries.

Byte remains responsible for technical engineering and evidence-based adjudication. OX remains an independent external validator. Nolan remains the human authority for outbound repository transmission and final project acceptance.
