# Byte-MCP OX Validation Integration — V1 Design

**Date:** 2026-08-29  
**Status:** Design approved in chat; awaiting review of this committed specification before implementation planning  
**Target repository:** `m-indsRefuge/Byte-MCP`  
**Baseline commit:** `ae154db8e0e7baeaecfa62d82d00944944353b91`

## 1. Purpose

Byte-MCP will gain a dedicated OX external-validation capability inside the existing MCP server. The capability exists to let Byte/ChatGPT submit bounded, immutable engineering review packets to OX (GLM-5.3-Flash), conduct evidence-backed follow-up discussion, adjudicate OX findings independently, and perform blind and targeted revalidation after remediation.

The integration is intentionally **OX-specific**. V1 is not a provider-agnostic model gateway, agent framework, autonomous coding system, or arbitrary remote-execution service.

The engineering loop is:

**Nolan → Byte implementation and deterministic verification → OX external validation → Byte evidence-based adjudication → remediation → deterministic regression gate → OX revalidation → Byte final technical recommendation → Nolan acceptance.**

Nolan retains final human authority over project direction, outbound code-transmission approval, and milestone acceptance. Byte owns technical review scope, evidence assembly under the deterministic protocol, finding adjudication, remediation, and technical recommendation. OX independently attempts to prove the implementation wrong.

## 2. Design principles

V1 follows these principles:

1. **One MCP server.** OX is a capability within Byte-MCP, not a separate server or repository.
2. **OX-specific implementation.** The integration is hardcoded for OX / GLM-5.3-Flash. No provider interfaces or multi-model abstraction are introduced.
3. **Hosted API only.** No local GLM inference path exists in V1.
4. **Read-only target repositories.** OX-MCP operations may inspect approved Git repositories but never write, patch, commit, delete, execute, or otherwise mutate them.
5. **Committed states only.** Reviews target exact Git commit SHAs, never a mutable working-tree snapshot.
6. **Deterministic evidence.** Byte declares a bounded subsystem; Byte-MCP mechanically builds the mandatory review packet from a predeclared subsystem definition.
7. **Human approval before external transmission.** Repository content cannot leave the machine on a preparation call. Approval is bound to an exact manifest digest.
8. **Append-only provenance.** Requests, responses, manifests, messages, findings, adjudications, and revalidations are preserved as evidence rather than rewritten.
9. **No autonomous loops.** Each outbound MCP operation produces at most one provider response.
10. **No execution.** The OX subsystem runs no repository code, tests, builds, package managers, shells, or arbitrary subprocesses.
11. **Fail closed at the evidence boundary.** If required provenance cannot be persisted before transmission, nothing is sent.
12. **Existing Byte-MCP remains available without OX.** Missing or broken OX configuration must not disable the existing local read capability.

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

The existing `FileService` remains responsible for Byte-MCP's current local filesystem tools. OX logic does not get added to `service.py` as a general catch-all.

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

Exact filenames may be adjusted during implementation planning if a smaller decomposition is clearer, but the separation between existing local file access and OX validation remains mandatory.

### 3.2 Optional OX lifecycle

Byte-MCP has two capability lifecycles:

- **Core local capability — required.** Existing Byte-MCP configuration and `FileService` must validate before the server binds.
- **OX capability — optional/fail-isolated.** OX configuration may produce `AVAILABLE`, `DISABLED`, or `MISCONFIGURED` without taking down the existing Byte-MCP tools.

`DISABLED` represents an intentionally absent `AI_GATEWAY_API_KEY`. `MISCONFIGURED` represents invalid OX repository/evidence configuration. Existing `list_roots`, `list_directory`, `search`, and `fetch` remain usable in either OX-unavailable state.

Startup validates only local OX structure and the presence/non-emptiness of the credential. It does not make a network request merely to prove that the key is accepted. Real authentication occurs on the first outbound OX operation.

## 4. Provider and credential boundary

### 4.1 Fixed provider route

V1 uses Vercel AI Gateway only as the transport path to the fixed OX model:

