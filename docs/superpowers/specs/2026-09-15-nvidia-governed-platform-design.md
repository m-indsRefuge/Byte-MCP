# NVIDIA Governed Platform Design

**Date:** 2026-09-15  
**Project:** Byte-MCP  
**Status:** Approved  
**Scope:** NVIDIA provider platform completion  
**Predecessors:** NVIDIA-01 transport, NVIDIA-02 live canary, NVIDIA-03 routine code review, NVIDIA-04 governed model selection

## 1. Purpose

Byte-MCP already has a functioning NVIDIA provider integration. NVIDIA-02 proved live provider connectivity with `nvidia/nemotron-3.5-lightning-30b-a3b`, and NVIDIA-03 established a governed code-review workflow with immutable requests, explicit approval, append-only evidence, and exactly-once provider execution.

NVIDIA-04 extends that architecture from a single hard-coded review model to governed model selection.

The next phase is not an API connectivity repair.

Its purpose is to turn the existing NVIDIA integration into a mature, routine provider platform comparable in operational fluency to Byte-MCP's Wolfram integration.

The completed NVIDIA platform will expose two deliberately different user-facing surfaces:

1. `nvidia_query` — a lightweight, everyday inference surface.
2. `nvidia_review` / `nvidia_get_review` — the existing evidence-heavy, approval-gated review surface.

Both surfaces will share a common governed NVIDIA core while preserving their different risk and evidence requirements.

---

## 2. Design Goals

The completed NVIDIA integration must provide:

- routine access to approved NVIDIA-hosted models;
- a simple one-call inference path for normal reasoning and coding work;
- a separate formal review path for consequential repository review;
- one authoritative model registry;
- friendly model aliases at the MCP boundary;
- exact provider model identities internally;
- deterministic model profiles;
- typed and operationally useful errors;
- lazy credential loading;
- bounded requests and responses;
- explicit provenance;
- no hidden retries;
- no silent fallback;
- no dynamic model substitution;
- provider-free offline qualification;
- separately authorized live qualification;
- auditable model maturity states;
- straightforward addition of future NVIDIA models.

A successful final architecture should make adding a future NVIDIA-hosted model primarily a matter of:

**profile → tests → offline qualification → live qualification**

rather than creating another bespoke provider integration.

---

## 3. Non-Goals

This phase will not implement:

- autonomous model selection;
- dynamic `/v1/models` discovery in runtime execution;
- automatic routing based on task classification;
- automatic retries;
- automatic model fallback;
- silent provider substitution;
- arbitrary model IDs supplied by callers;
- retry-on-rate-limit behavior;
- review execution without explicit approval;
- persistent conversation state for `nvidia_query`;
- a second heavyweight evidence lifecycle for ordinary queries;
- exposure of credentials in logs, evidence, manifests, responses, or audit metadata.

The platform may evolve toward more sophisticated routing later, but such behavior must be introduced as a separate governed feature rather than emerging implicitly from the provider layer.

---

## 4. High-Level Architecture

The NVIDIA provider will become one shared platform with two execution surfaces.

```text
                         Byte-MCP
                            │
                 ┌──────────┴──────────┐
                 │                     │
          nvidia_query            nvidia_review
        lightweight path          governed path
                 │                     │
                 └──────────┬──────────┘
                            │
                    Shared NVIDIA Core
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
     Model Profiles      Runtime          Transport
      / allowlist       / service        / errors
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                 NVIDIA OpenAI-compatible API
```

The two surfaces share infrastructure but not lifecycle semantics.

`nvidia_query` is optimized for routine use.

`nvidia_review` is optimized for reproducibility, authorization, and durable evidence.

---

## 5. Shared NVIDIA Core

The provider must have one authoritative shared core responsible for:

- provider identity;
- NVIDIA endpoint configuration;
- credential acquisition;
- governed model registry;
- alias resolution;
- model execution profiles;
- canonical request construction;
- provider transport;
- response size limits;
- response parsing;
- typed failure classification;
- safe metadata extraction.

Existing modules such as `chat.py`, `settings.py`, `registry.py`, `review_protocol.py`, and the provider infrastructure should be evolved or reorganized around this boundary rather than duplicated.

