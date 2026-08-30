# Byte-MCP Wolfram Co-Engineer Integration — V1 Design

**Date:** 2026-08-30  
**Status:** Design approved in chat; awaiting review of this committed specification before implementation planning  
**Target repository:** `m-indsRefuge/Byte-MCP`  
**Baseline commit:** `aaf015c02e606c9f8e2a1efb76ac193258f45ced`

## 1. Purpose

Byte-MCP will gain a separately governed Wolfram capability that gives Byte a computational co-engineer while preserving OX as the primary independent adversarial validator.

The organizational model is fixed:

```text
                         Nolan
                  Human project authority
                           |
                           v
                          Byte
                 Lead Engineer / Orchestrator
                    /                 \
                   /                   \
                  v                     v
             Wolfram                    OX
            Co-Engineer         Adversarial Validator
          + computation          + independent review
          + technical analysis
          + debugging support
          + fallback validation
```

The two external specialists never communicate directly. All routing, escalation, evidence selection, adjudication, and conflict resolution is mediated by Byte.

The intended engineering loop is:

**Nolan → Byte engineering ↔ Wolfram co-engineering as useful → deterministic verification → OX adversarial validation → Byte evidence-based adjudication → optional Wolfram fallback investigation where needed → remediation → regression verification → OX revalidation → Byte recommendation → Nolan acceptance.**

Wolfram is not a replacement for OX and does not become the acceptance gate merely because it assisted with the implementation.

## 2. Existing Byte-MCP boundary remains authoritative

Byte-MCP V1.1 is a frozen four-tool, read-only filesystem capability. The Wolfram integration is a new separately reviewed capability and must not silently weaken the accepted filesystem boundary.

Existing tools remain unchanged:

```text
list_roots
list_directory
search
fetch
```

The Wolfram subsystem must be isolated from `FileService` and must not introduce repository write, rename, move, delete, shell, registry, arbitrary process-control, arbitrary HTTP, or unrestricted-path authority.

A missing, disabled, rate-limited, or broken Wolfram configuration must not disable the existing Byte-MCP read capability or the OX subsystem.

## 3. Provider communication invariant

OX and Wolfram never communicate directly.

Forbidden flows include:

```text
OX -> Wolfram
Wolfram -> OX
OX response automatically forwarded to Wolfram
Wolfram response automatically forwarded to OX
shared provider session
provider-to-provider callback
provider-selected escalation
```

All cross-specialist activity is mediated by Byte:

```text
OX finding / uncertainty
        |
        v
       Byte
        |
        +-- adjudicate directly
        |
        +-- optionally formulate a separate Wolfram question
                    |
                    v
                 Wolfram
                    |
                    v
                   Byte
```

If an OX issue motivates a Wolfram investigation, local provenance may record that the Wolfram engagement was triggered by an OX unresolved finding, but the raw OX conversation is not automatically transmitted. Byte independently reformulates the technical problem to reduce anchoring and preserve provider separation.

## 4. Role distinction

### 4.1 Byte

Byte owns:

- architecture and implementation strategy;
- repository interpretation;
- routing decisions;
- evidence selection;
- Wolfram problem formulation;
- OX review scope under the accepted OX protocol;
- technical adjudication;
- remediation decisions;
- final engineering recommendation.

### 4.2 Wolfram

Wolfram is primarily a co-engineer used during design, implementation, debugging, verification, and targeted fallback investigation.

Typical uses include:

- symbolic and numerical computation;
- equation solving;
- algorithm analysis;
- invariant and reachability questions;
- state-space calculations;
- expected-output and test-oracle generation;
- boundary-case derivation;
- statistics and probability;
- scientific and engineering calculations;
- optimization;
- independent checking of Byte hypotheses;
- bounded code comprehension and debugging where the LLM API proves useful;
- fallback technical investigation when OX cannot resolve a question.

Wolfram may disagree with Byte. Useful outputs include support, contradiction, partial support, insufficient evidence, counterexamples, and alternative solutions.

### 4.3 OX

OX remains the primary independent adversarial validator. Its role is unchanged by this design.

Wolfram participation in implementation does not make subsequent Wolfram checking independent in the same sense as an OX review.

## 5. Phase 1 implementation strategy: qualify the LLM API first