- OpenAI-compatible AI Gateway endpoint.
- Fixed model: `zai/glm-5.3-flash`.
- Provider routing restricted to Z.AI only.
- No automatic fallback to a different model host.
- No user-selectable model/provider parameter in the MCP tool surface.

If Z.AI is unavailable through the approved route, the OX operation fails explicitly.

### 4.2 API key

The credential is supplied as `AI_GATEWAY_API_KEY` through the process environment.

It must never be:

- committed to Git;
- written to an OX config file;
- written to review evidence;
- written to Byte-MCP audit logs;
- returned through MCP;
- included in exception text;
- included in debug representations or serialized request snapshots.

The authorization header is constructed only inside the narrow outbound client immediately before the HTTPS call. Automated tests use sentinel fake credentials and assert that those values never appear in persisted or returned data.

## 5. Approved repositories and immutable Git states

### 5.1 Repository allowlist

OX may inspect only explicitly configured local Git repositories. There is no general filesystem browser exposed to OX and no arbitrary path parameter accepted by the public OX tools.

Each repository has a stable alias that resolves to a configured local Git repository path. Repository paths are validated and constrained independently of the existing Byte-MCP general root aliases.

### 5.2 Committed states only

Every review records an exact target commit SHA. Where change review is required, it also records an explicit base commit SHA.

Review artifacts are read from the Git object state belonging to those commits, not from the current working-tree contents. Uncommitted changes therefore cannot silently replace the material approved for review.

V1 must not execute Git commands through an arbitrary subprocess interface. The implementation plan should choose the smallest dependable, constrained Git-reading approach that can read commits, trees, blobs, and diffs without enabling repository code execution or mutation.

## 6. Deterministic subsystem definitions

A review caller may not supply an arbitrary hand-picked list of files.

Each allowlisted repository has a predeclared, versioned subsystem registry. A subsystem definition identifies deterministic categories such as:

- source roots/files;
- associated test roots/files;
- boundary/interfaces/contracts;
- required project/build/config context;
- required contextual documentation.

Example shape:

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

The example does not lock the final Byte-MCP subsystem taxonomy; the implementation plan will define the initial registry based on the live repository.

Every prepared review records the subsystem ID, subsystem-definition version, and SHA-256 of the exact definition used. Changing the definition after preparation invalidates the prior approval.

V1 performs no AI-based scope inference, fuzzy test association, symbol-graph inference, or heuristic evidence trimming.

## 7. Mandatory review bundle

For the declared repository/subsystem/base/target state, Byte-MCP mechanically constructs a packet containing all mandatory protocol categories:

1. Repository identity and exact target/base commits.
2. Exact subsystem definition and its version/hash.
3. Every source artifact required by the subsystem definition.
4. Every associated test artifact required by the definition.
5. Declared boundary/interface/configuration context.
6. A bounded deterministic repository tree for structural context.
7. Exact base-to-target change evidence where a base commit is supplied.
8. Caller-supplied deterministic verification evidence, with provenance and hashes.
9. A manifest containing every transmitted artifact's logical path, category, byte length, and SHA-256.

If a mandatory artifact/category cannot be produced, preparation fails.

If a complete deterministic bundle exceeds the configured V1 bundle/context limit, Byte-MCP fails explicitly with a `BundleTooLarge`-class domain error and useful size diagnostics. It must never silently omit, summarize, truncate, rank, or discard evidence to fit a provider limit.

If OX later requests a file outside the approved scope, `ox_continue` cannot attach it. A justified scope expansion requires a newly prepared bundle and new human approval.

## 8. Deterministic verification evidence

OX-MCP does not execute tests or builds. Byte supplies deterministic verification evidence explicitly during review/revalidation preparation.

A verification record contains fields such as:

- verification ID;
- kind (`pytest`, `ruff`, build, custom, etc.);
- command description;
- exit code;
- exact stdout/stderr or attached raw evidence artifact;
- recorded timestamp;
- caller-supplied provenance;
- SHA-256.