The review subsystem may add stricter logic above the shared core, but it must not maintain an independent competing definition of NVIDIA model identity.

---

## 6. Governed Model Registry

There must be one authoritative registry of NVIDIA models that Byte-MCP is permitted to use.

The initial governed model set is:

### Lightning

Alias: `lightning`

Provider model ID: `nvidia/nemotron-3.5-lightning-30b-a3b`

Surfaces:
- query enabled;
- review enabled.

### DeepSeek V4 Pro

Alias: `deepseek-v4-pro`

Provider model ID: `deepseek-ai/deepseek-v4-pro-0813`

Surfaces:
- query enabled;
- review enabled after required qualification.

The registry must distinguish model identity, provider model ID, friendly alias, surface enablement, query execution profile, review execution profile, and qualification status.

Callers must never provide an arbitrary provider model ID directly to a public MCP tool. They provide a governed alias, and the runtime resolves the alias locally to the exact provider identity.

---

## 7. Surface-Specific Profiles

Model identity and execution profile are separate concepts.

A model may require different request controls for ordinary inference and formal review. Profiles may define bounded values such as temperature, top-p, maximum output tokens, seed, thinking controls, and surface-specific provider options.

Execution controls must be deterministic and owned by the registry. The MCP caller must not be allowed to override arbitrary sampling or provider parameters during normal operation.

---

## 8. `nvidia_query`

### 8.1 Purpose

`nvidia_query` is the lightweight general NVIDIA inference surface.

Typical use cases include code reasoning, architecture analysis, implementation critique, alternative solution generation, structured reasoning, model comparison, technical explanation, and bounded general-purpose inference.

### 8.2 Proposed MCP Contract

Conceptually:

```text
nvidia_query(
    input,
    model=None
)
```

If `model` is omitted, the governed default query model is used. The initial preferred default is `deepseek-v4-pro`. Lightning remains explicitly selectable when a faster alternative is desired.

### 8.3 Query Execution Flow

```text
MCP invocation
      │
      ▼
validate input
      │
      ▼
resolve alias
      │
      ▼
validate query-enabled profile
      │
      ▼
construct canonical request
      │
      ▼
load credential
      │
      ▼
mark provider start
      │
      ▼
ONE provider request
      │
      ▼
validate response
      │
      ▼
bound output
      │
      ▼
return response + metadata
```

Validation and model resolution happen before credential loading. No provider call may occur for an invalid request or unknown model.

### 8.4 Query Result

A successful query should return a bounded structured result containing at least:

- model;
- provider model ID;
- response;
- request SHA-256;
- finish reason.

Where available and safe, it may also return provider request ID, response byte count, and duration metadata.

---

## 9. `nvidia_review`

The review path retains the strict lifecycle already established by NVIDIA-03 and NVIDIA-04.

The following invariants remain mandatory:

- review packet remains model-neutral;
- model is selected only during PREPARE;
- model must be review-enabled;
- provider model ID is frozen at PREPARE;
- execution profile is frozen at PREPARE;
- request body is canonical;
- request SHA is immutable;
- approval requires exact expected SHA;
- approval cannot specify or alter model;
- transmission cannot specify or alter model;
- exactly one provider request is permitted per approved attempt;
- no automatic retry;
- no model fallback;
- ambiguous post-start outcomes block replay;
- evidence remains append-only.

`nvidia_get_review` remains the bounded local evidence-reading surface.

---

## 10. Model Neutrality and Request Identity

Repository review evidence must remain independent from provider choice.

For the same repository packet, the packet identity remains the same while the provider request identity must differ when the selected model or execution profile differs.

Therefore:

```text
packet_sha(L) = packet_sha(D)
request_sha(L) != request_sha(D)
```

This allows model comparison without contaminating repository evidence.

---

## 11. Post-PREPARE Immutability

After a review is prepared, the selected model becomes immutable.

Approval remains conceptually:

```text
review_id
expected_request_sha256
approve=true
```

Approval must not accept model alias, provider model ID, endpoint, sampling parameters, fallback configuration, or retry model.

Transmission similarly must not expose model selection. Any model change requires a new preparation identity.