Nolan has obtained a Wolfram|Alpha AppID specifically for the **LLM API**.

Phase 1 therefore starts with that API and does not assume that the Wolfram GPT experience, Wolfram Language AgentTools, Wolfram AI Access, or the Full Results API are equivalent to the LLM API.

The first implementation objective is deliberately narrow:

1. securely integrate the Wolfram|Alpha LLM API;
2. expose a bounded `wolfram_query` capability;
3. run a fixed engineering qualification campaign;
4. measure actual coding/debugging usefulness;
5. assign a capability profile from evidence;
6. expand the Wolfram tool surface only if the qualification result justifies it.

This sequencing avoids building local Wolfram Engine sandbox infrastructure or rich review orchestration before the LLM API demonstrates that those investments are useful.

## 6. Phase 1 external architecture

```text
ChatGPT / Byte
       |
       | MCP
       v
+------------------------------------------------+
|                    Byte-MCP                    |
|                                                |
| Existing filesystem capability                 |
|   list_roots / list_directory / search / fetch |
|                                                |
| Existing OX subsystem                          |
|   independent adversarial validation           |
|                                                |
| Wolfram capability                             |
|   wolfram_query                                |
|      -> outbound data policy                   |
|      -> quota policy                           |
|      -> WolframLLMClient                       |
|      -> audit metadata                         |
+----------------------------------|-------------+
                                   | HTTPS GET
                                   v
                    Wolfram|Alpha LLM API
```

The Wolfram client is a narrow fixed-purpose outbound adapter, not a generic HTTP client.

## 7. Credential and endpoint boundary

### 7.1 Credential

The Wolfram|Alpha AppID is a secret.

The target operating model is to reuse the accepted Byte-MCP launcher credential pattern and store it machine-locally under the Byte-MCP private application state, conceptually:

```text
%USERPROFILE%\.byte-mcp\credentials\wolfram-appid.dpapi
```

The exact launcher wiring is implementation-plan detail, but the security contract is fixed:

- Windows user-bound DPAPI storage for the deployed Windows profile;
- never committed;
- never returned through MCP;
- never included in logs, evidence, exceptions, or audit payloads;
- never accepted as an MCP argument;
- never placed in a repository configuration file;
- never forwarded to OX;
- never inherited by a future local Wolfram compute process unless separately justified.

### 7.2 Fixed provider route

The caller cannot choose the endpoint, host, method, authorization header, or credential.

Phase 1 permits only the documented Wolfram|Alpha LLM API route. Authentication is attached inside the narrow client using the provider-supported bearer-token mechanism so the AppID does not need to appear in the request URL.

There is no arbitrary HTTP MCP tool and no caller-supplied URL.

## 8. `wolfram_query` contract

Phase 1 exposes one new Wolfram MCP tool:

```text
wolfram_query(
    input: str,
    max_chars: int | None = None
)
```

The exact MCP schema may be refined during implementation planning, but the following contract is mandatory:

- `input` is bounded;
- `max_chars` is server-bounded and cannot request unbounded output;
- the AppID is never caller-visible;
- one MCP invocation performs at most one provider request;
- there are no automatic retries;
- raw provider transport details are normalized before returning to Byte;
- the result preserves provider identity and a Wolfram result/attribution link where supplied;
- failure is explicit rather than converted into a guessed answer.

Illustrative response shape:

```json
{
  "status": "success",
  "provider": "Wolfram|Alpha",
  "result": "...",
  "result_url": "...",
  "truncated": false,
  "usage": {
    "local_period_count": 12,
    "soft_limit": 1800
  }
}
```

The implementation plan will confirm the exact response fields against the live API before coding.

## 9. Response and quota bounds

Initial response policy:

- default result ceiling: 6,800 characters;
- maximum result ceiling: 6,800 characters unless live API verification demonstrates a reason to change it;
- minimum caller-requested result size, if exposed: bounded server-side;
- input size: bounded server-side;
- automatic retries: zero.

The current non-commercial allowance is treated as an external provider constraint, not a guarantee baked permanently into domain semantics.

Byte-MCP maintains a conservative local monthly soft budget for operational discipline. Initial target:

```text
provider-advertised allowance: 2000 calls/month
local soft ceiling:            1800 calls/month
reserved buffer:                200 calls/month
```