Byte-MCP preserves and hashes this evidence but never claims that it generated or independently verified it. Required evidence may not be fabricated, inferred, or silently omitted.

## 9. Evidence storage and provenance

### 9.1 Evidence must live outside reviewed repositories

OX evidence must be stored in a dedicated local application-data location that is **outside every allowlisted reviewed repository**. This is mandatory because Byte-MCP itself is expected to be a review target; storing evidence under `Byte-MCP/data/ox/` would mutate the repository being reviewed.

A platform-appropriate default should be chosen during implementation (for example, a Byte-MCP application-data directory under the user's profile) and may be overridden by a bounded configuration value.

No review operation may modify its target repository merely by occurring.

### 9.2 Evidence layout

Conceptually:

```text
<OX_EVIDENCE_ROOT>/
└── reviews/
    └── OX-000001/
        ├── review.json
        ├── manifest.json
        ├── verification.json
        ├── bundles/
        ├── threads/
        │   ├── initial.jsonl
        │   ├── blind-revalidation.jsonl
        │   └── targeted-revalidation.jsonl
        ├── responses/
        ├── findings/
        ├── adjudication/
        └── revalidations/
```

V1 uses transparent JSON/JSONL filesystem evidence rather than a database. A database is deferred until there is demonstrated indexing/query pressure.

### 9.3 Stable identities

Reviews receive stable identifiers such as `OX-000001`; findings derive from the review (`OX-000001-F001`); revalidations derive from the review (`OX-000001-RV001`). These identifiers are references, not authentication tokens.

### 9.4 Append-only records

Provider messages and raw responses are never rewritten. Byte adjudication is stored separately from OX's original claim.

The evidence model preserves three independent facts:

- what OX said;
- what evidence existed;
- what Byte concluded.

The evidence store should be append-oriented. V1 may use atomic write/rename where needed to prevent torn records. Recovery behavior for malformed/torn local records must be explicit in the implementation plan.

## 10. Human approval and two-phase transmission

`ox_review` and `ox_revalidate` use a two-phase handshake.

### 10.1 Prepare phase

The first call validates the repository, immutable commits, subsystem, required verification evidence, and bundle limits; constructs the full packet locally; persists the prepared evidence; calculates the manifest digest; and returns a proposal.

It makes **zero provider/network calls**.

The proposal contains at least:

- review/revalidation ID;
- repository and subsystem;
- target/base commit;
- review objective;
- artifact count and total bytes;
- manifest SHA-256;
- fixed provider/model route;
- `transmitted = false`.

### 10.2 Approval phase

After Nolan explicitly approves the exact prepared proposal in the ChatGPT conversation, Byte calls the same high-level operation with the prepared ID and approval flag.

Before transmission, Byte-MCP re-verifies the persisted manifest/digest and immutable target state. If anything differs, approval is invalidated and transmission is refused.

There is no supported one-call path that both prepares and transmits a new repository bundle.

The server cannot cryptographically prove the physical identity of the human behind the MCP client. Therefore the enforcement is layered:

- Byte-MCP guarantees no first preparation call can transmit repository content;
- Byte-MCP guarantees the second call can transmit only the exact digest-bound prepared packet;
- the Byte/Nolan operating protocol requires the second call only after Nolan's explicit approval;
- any ChatGPT/MCP UI confirmation is an additional safeguard, not the sole enforcement mechanism.

## 11. MCP tool surface

V1 exposes exactly four high-level OX operations.

### 11.1 `ox_review`

Starts a new review.

- New-review invocation: local prepare only; zero network calls.
- Approved invocation using an existing prepared review ID: verifies approval binding and sends exactly the prepared bundle.
- `approve=true` without a valid prepared review is rejected.

### 11.2 `ox_continue`

Continues an already transmitted review thread.

- Loads the exact provider-native message history.
- Appends one Byte message.
- Performs at most one provider request and records at most one provider response.
- Cannot add arbitrary repository files or expand the approved scope.
- Fails for reviews that have never been transmitted.

### 11.3 `ox_revalidate`

Creates a revalidation against a new committed remediation state.

- First call prepares only and returns a new digest-bound revalidation proposal.
- Second approved call transmits that exact prepared state.
- `blind` mode starts a genuinely fresh OX conversation with no original findings/remediation narrative foregrounded.
- Targeted completeness review explicitly receives the relevant original finding and remediation evidence only after the blind pass.

### 11.4 `ox_get_review`

Reads local review state and never contacts the provider.

It may support bounded views such as summary, findings, thread, manifest, adjudication, and revalidation, without multiplying the public MCP tool count.

## 12. MCP annotations

The existing local tools retain their existing read-only/idempotent/local semantics.

OX tools must not inherit the same annotation object blindly:

- `ox_get_review` is read-only and has no external side effect.
- `ox_review`, `ox_continue`, and `ox_revalidate` can create local evidence, consume external API service, and transmit approved data. Their annotations must truthfully describe those side effects.

The exact supported annotation fields will be confirmed against the pinned MCP SDK during implementation.

## 13. Review and finding state machines

Review lifecycle and finding lifecycle are distinct.

### 13.1 Review lifecycle

Core states include:

```text
PREPARED
  -> TRANSMITTING
      -> REVIEWED
      -> FAILED / OUTCOME_UNKNOWN as appropriate

REVIEWED
  -> continuation turns (state remains REVIEWED)
  -> REVALIDATION_PREPARED
      -> REVALIDATION_TRANSMITTING
          -> REVALIDATED
          -> FAILED / OUTCOME_UNKNOWN as appropriate
```

Impossible transitions are rejected explicitly.

Provider failure must not erase previously persisted prepared evidence. Retry is never automatic; a later retry is an explicit MCP operation with its own attempt evidence.

### 13.2 Finding lifecycle

A finding may progress through:

- `RAISED`
- `REPRODUCED`
- `CONFIRMED`
- `DISPROVED`
- `DEFERRED` / `UNRESOLVED`
- `REMEDIATED`
- `REVALIDATED`

Failure to reproduce is not equivalent to disproving. `DISPROVED` requires evidence satisfying the finding's disproof condition or otherwise decisively refuting the claim.

## 14. OX message and finding contract

### 14.1 Native message handling

The client uses the provider's native OpenAI-compatible `messages` representation rather than inventing a parallel conversation protocol. OX-MCP owns persistence/provenance; the API owns ordinary role/message semantics.

Each thread is stored append-only in exact order. Blind revalidation uses a fresh message sequence rather than telling OX to pretend prior context does not exist.

### 14.2 Structured findings

Formal OX reviews are instructed to return a strict, versioned finding schema. Expected fields include:

- finding ID;
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

Where the fixed API route reliably supports native JSON response mode, the client should request it and then validate the result against the OX-MCP schema.

The raw provider response is always preserved. OX-MCP validates but never silently rewrites or repairs malformed findings. Invalid structured output becomes an explicit protocol-format failure; OX may be asked in a later explicit continuation turn to resubmit correctly.

Private model reasoning/chain-of-thought is not part of the engineering evidence contract. Evidence depends on visible claims, cited/reproducible evidence, structured findings, and Byte's documented adjudication rationale.

## 15. Outbound API semantics

### 15.1 One narrow client

Only the dedicated OX client module may make OX/Vercel HTTP calls. It does not decide scope, grant approval, read arbitrary files, or mutate evidence outside its defined request/response responsibilities.

### 15.2 Non-streaming V1

V1 uses non-streaming requests only. One request yields one complete response before validation/persistence. Streaming and partial-response recovery are deferred.

### 15.3 Attempt identity before transmission

Every outbound attempt receives durable identity before network transmission, including:

- attempt ID;
- provider request ID where supported;
- review/revalidation ID;
- manifest SHA-256;
- message-history SHA-256;
- creation timestamp.

The `TRANSMISSION_INTENT` record must be persisted before the network is touched. Failure to persist that intent aborts transmission.

### 15.4 No automatic retries

V1 performs no automatic provider retry for timeout, rate limit, overload, or other failure. Retries could duplicate cost and make external state ambiguous. A retry is a new explicit MCP operation/attempt.

### 15.5 Ambiguous outcomes

Attempt outcomes distinguish at least:

- `NOT_SENT`
- `REJECTED`
- `COMPLETED`
- `OUTCOME_UNKNOWN`

A timeout or transport interruption after possible request transmission must not be falsely recorded as definitely rejected/not sent.

### 15.6 Bounded network/output behavior

The client uses bounded connect/read/write/pool timeouts and a bounded provider output-token ceiling. Values are server-side configuration/constants with safe ranges, not arbitrary unbounded MCP parameters.

### 15.7 Usage telemetry

Successful provider responses preserve available token-usage metadata such as input/prompt, output/completion, total, and cached-token counts. V1 does not calculate currency cost because pricing can change.

## 16. Error model

OX failures are normalized into Byte-MCP domain errors rather than leaking raw HTTP/transport/filesystem exceptions. Expected categories include:

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

For an approved transmission, ordering is strict:

```text
construct prepared packet
  -> persist PREPARED evidence
  -> obtain human approval externally in the Byte/Nolan workflow
  -> verify manifest digest
  -> persist TRANSMISSION_INTENT
  -> perform provider call
  -> persist exact provider response / attempt outcome
  -> validate and persist structured findings result
  -> update review lifecycle record
  -> write normal Byte-MCP audit entry
  -> return result to Byte
```

If a provider call succeeds but durable response persistence fails, the system must not report a clean evidenced review. It returns an evidence/recovery error and preserves as much durable attempt state as possible without inventing certainty.

The existing Byte-MCP audit and OX evidence have separate purposes:

- Byte-MCP audit answers **what operation was requested/performed**.
- OX evidence answers **what exact engineering review was prepared/transmitted, what OX returned, and how the findings were adjudicated/revalidated**.

## 18. Testing strategy

Implementation follows TDD. Automated tests never use the real Vercel/Z.AI API or Nolan's credential.

### 18.1 Unit contracts

Cover OX settings/runtime states, repository allowlist, stable IDs, subsystem-definition hashing, immutable Git reads, bundle construction, manifest hashing, findings schema, messages, evidence persistence, and legal state transitions.

### 18.2 Security invariants

Tests must prove:

- no API key persistence or leakage;
- no repository escape;
- no working-tree substitution for committed Git objects;
- no unapproved transmission;
- no digest-mismatch transmission;
- no arbitrary continuation attachment/scope expansion;
- no execution/subprocess path through supported OX operations;
- no automatic retry;
- no provider fallback outside Z.AI;
- no evidence writes inside the reviewed repository.

A fake OX client should deliberately fail if reached, allowing tests to verify that forbidden transitions fail before the network boundary is invoked.

### 18.3 Review protocol

Cover:

- prepare makes zero HTTP calls;
- approve sends the exact prepared digest;
- `ox_continue` preserves provider-native message ordering;
- one MCP outbound operation produces at most one provider response;
- blind revalidation uses a fresh context;
- targeted revalidation links the intended original finding/remediation evidence;
- malformed findings are preserved and surfaced as protocol failures rather than repaired silently.

### 18.4 Failure/recovery

Cover authentication rejection, permission rejection, quota/rate limit, context-too-large, provider overload, deterministic `NOT_SENT` failures, ambiguous `OUTCOME_UNKNOWN` transport cases, corrupt evidence, response-persistence failure, and OX-disabled/misconfigured startup isolation.

### 18.5 Regression/integration

The full existing Byte-MCP suite must remain green. With `AI_GATEWAY_API_KEY` absent, all existing local tools must continue to work while OX operations return a controlled unavailable state.

CI must pass on the repository's supported Windows and Linux environments, with lint/compile/dependency checks preserved.

## 19. Live acceptance sequence

Real credits are not used during automated development.

After implementation and all deterministic/CI gates are green, perform one deliberately small non-sensitive live canary through the real Byte-MCP server:

1. prepare a tiny approved review;
2. inspect the manifest/digest;
3. obtain Nolan's explicit approval;
4. perform one real `zai/glm-5.3-flash` request through Vercel with Z.AI-only routing;
5. verify exact response/evidence persistence;
6. verify structured finding behavior;
7. verify usage metadata;
8. verify no secret leakage;
9. run `ox_get_review`;
10. perform one explicit `ox_continue` turn;
11. confirm the existing Byte-MCP local tools still operate afterward.

Before transmitting private repository content through Vercel/Z.AI, the live gate must also include a current review of the relevant provider/gateway data-handling terms. The first canary does not require private source code.

## 20. Dogfood review and V1 completion gate

The first serious external review target should be the committed Byte-MCP OX subsystem itself.

Sequence:

1. Byte implements and deterministically verifies the OX subsystem.
2. The implementation is committed.
3. OX-MCP prepares the deterministic OX-subsystem packet from that committed state.
4. Nolan approves the exact manifest.
5. OX performs the independent review.
6. Byte adjudicates every finding against the live committed repository and deterministic evidence.
7. Confirmed findings are remediated using the normal engineering/TDD workflow.
8. Full regression verification passes.
9. OX performs blind revalidation against the remediation commit.
10. OX performs targeted completeness review where required.
11. Byte issues the final technical recommendation.
12. Nolan performs final human acceptance.

V1 is not complete until:

- the design/spec is approved;
- TDD implementation is complete;
- existing Byte-MCP regression tests remain green;
- the new OX suite is green;
- lint/compile/dependency gates are green;
- Windows CI is green;
- Linux CI is green;
- no real credential appears in repository/history/evidence;
- the prepare/approve digest binding is demonstrated;
- OX-disabled mode leaves Byte-MCP core functional;
- the small live API canary succeeds;
- persistent multi-turn OX conversation is demonstrated;
- blind revalidation is demonstrated;
- OX independently reviews the OX subsystem;
- Byte adjudicates all findings;
- confirmed defects are repaired and regression-tested;
- OX revalidates the remediation;
- Nolan accepts the subsystem.

## 21. Explicit V1 non-goals

V1 does not include:

- provider/model abstraction;
- local GLM inference;
- autonomous model-to-model loops;
- arbitrary shell or test execution;
- OX write/patch/commit/delete authority;
- arbitrary filesystem access;
- automatic provider retries;
- streaming provider responses;
- database-backed evidence;
- automatic monetary cost calculation;
- AI-generated subsystem membership;
- silent bundle trimming or summarization;
- multi-process worker queues;
- a separate OX-MCP server or tunnel.

## 22. Deferred possibilities

Only after evidence demonstrates a need should later versions consider:

- sandboxed independent test reproduction;
- richer deterministic Git/symbol dependency expansion;
- database indexing for large review histories;
- evidence rotation/archive tooling;
- stronger cryptographic human-approval identity mechanisms;
- structured metrics for OX calibration/accuracy;
- known-defect canaries and historical meta-review;
- alternative validator models.

None of these should complicate V1 unless implementation evidence makes them necessary.

## 23. Final architectural contract

Byte-MCP V1 will contain an isolated OX validation subsystem that sends only explicitly approved, deterministic, hash-bound review bundles from exact committed states of allowlisted repositories to the fixed `zai/glm-5.3-flash` model through Vercel AI Gateway restricted to Z.AI routing.

The subsystem does not execute repository code or mutate reviewed repositories. It preserves append-only provenance outside all reviewed repositories, uses provider-native message semantics and strict structured findings, supports evidence-backed multi-turn discussion plus blind/targeted revalidation, and performs no hidden model loops or automatic retries.

Byte remains responsible for technical engineering and evidence-based adjudication. OX remains an independent external validator. Nolan remains the human authority for outbound repository transmission and final project acceptance.