---

## 12. Error Model

Both query and review surfaces should use one shared NVIDIA failure vocabulary where appropriate.

Recommended categories:

```text
INVALID_REQUEST
MODEL_NOT_ALLOWED
MODEL_NOT_ENABLED
CREDENTIAL_UNAVAILABLE
AUTHENTICATION_FAILED
RATE_LIMITED
PROVIDER_REJECTED
TRANSPORT_FAILED
RESPONSE_INVALID
RESPONSE_TOO_LARGE
```

Errors should contain enough information to identify what failed, which model was involved, whether failure occurred locally or at NVIDIA, whether a provider request started, whether automatic retry occurred, and whether making a fresh invocation is safe.

Automatic retry is always false unless a future explicitly governed feature changes that contract.

---

## 13. Credential Handling

Credential loading must be lazy.

The credential must not be required for model registry validation, alias resolution, request validation, canonical request construction, request hashing, review PREPARE, review retrieval, offline qualification, or local runtime inspection.

Credential access occurs only immediately before provider-bound execution.

Credentials must never appear in provider request evidence, review packets, review manifests, audit metadata, exception strings, MCP responses, qualification receipts, or persistent logs.

---

## 14. Retry and Fallback Policy

The provider performs no hidden retry.

One invocation corresponds to at most one provider request.

No alternate model is silently attempted. No automatic fallback exists. No retry-on-rate-limit behavior exists. No provider SDK retry policy may bypass this contract.

---

## 15. Dynamic Model Discovery

The live execution path must not depend on NVIDIA `/v1/models`.

Runtime authorization is based solely on the governed local registry. Adding a model is a code/configuration and qualification event.

---

## 16. Audit Metadata

`nvidia_query` should record lightweight bounded operational metadata rather than durable review evidence.

Recommended metadata includes timestamp, surface, model alias, provider model ID, request SHA-256, provider-start state, HTTP status where available, finish reason, request/response byte counts, duration, and outcome category.

The ordinary query path should not silently persist complete prompt and response bodies merely for observability.

---

## 17. Runtime Readiness

The NVIDIA integration should provide a provider-free readiness/qualification mechanism capable of reporting runtime state, configured endpoint, default query alias, enabled query and review models, credential presence, request builder status, response bounds status, review evidence status, and expected versus actual MCP surfaces.

The intended public MCP surface is:

```text
nvidia_query
nvidia_review
nvidia_get_review
```

Additional NVIDIA MCP tools require a demonstrated agent-facing use case.

---

## 18. Qualification Architecture

NVIDIA qualification is separated into four layers:

1. unit qualification;
2. contract qualification;
3. offline qualification;
4. explicit live qualification.

Unit and contract tests must cover alias resolution, registry integrity, execution profiles, canonical request construction, response parsing, error classification, credential boundaries, response limits, metadata construction, query invariants, and existing review invariants.

---

## 19. Offline Qualification

The complete NVIDIA subsystem must be qualifiable without an NVIDIA credential, network access, or a provider request.

Offline qualification verifies model registry consistency, alias uniqueness, deterministic profiles and requests, credential absence from serialized artifacts, local rejection before credential loading, review manifest allowlisting, absence of automatic retry/fallback/runtime discovery, NVIDIA regression tests, relevant Byte-MCP regression, Ruff, formatting, compilation, and scope integrity.

---

## 20. Baseline Compatibility

Byte-MCP contains historical test strata associated with different runtime lineages.

Where the frozen base already contains known unrelated failures, qualification must use differential evidence.

The required statement becomes:

```text
new failures introduced by NVIDIA = 0
```

Baseline and candidate test failure node IDs must be compared explicitly.

The same principle applies to pre-existing repository-wide formatting debt: NVIDIA milestones must introduce zero new formatting debt, while NVIDIA-owned changed files must independently satisfy the active formatting contract.

---

## 21. Live Qualification

Live qualification is always a separate explicitly authorized event.

Runtime promotion itself does not contact NVIDIA.

A query model may be marked query-live-qualified only after offline qualification, runtime promotion verification, one explicitly authorized live canary, exactly one provider request, successful bounded response handling, and a receipt.