The local counter is not billing authority. Provider-side usage remains authoritative.

No hidden retry may consume another API call. Any second attempt is a new explicit operation.

## 10. Error model

Expected Wolfram errors are normalized into Byte-MCP domain failures rather than leaking unsafe raw HTTP details.

At minimum the design distinguishes:

- unavailable/disabled configuration;
- authentication failure;
- invalid request;
- uninterpretable input;
- rate limit/quota limit;
- timeout;
- provider/server failure;
- DNS/TLS/transport failure;
- malformed/unexpected provider response;
- outbound policy denial.

A timeout or provider error never becomes fabricated Wolfram evidence.

## 11. Outbound context and data policy

Wolfram queries may be retained by the provider under its service practices, so Byte-MCP sends the minimum context necessary.

### 11.1 Tier A — safe by default

Byte may send bounded non-sensitive material such as:

- equations;
- mathematical expressions;
- algorithms expressed abstractly or as pseudocode;
- synthetic test data;
- numerical verification cases;
- sanitized error messages;
- acceptance criteria;
- invariants and constraints;
- bounded non-sensitive code excerpts;
- logical repository-relative paths where useful;
- generic architectural descriptions.

### 11.2 Tier B — bounded engineering evidence

Where code/debugging qualification or later co-engineering requires real source material, Byte selects only the minimum bounded evidence necessary.

External providers receive logical repository-relative paths, not backing machine paths.

The intended pattern is:

```text
Repository evidence
       |
       v
      Byte
       |
       +-- select minimum relevant material
       +-- sanitize
       +-- formulate technical question
       v
    Wolfram
```

Byte does not send an entire repository merely because a smaller question can answer the engineering uncertainty.

### 11.3 Tier C — automatic denial

The outbound policy denies known or suspected secrets, including:

- API keys;
- access tokens;
- passwords;
- private keys;
- OAuth credentials;
- authentication headers;
- session cookies;
- DPAPI credential blobs;
- connection strings containing secrets;
- environment-secret values;
- tunnel credentials;
- OX credentials;
- the Wolfram AppID itself.

Machine-identifying absolute paths and unrelated private repository material are also removed or denied by default.

A policy denial occurs before network transmission and records that no provider request occurred.

### 11.4 Human approval model

Wolfram's normal co-engineering calls do **not** inherit OX's mandatory two-phase per-review human approval handshake.

Nolan's approval of this capability and its locked outbound policy authorizes Byte to invoke Tier A and bounded Tier B Wolfram calls during ordinary engineering when they remain inside the implemented size, repository, sanitization, and secret-denial constraints.

This distinction is intentional: Wolfram is an active co-engineer, while OX is a controlled independent review gate.

The rules are:

- Tier A may be sent without per-call human approval;
- bounded Tier B may be sent without per-call human approval when it satisfies the locked outbound policy;
- Tier C is denied and cannot be transmitted through the normal Wolfram capability;
- a future Wolfram feature that materially expands repository scope, data sensitivity, provider authority, or transmission size requires a new design/security gate rather than silently reusing this authorization;
- the later `wolfram_review` lifecycle, if unlocked by qualification, must not blindly copy OX's two-phase approval semantics unless a separate requirement justifies doing so.

Nolan retains authority over project direction, capability expansion, and final acceptance without becoming responsible for approving every routine co-engineering query.

## 12. OX isolation in Wolfram context

The no-provider-communication rule is enforced in data handling as well as process flow.

Wolfram is not automatically given:

- raw OX prompts;
- raw OX responses;
- OX hidden/provider context;
- OX review transcripts;
- OX confidence values;
- OX provider metadata.

If OX produces an unresolved technical issue, Byte independently reformulates the engineering question for Wolfram.

Local provenance may retain a link such as:

```text
route_reason = OX_FALLBACK
source_finding_id = <local OX finding reference>
```

That linkage does not require transmitting the OX conversation to Wolfram.

## 13. Routing policy

Byte owns all routing decisions.

### 13.1 Byte first

If Byte can establish a repository fact reliably from code, tests, or deterministic evidence, no Wolfram call is required merely because the service exists.

### 13.2 LLM API use

Phase 1 uses `wolfram_query` when external Wolfram computational knowledge, interpretation, or measured coding/debugging support is useful.