A review model requires at least one complete PREPARE → explicit approval → provider request → terminal evidence lifecycle before being marked review-live-qualified.

---

## 22. Model Maturity States

Recommended states:

```text
REGISTERED
OFFLINE_QUALIFIED
QUERY_LIVE_QUALIFIED
REVIEW_LIVE_QUALIFIED
```

Surface enablement and qualification state must not be conflated.

---

## 23. Qualification Artifacts

Create:

```text
qualification/nvidia/
    README.md
    model-registry.json
    offline-receipts/
    live-canary-receipts/
```

Artifacts must contain no credentials.

Receipts should capture commit, model alias, provider model ID, profile identity/version, request SHA where applicable, test commands/results, provider attempt count, and final qualification state.

---

## 24. Failure-Aware Engineering

The completed NVIDIA platform must include a living `FAILURE_MAP.md`.

It should cover credential, authentication, rate-limit, provider rejection, transport, timeout, malformed response, response bounds, invalid/disabled model, registry mismatch, retry/fallback regression, evidence corruption, manifest mismatch, and ambiguous provider-start failures.

For each significant failure boundary document observable symptom, likely cause, first diagnostic step, propagation risk, safe recovery, data/evidence risk, what not to do, and related tests.

No NVIDIA platform milestone is considered complete merely because its happy path passes.

---

## 25. Release Sequence

```text
design
  ↓
implementation plan
  ↓
TDD implementation
  ↓
offline qualification
  ↓
feature commit
  ↓
runtime promotion
  ↓
provider-free runtime verification
  ↓
explicit live query canary
  ↓
QUERY_LIVE_QUALIFIED
  ↓
explicit review qualification where required
  ↓
REVIEW_LIVE_QUALIFIED
```

Live requests are never implicit consequences of deployment.

---

## 26. Migration Strategy

The existing NVIDIA implementation should be evolved incrementally rather than rewritten.

Recommended order:

1. preserve NVIDIA-04 governed model selection;
2. establish the shared governed model registry;
3. clarify shared provider runtime boundaries;
4. introduce typed shared error classification;
5. build `nvidia_query`;
6. migrate `nvidia_review` to the same authoritative model registry;
7. add lightweight query audit metadata;
8. add provider-free qualification tooling;
9. add model maturity representation;
10. add NVIDIA qualification artifacts;
11. add/update `FAILURE_MAP.md`;
12. complete offline qualification;
13. promote runtime;
14. perform separately authorized live canaries.

Existing review evidence identities and historical review records must remain readable.

---

## 27. Acceptance Criteria

The platform is complete when:

- `nvidia_query` is available for routine use;
- `nvidia_review` remains approval-gated;
- `nvidia_get_review` remains local and provider-free;
- query and review share one authoritative governed model registry;
- public calls use friendly aliases;
- exact provider IDs remain internal and auditable;
- DeepSeek V4 Pro and Lightning have deterministic profiles;
- unknown/disabled models are rejected locally;
- validation happens before credential loading;
- credentials remain isolated;
- ordinary queries perform at most one provider request;
- review execution performs at most one request per approved attempt;
- no hidden retry/fallback/runtime discovery exists;
- query responses are bounded;
- review evidence remains immutable and append-only;
- review model identity is immutable after PREPARE;
- errors are typed and operationally useful;
- offline qualification requires no NVIDIA credential;
- runtime promotion makes no provider request;
- live qualification requires explicit authorization;
- model maturity is recorded;
- qualification receipts are auditable;
- significant failure surfaces are documented;
- NVIDIA changes introduce zero new unrelated Byte-MCP regressions.

---

## 28. Final Product Principle

The finished NVIDIA integration should be uneventful to operate.

A normal query should feel like:

```text
Byte → nvidia_query(...) → result
```

A formal review should feel like:

```text
Byte → PREPARE → inspect immutable identity → human approval
     → exactly one NVIDIA request → evidence-backed result
```

Adding another NVIDIA model should feel like:

```text
define profile → test profile → offline qualify
→ explicitly live qualify → enable surface
```

The complexity belongs inside the provider platform.

The user-facing experience should remain small, predictable, governed, and fluent.