Likely use cases include:

- mathematical verification;
- algorithms;
- boundary conditions;
- state-space questions;
- test oracles;
- scientific/engineering knowledge;
- real-world quantities;
- bounded code/debugging tasks if qualification demonstrates competence.

### 13.3 OX timing

OX remains outside the normal co-engineering loop until the controlled validation stage.

Wolfram may participate proactively during engineering. OX remains the independent adversarial acceptance-path validator.

### 13.4 Fallback validation

If OX cannot resolve a finding, or identifies a defect but cannot establish the correct solution, Byte may deliberately consult Wolfram.

That Wolfram engagement is recorded as `FALLBACK_VALIDATION`, not independent adversarial validation.

## 14. Evidence adjudication

Conflicts are never resolved by provider voting.

Evidence hierarchy is qualitative rather than model-prestige based:

```text
reproducible evidence
    > formal/computational evidence
    > deterministic test evidence
    > well-supported reasoning
    > unsupported provider opinion
```

A concrete Wolfram counterexample may outweigh an unsupported Byte or OX opinion. An OX-reproduced security defect may outweigh a mathematically correct but irrelevant Wolfram calculation.

Byte adjudicates the evidence in repository context.

## 15. Wolfram engagement provenance

Every Wolfram operation records metadata sufficient to understand why it occurred without persisting secrets or indiscriminately caching provider content.

Recommended metadata includes:

- provider: `wolfram`;
- purpose: `COENGINEERING` or `FALLBACK_VALIDATION`;
- route reason;
- request ID;
- input fingerprint;
- timestamp;
- result status;
- response length;
- duration;
- local quota counter;
- optional related repository/bundle hash;
- optional local OX finding reference when route reason is `OX_FALLBACK`.

Suggested route reasons:

```text
DIRECT_COMPUTATION
KNOWLEDGE_LOOKUP
VERIFY_BYTE_HYPOTHESIS
GENERATE_TEST_ORACLE
SEARCH_COUNTEREXAMPLE
DEBUG_NUMERICAL_BEHAVIOR
CODE_COMPREHENSION
OX_FALLBACK
OTHER_BOUNDED_REASON
```

Raw AppID, authorization headers, secret-bearing input, and unrelated repository content are never audit fields.

## 16. Provider-result retention

Phase 1 must not introduce a permanent cache of Wolfram API content.

The transport layer keeps provider output only as long as needed to return and use the current result. Persistent engineering records may retain Byte-authored conclusions, hashes, provenance, benchmark scores, and bounded derived findings as permitted by the applicable terms, but the system does not build a copied Wolfram response corpus.

Attribution/result links returned by Wolfram are preserved where applicable.

The implementation plan must perform a current terms review before the first live qualification campaign and encode only behaviors that are compatible with those terms.

## 17. Target Wolfram review surface after qualification

Nolan's desired end-state is tool parity with the accepted OX public lifecycle plus Wolfram's unique query capability.

The accepted OX design currently exposes:

```text
ox_review
ox_continue
ox_revalidate
ox_get_review
```

If the LLM API qualification supports broader engineering use, the Wolfram target surface becomes:

```text
wolfram_review
wolfram_continue
wolfram_revalidate
wolfram_get_review
wolfram_query
```

The Wolfram review tools should mirror OX lifecycle semantics where doing so improves operational consistency, while preserving different organizational meaning.

### 17.1 `wolfram_review`

Creates a bounded Wolfram co-engineering or fallback-review engagement.

It is not automatically considered independent validation.

### 17.2 `wolfram_continue`

Adds one bounded Byte follow-up and performs at most one Wolfram provider request. It may not silently import OX conversation history or unrelated repository material.

### 17.3 `wolfram_revalidate`

Rechecks a remediation or proposition when useful. If Wolfram materially contributed to the solution, provenance marks the revalidation as non-independent.

It cannot silently replace the OX adversarial revalidation gate.

### 17.4 `wolfram_get_review`

Reads local Wolfram engagement state and never contacts the provider.

### 17.5 Staging rule

These four review-lifecycle tools are **not automatically implemented in Phase 1** merely because they are the target architecture. They are unlocked only if qualification evidence shows the LLM API is useful enough for bounded engineering review/debugging.

This is the main YAGNI gate in the design.

## 18. LLM API capability qualification gate

The LLM API begins as an unqualified specialist.

The initial benchmark campaign uses approximately 30 primary calls across ten task families, with at most five deliberate follow-up calls unless evidence justifies stopping earlier.

### 18.1 Task families

```text
WA-01  Pure computation
WA-02  Symbolic / invariant verification
WA-03  Algorithm analysis
WA-04  Python code comprehension
WA-05  Bug diagnosis
WA-06  Test-case generation
WA-07  Expected-output / oracle generation
WA-08  State-machine reasoning
WA-09  Architecture constraint analysis
WA-10  Adversarial claim checking
```

The benchmark includes both straightforward and subtle examples. Some code samples are correct so false-positive behavior is measurable.

### 18.2 Ground truth

Each benchmark task has an established ground truth or explicit adjudication condition before the provider result is scored.

The scoring process distinguishes correctness from persuasive wording.

### 18.3 Scoring

Each response is scored 0-4 on:

- correctness;
- specificity;
- evidence/reasoning quality;
- engineering usefulness;
- unsupported-claim discipline.

Maximum score: 20.

Classification:

```text
18-20  EXCELLENT
14-17  USEFUL
10-13  PARTIAL
 5-9   WEAK
 0-4   NOT_USEFUL
```

Hard failure labels are recorded separately:

```text
UNINTERPRETABLE
API_ERROR
TIMEOUT
UNSUPPORTED_CLAIM
FACTUALLY_WRONG
```

### 18.4 Coding-specific checks

Code/debugging tasks also record:

```text
defect_found
root_cause_correct
location_correct
fix_correct
tests_useful
invented_facts
```

### 18.5 Independence during qualification

Where practical, Byte solves selected tasks before seeing Wolfram's result so the campaign can compare:

```text
Byte only
Wolfram only
Byte + Wolfram
```

The main product question is whether adding Wolfram materially improves Byte, not whether Wolfram wins a generic model benchmark.

OX and Wolfram results remain isolated if overlapping samples are used.

## 19. Capability profiles

Qualification assigns one evidence-based profile.

### Profile A — Broad Co-Engineer

Strong computation plus useful code comprehension, debugging, and test reasoning.

Result: unlock the broader Wolfram engagement lifecycle and route suitable engineering work proactively.

### Profile B — Computational Co-Engineer

Excellent computation and algorithmic assistance; generic code review is less reliable.

Result: retain strong Wolfram role focused on computation, invariants, algorithms, test oracles, and targeted debugging.

### Profile C — Specialist Calculator

Reliable computational results but poor engineering interpretation.

Result: keep `wolfram_query` narrowly routed; do not add broad review tooling.

### Profile D — Not Worth Integrating Broadly

No material engineering improvement.

Result: retain at most occasional bounded query access; do not build additional subsystem complexity.

## 20. Minimum threshold for broad co-engineering authority

The proposed qualification threshold for calling the LLM API a genuine broad engineering co-engineer is:

```text
overall benchmark average >= 14/20
coding/debugging root-cause correctness >= 70%
unsupported/invented technical claims <= 10%
measurable Byte+Wolfram improvement in >= 1 meaningful task family
```

Failure to meet that threshold does not make Wolfram useless. It narrows the role to the task families supported by evidence.

## 21. Deferred local Wolfram Engine

A local Wolfram Engine remains a promising later capability but is **not Phase 1 scope**.

If qualification or later engineering evidence shows a need for deterministic local symbolic/numerical execution beyond the LLM API, a separate design/implementation gate may add a constrained `wolfram_compute` runtime.

That later gate must account for Wolfram's documented evaluator authority, including potential filesystem, environment, network, and process access.

The accepted direction, if implemented later, is:

- dedicated sandboxed local kernel rather than unsandboxed session mode;
- no raw unrestricted evaluator exposed through remote MCP;
- allowlisted computational expression vocabulary;
- fresh kernel per computation;
- scrubbed environment;
- no repository mount by default;
- bounded runtime/input/output;
- no intended network authority;
- no general shell/process capability;
- explicit security acceptance tests.

None of this complexity is introduced until Phase 1 evidence demonstrates a need.

## 22. Full Results API

The Wolfram|Alpha Full Results API is deferred.

Its richer pod/statistics/graph/result structure may be useful later, but this design does not assume that it provides stronger coding intelligence than the LLM API.

A Full Results AppID is not required for Phase 1. It is added only if a concrete use case requires the richer output structure.

## 23. Testing strategy

Implementation follows TDD.

Automated tests use fake credentials and mocked transport. They never consume Nolan's real Wolfram quota.

### 23.1 Unit contracts

Cover:

- Wolfram availability/settings states;
- DPAPI-facing credential abstraction without real secret fixtures;
- fixed endpoint and auth-header construction;
- query/input/output bounds;
- local quota accounting;
- outbound policy allow/deny behavior;
- path sanitization;
- response normalization;
- error classification;
- audit/provenance metadata;
- zero automatic retry behavior.

### 23.2 Security invariants

Tests must prove:

- the AppID is never persisted in repository/config/audit/evidence/returned payloads;
- caller cannot choose arbitrary URL, method, or authorization header;
- secret-like content is denied before the transport is reached;
- absolute backing-machine paths are not transmitted through supported bounded evidence paths;
- OX raw content is not automatically forwarded;
- denied requests make zero HTTP calls;
- one MCP invocation makes at most one provider request;
- no automatic retry occurs after timeout/rate limit/provider failure;
- Wolfram failure does not disable existing Byte-MCP filesystem tools;
- Wolfram failure does not alter OX provider routing or state.

A fake client that fails if reached should be used for policy-denial tests.

### 23.3 Qualification harness

Benchmark fixtures, ground truth, scoring records, and campaign summaries are deterministic and versioned.

The harness must not silently change prompts or scoring criteria midway through a campaign.

Real provider calls occur only in the explicit live qualification gate.

### 23.4 Regression

The full existing Byte-MCP suite remains green. Existing filesystem and OX behavior remains unchanged when Wolfram is disabled or misconfigured.

## 24. Live acceptance sequence

After deterministic implementation and regression gates are green:

1. confirm the Wolfram credential is stored through the approved machine-local mechanism;
2. verify existing Byte-MCP tools remain functional;
3. run one non-sensitive pure-computation canary;
4. verify attribution/result metadata;
5. verify audit metadata contains no raw credential;
6. deliberately exercise one controlled error path;
7. confirm no automatic retry occurred;
8. run the fixed LLM API capability qualification campaign;
9. score every response against predeclared ground truth;
10. assign the evidence-based capability profile;
11. decide whether broader `wolfram_review` lifecycle tools are justified;
12. only then design/implement any required expansion.

## 25. Explicit V1 non-goals

Phase 1 does not include:

- Full Results API integration;
- local Wolfram Engine installation or sandbox runtime;
- Wolfram AI Access / LLM Kit dependency;
- general hosted-model gateway abstraction;
- arbitrary HTTP access;
- unrestricted Wolfram Language evaluation;
- repository write authority;
- shell/process/registry/computer-use authority;
- direct OX-Wolfram communication;
- automatic provider escalation;
- automatic retries;
- provider-result cache;
- autonomous multi-model loops;
- treating Wolfram as the independent acceptance validator;
- implementing broad review tools before qualification justifies them.

## 26. Final architectural contract

Byte-MCP will add Wolfram as a separately governed computational co-engineer while preserving OX as the independent adversarial validator and Nolan as final human authority.

Phase 1 integrates only the Wolfram|Alpha LLM API using Nolan's existing LLM API AppID through a narrow fixed HTTPS client. The AppID remains machine-local and secret. Outbound payloads are minimized, sanitized, secret-screened, bounded, and never provide arbitrary HTTP or filesystem authority. Calls are single-attempt, quota-aware, auditable by metadata, and fail explicitly.

OX and Wolfram never communicate directly. Byte controls every routing and fallback decision. Wolfram evidence is interpreted in repository context and conflicts are resolved by evidence rather than provider voting.

The LLM API must earn broader engineering authority through a fixed qualification campaign. Only if measured coding/debugging performance supports it will Byte-MCP add Wolfram equivalents of the accepted OX lifecycle (`wolfram_review`, `wolfram_continue`, `wolfram_revalidate`, `wolfram_get_review`). The local Wolfram Engine and Full Results API remain deferred until demonstrated need justifies their additional security and implementation complexity.
