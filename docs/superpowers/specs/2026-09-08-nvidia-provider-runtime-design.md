# NVIDIA-00 — Provider Runtime and Hosted NIM Discovery Design

Date: 2026-09-08

Repository: `m-indsRefuge/Byte-MCP`

Design branch: `feat/nvidia-provider-n00-discovery`

Qualified architectural predecessor: `94ff28810a06b7af2207196ac98c1152cc65b4b1` (Q03J-A code line)

Status: APPROVED ARCHITECTURE — DESIGN SPECIFICATION AWAITING USER REVIEW

## 1. Purpose

NVIDIA-00 establishes the provider-neutral architecture that Byte-MCP will use to integrate NVIDIA's hosted NIM/API Catalog without cloning the existing OX subsystem or coupling Byte-MCP to one NVIDIA model.

The immediate objective is not to send model-generation requests. The objective is to define and implement the smallest trustworthy substrate required to discover NVIDIA-hosted models, characterize their capabilities, qualify selected models, and prepare a later exactly-once inference transport.

NVIDIA is the first implementation target for this provider-neutral substrate because NVIDIA exposes a common hosted API gateway across many model publishers while individual models still differ in capabilities, request parameters, lifecycle, and hosted availability.

The intended long-term result is:

```text
Byte-MCP
  -> provider runtime
       -> NVIDIA hosted adapter
            -> qualified NVIDIA/API Catalog models
       -> OX adapter (future migration only)
       -> future providers
```

NVIDIA-00 does not migrate OX. It extracts architectural lessons from OX into new provider-neutral concepts while preserving the historical OX implementation and evidence unchanged.

## 2. Research baseline

As of 2026-09-08, NVIDIA documentation establishes the following facts for the hosted API Catalog:

1. The default hosted base URL is `https://integrate.api.nvidia.com/v1`.
2. Hosted model inventory is exposed at `GET https://integrate.api.nvidia.com/v1/models`.
3. Hosted access uses an NVIDIA API key conventionally provided through `NVIDIA_API_KEY` and sent as a Bearer token.
4. Hosted LLM/chat services use OpenAI-compatible request conventions, including `/v1/chat/completions` for chat-capable models.
5. The public API Catalog contains models from NVIDIA and third-party publishers, and the catalog is dynamic: models may be added, updated, deprecated, or removed.
6. Self-hosted NIM is a distinct deployment mode. NGC credentials such as `NGC_API_KEY` are used for authenticated model/container downloads and are not the credential abstraction for the hosted API Catalog.
7. Local/self-hosted NIM model identifiers can differ from hosted identifiers; callers should use the identifier exposed by the relevant endpoint.
8. Production reliability requirements may justify self-hosted NIM or an enterprise endpoint; the developer-facing hosted catalog must be treated as development/evaluation infrastructure rather than guaranteed production capacity.

Primary references consulted on 2026-09-08:

- NVIDIA NIM Operator, hosted model configuration: `https://docs.nvidia.com/nim-operator/latest/guardrail.html`
- NVIDIA NeMo troubleshooting, hosted API Catalog: `https://docs.nvidia.com/nemo-platform/documentation/reference/troubleshooting/guardrails`
- NVIDIA OpenShell provider configuration: `https://docs.nvidia.com/openshell/sandboxes/manage-providers`
- NVIDIA NIM LLM environment variables: `https://docs.nvidia.com/nim/large-language-models/latest/reference/environment-variables.html`
- NVIDIA AI-Q model swapping / hosted considerations: `https://docs.nvidia.com/aiq-blueprint/2.1.0/customization/swapping-models.html`
- NVIDIA API Catalog: `https://build.nvidia.com/models`

Catalog counts and model availability are observations, not frozen API guarantees. They must never be encoded as permanent assumptions.

## 3. Scope

NVIDIA-00 covers only the discovery and provider-contract foundation.

It defines:

- provider identity and endpoint-family vocabulary;
- hosted NVIDIA settings and credential boundaries;
- model identity and capability profiles;
- model lifecycle and qualification states;
- normalized provider attempt outcomes and transport-failure vocabulary;
- a read-only NVIDIA catalog client contract;
- separation between discovered models and qualified models;
- initial qualification-roster metadata;
- test seams for future exactly-once HTTP transport;
- boundaries for a future shared provider lane and durable provider evidence.

NVIDIA-00 may add local code and tests for these concepts after an implementation plan is separately approved.

NVIDIA-00 does not perform model inference.

## 4. Non-goals

NVIDIA-00 does not:

- call `/v1/chat/completions`;
- call `/v1/responses`;
- call embedding, reranking, OCR, image, video, speech, or other specialized NVIDIA endpoints;
- self-host any NIM container;
- use `NGC_API_KEY` for hosted inference;
- install or adopt the OpenAI Python SDK;
- add automatic retries;
- add model fallback;
- add automatic model selection from the live catalog;
- qualify every NVIDIA API Catalog model;
- change OX behavior;
- modify OX evidence;
- migrate OX code into the provider runtime;
- alter Wolfram behavior;
- promote a new Byte-MCP runtime;
- expose secrets or environment values through MCP responses, evidence, logs, or exceptions;
- claim hosted NVIDIA endpoints provide production SLA guarantees.

Embeddings, reranking, multimodal generation, self-hosting, and OX migration are separate future designs.

## 5. Architectural principles

### 5.1 Provider-neutral above, provider-specific below

The shared runtime owns generic concepts such as provider identity, model identity, qualification state, attempt outcomes, transport observation, and retry prohibition.

The NVIDIA adapter owns NVIDIA-specific concepts such as the hosted base URL, `NVIDIA_API_KEY`, model-catalog decoding, NVIDIA request dialects, and NVIDIA-specific safe error-code mapping.

Provider-neutral modules must not import from `byte_mcp.ox` or `byte_mcp.nvidia`.

Provider adapters may import provider-neutral contracts.

### 5.2 Discovery is advisory; qualification is authoritative

A model returned by `/v1/models` is only `DISCOVERED`.

It is not automatically safe to use, enabled, or approved for any Byte-MCP role.

A model may become eligible for routing only after explicit characterization and qualification under Byte-MCP-owned evidence.

The live catalog may inform operators that a qualified model has disappeared or changed, but catalog changes must never silently rewrite historical qualification evidence.

### 5.3 No hidden retry or substitution

The provider runtime owns retry policy.

For NVIDIA hosted inference, the frozen default is zero automatic retries.

A `429`, timeout, connection interruption, `5xx`, malformed response, deprecated model, or unavailable model must not trigger:

- a second request;
- a different NVIDIA model;
- a different provider;
- a reconnect/resume attempt;
- an implicit SDK retry.

Any future retry or fallback mechanism requires separate explicit design and authorization semantics.

### 5.4 Direct HTTP transport

The governed NVIDIA transport will use the existing `httpx` dependency rather than introducing the OpenAI SDK for provider execution.

This preserves Byte-MCP ownership of:

- the exact outbound request count;
- redirect behavior;
- connect/read/write/pool timeouts;
- absolute deadlines;
- transport observations;
- error classification;
- retry count;
- safe response parsing.

OpenAI compatibility is treated as a wire-protocol convention, not as a requirement to use the OpenAI client library.

### 5.5 Hosted and self-hosted credentials remain distinct

Hosted inference credential:

```text
NVIDIA_API_KEY
```

Self-hosted/container/model-download credential:

```text
NGC_API_KEY
```

NVIDIA-00 concerns hosted inference only. `NGC_API_KEY` must not be accepted as a fallback alias for `NVIDIA_API_KEY`.

## 6. Proposed module boundary

The target structure is conceptually:

```text
src/byte_mcp/
  providers/
    __init__.py
    models.py
    outcomes.py
    transport.py          # contracts only in NVIDIA-00; execution later
    registry.py

  nvidia/
    __init__.py
    settings.py
    catalog.py
    models.py
    registry.py

  ox/                     # unchanged by NVIDIA-00
  wolfram/                # unchanged by NVIDIA-00
```

Exact filenames may be refined in the implementation plan, but responsibility boundaries are frozen:

- provider-neutral identity/outcome types live outside provider packages;
- NVIDIA catalog parsing and hosted settings live in the NVIDIA package;
- OX code is not moved during NVIDIA-00;
- no provider-neutral module depends on OX-specific exception classes or OX-specific ID formats.

## 7. Provider identity

Introduce an immutable provider identity with at least:

```text
provider_id: str
provider_family: str
endpoint_family: str
```

For the first NVIDIA adapter:

```text
provider_id = "nvidia-api-catalog"
provider_family = "nvidia"
endpoint_family = "openai-chat"
```

The provider identity identifies the transport/provider surface, not the model publisher. A DeepSeek or Moonshot model routed through NVIDIA remains a request to provider `nvidia-api-catalog` while preserving its publisher/model identity separately.

This distinction is required for evidence and routing. For example:

```text
provider: nvidia-api-catalog
publisher: deepseek-ai
model: deepseek-ai/deepseek-v4-pro-0813
```

must not be collapsed into `provider=deepseek`.

## 8. Model identity and capability profile

A model profile is an immutable Byte-MCP-owned record containing at minimum:

```text
model_id: str
publisher: str
provider_id: str
endpoint_family: str
input_modalities: tuple[str, ...]
output_modalities: tuple[str, ...]
context_window: int | None
supports_streaming: bool | None
supports_tool_calling: bool | None
supports_reasoning: bool | None
reasoning_dialect: str | None
hosted_status: str
qualification_state: str
observed_at: str
```

Optional capability fields may be added when supported by authoritative evidence, but unknown values must remain explicit rather than guessed.

The registry must not infer unsupported capabilities from marketing labels alone.

### 8.1 Reasoning dialect

Models behind the same NVIDIA gateway can require different optional request parameters.

The registry therefore records a bounded `reasoning_dialect` identifier rather than embedding arbitrary provider request JSON into the generic model profile.

Examples of future dialect identifiers may include:

```text
nvidia-chat-template-enable-thinking
reasoning-effort
provider-default
```

The adapter translates a qualified dialect into an allow-listed request shape. Arbitrary catalog metadata must never be copied directly into outbound request JSON.

## 9. Model lifecycle

The model lifecycle is:

```text
DISCOVERED
  -> CHARACTERIZED
  -> QUALIFIED
  -> ENABLED
```

Additional non-forward states:

```text
UNAVAILABLE
DEPRECATED
DISABLED
```

Semantics:

`DISCOVERED`
: Seen in a live or captured catalog result. No inference authorization follows.

`CHARACTERIZED`
: Byte-MCP has recorded sufficient model metadata and endpoint behavior from authoritative documentation or bounded probes.

`QUALIFIED`
: The model has passed the model-specific qualification campaign required for its intended endpoint family.

`ENABLED`
: Routing policy may select the model for one or more explicit roles.

`UNAVAILABLE`
: The previously known hosted identifier is not currently available through the expected hosted surface or a bounded availability check failed deterministically.

`DEPRECATED`
: NVIDIA marks the hosted model/endpoint as deprecated or announces removal.

`DISABLED`
: Byte-MCP intentionally excludes the model from routing regardless of provider availability.

A model never moves to `QUALIFIED` or `ENABLED` solely because NVIDIA returns it from `/v1/models`.

## 10. Catalog discovery contract

The hosted catalog endpoint is:

```text
GET https://integrate.api.nvidia.com/v1/models
Authorization: Bearer <NVIDIA_API_KEY>
```

The NVIDIA catalog client is read-only with respect to Byte-MCP provider execution: it cannot generate model output.

Its responsibilities are limited to:

1. construct one bounded authenticated GET;
2. apply configured timeouts and redirects policy;
3. parse only the allow-listed model-list envelope required for discovery;
4. normalize model identifiers without inventing metadata;
5. redact or discard unneeded response content;
6. return a bounded catalog snapshot;
7. make no retry and no inference call.

The catalog client must never:

- execute a model;
- infer qualification;
- persist the API key;
- return authorization headers;
- return raw arbitrary response headers;
- automatically write qualification state;
- automatically enable newly discovered models.

A real authenticated catalog request is still an external NVIDIA request and requires an explicit live-discovery authorization before first use. Unit tests use injected transports or static fixtures.

## 11. Hosted settings

The NVIDIA hosted settings contract must expose at least:

```text
api_key: str | None
base_url: str = "https://integrate.api.nvidia.com/v1"
catalog_timeout_seconds: bounded positive value
```

Security rules:

1. Load the hosted credential only from the approved NVIDIA configuration source/environment contract.
2. Never include the credential value in `repr`, exceptions, audit payloads, MCP responses, evidence files, test snapshots, or logs.
3. Validate the base URL against the exact hosted origin for the hosted adapter; arbitrary caller-supplied URLs are not allowed in the production hosted profile.
4. Do not accept `NGC_API_KEY` as an inference fallback.
5. Missing credentials disable or misconfigure NVIDIA without blocking core Byte-MCP startup.

## 12. Normalized provider outcomes

The provider-neutral attempt outcome vocabulary is frozen as:

```text
NOT_SENT
REJECTED
COMPLETED
OUTCOME_UNKNOWN
```

These names intentionally preserve the semantics learned from OX while removing OX ownership of the concept.

Definitions:

`NOT_SENT`
: Byte-MCP has trustworthy local evidence that the provider request was not transmitted to a remote service capable of acting on it.

`REJECTED`
: Byte-MCP received a complete provider/gateway response that deterministically rejected the request without a successful model result.

`COMPLETED`
: Byte-MCP received and validated the complete expected provider result for that attempt. A malformed payload after a complete HTTP response may be classified as `COMPLETED` transport-wise with a protocol failure at the higher layer; the implementation plan must preserve a clear distinction between transport outcome and usable-result state.

`OUTCOME_UNKNOWN`
: Transmission may have occurred but Byte-MCP cannot prove a complete provider result or deterministic rejection.

The outcome vocabulary must not imply permission to retry.

## 13. Provider-neutral transport failure vocabulary

NVIDIA-00 freezes a provider-neutral transport-failure enum compatible with the currently proven OX categories:

```text
ABSOLUTE_DEADLINE
READ_TIMEOUT
READ_ERROR
WRITE_TIMEOUT
WRITE_ERROR
REMOTE_PROTOCOL_ERROR
HTTP_TRANSPORT_ERROR
CONNECT_TIMEOUT
CONNECT_ERROR
POOL_TIMEOUT
```

Provider-specific adapters may map safe HTTP/application error codes separately, but transport categories belong to the shared runtime.

Future extraction from OX must preserve historical OX evidence values exactly; no historical OX artifact is rewritten to use a new type name.

## 14. Initial NVIDIA qualification roster

The initial roster is provisional and exists to focus later qualification work, not to guarantee permanent availability.

### 14.1 Routine reviewer candidate

```text
model: nvidia/nemotron-3.5-lightning-30b-a3b
intended role: routine high-throughput development review
state at NVIDIA-00: DISCOVERED / candidate only
```

### 14.2 Deep reviewer candidate

```text
model: nvidia/nemotron-3-ultra-550b-a55b
intended role: difficult architecture, reliability, and deep code review
state at NVIDIA-00: candidate only; live availability must be confirmed before qualification
```

### 14.3 Independent coding/reasoning candidate

```text
model: deepseek-ai/deepseek-v4-pro-0813
intended role: independent coding/reasoning reviewer
state at NVIDIA-00: DISCOVERED / candidate only
```

### 14.4 Long-horizon challenger candidate

```text
model: moonshotai/kimi-k3
intended role: long-horizon agentic/coding challenger; multimodal characterization later
state at NVIDIA-00: DISCOVERED / candidate only
```

No roster entry may be routed until it reaches `QUALIFIED` and then `ENABLED` for an explicit role.

## 15. Relationship to the existing OX implementation

The current OX code line demonstrates several capabilities that NVIDIA must preserve conceptually:

- a fixed single-attempt HTTP client;
- explicit transport timeout/deadline ownership;
- bounded transport observations;
- exactly-one provider dispatch semantics;
- a single non-queued provider lane;
- immutable launch descriptors;
- runtime-session identity;
- durable attempt evidence;
- fail-isolated optional provider startup;
- zero automatic retries.

NVIDIA-00 must not copy the OX package wholesale.

Instead, the new provider-neutral layer should be designed so that future OX migration can consume proven shared primitives without requiring a rewrite of historical OX evidence.

During NVIDIA-00 and NVIDIA-01:

```text
src/byte_mcp/ox/**
```

is frozen except for a separately approved compatibility change that is strictly required to keep tests compiling. Such a compatibility need must be surfaced before mutation rather than assumed.

## 16. Runtime and MCP boundaries

NVIDIA must be fail-isolated like OX and Wolfram.

Missing or invalid NVIDIA configuration must not prevent:

- Byte-MCP core startup;
- local file tools;
- OX availability;
- Wolfram availability.

NVIDIA-00 does not expose an inference MCP tool.

A future discovery surface may expose only bounded metadata such as qualified model IDs and qualification status. Raw provider catalog payloads should not become an unrestricted MCP surface.

A future inference tool requires a separate design covering authorization, request preparation, evidence, and provider execution.

## 17. Safety and privacy invariants

1. No NVIDIA inference request occurs in NVIDIA-00.
2. No NVIDIA request of any kind occurs from unit tests.
3. The first real `/v1/models` call requires explicit live-discovery authorization.
4. The first real `/v1/chat/completions` call requires a separate explicit live-canary authorization.
5. No automatic retry, reconnect, model fallback, or provider fallback.
6. A catalog change never grants execution authority.
7. API keys never enter durable evidence or MCP output.
8. Raw exception strings from HTTP/provider libraries are not automatically persisted.
9. Arbitrary response headers are not persisted.
10. Provider output is untrusted data and never treated as executable instructions.
11. OX and Wolfram remain isolated from NVIDIA; no provider communicates directly with another provider.
12. Historical OX evidence remains immutable.
13. Provider-neutral contracts must not weaken OX's existing approval or evidence semantics.
14. Catalog/model metadata must be bounded before persistence.
15. Any ambiguous inference transmission in future phases must resolve to `OUTCOME_UNKNOWN`, not an automatic resend.

## 18. Error handling

The NVIDIA adapter must eventually map provider failures into provider-neutral categories plus NVIDIA-specific safe classifications.

At minimum, the design anticipates:

```text
configuration missing/invalid
401 authentication
403 permission
404 model/endpoint unavailable
400 invalid request
413/request-size style rejection when exposed
429 rate limit or quota-like rejection
5xx provider unavailable
connect timeout/error
write timeout/error
read timeout/error
remote protocol interruption
absolute deadline
malformed provider envelope
```

NVIDIA-00 defines contracts only. NVIDIA-01 will specify exact HTTP-to-domain mappings before live inference.

Error classification must be based on bounded status/error-code fields, not arbitrary exception text.

## 19. Testing strategy

NVIDIA-00 implementation will be test-first.

Required test categories:

### 19.1 Provider-neutral model contracts

Verify:

- immutable provider/model identity;
- valid and invalid IDs;
- explicit unknown capability values;
- qualification-state transitions;
- no automatic `DISCOVERED -> QUALIFIED` transition.

### 19.2 NVIDIA settings

Verify:

- missing key fail-isolates NVIDIA;
- key never appears in `repr`;
- exact hosted base URL validation;
- `NGC_API_KEY` is not accepted as hosted inference credential;
- invalid configuration does not affect core/OX/Wolfram imports.

### 19.3 Catalog parser/client

Using injected `httpx` transports or static fixtures, verify:

- one GET maximum;
- zero retries;
- Bearer authorization is constructed internally;
- model IDs are parsed from a bounded OpenAI-compatible list envelope;
- unknown fields are ignored rather than executed/interpreted;
- malformed envelopes fail closed;
- credentials and arbitrary headers are absent from returned values;
- discovery does not write `QUALIFIED` or `ENABLED` state.

### 19.4 Regression

Run the full Byte-MCP Python test suite and Ruff checks. OX and Wolfram tests must continue to pass without behavioral edits to their provider execution paths.

## 20. Phase boundaries after NVIDIA-00

### NVIDIA-01 — exactly-once hosted chat transport

Design and implement one provider-neutral attempt transport plus NVIDIA `/v1/chat/completions` adapter with:

- exactly one POST;
- zero retry;
- deterministic request identity;
- bounded timeouts/deadline;
- safe transport observation;
- status/error mapping;
- response-envelope validation;
- no live call until separate authorization.

### NVIDIA-02 — Nemotron Lightning live canary

Qualify one model through one explicitly authorized live request using immutable prepared request identity and durable evidence.

### NVIDIA-03 — multi-model qualification

Characterize and qualify the approved roster without changing the provider runtime for each model. Model-specific dialect behavior must remain registry/adapter data rather than transport branching spread throughout the codebase.

### NVIDIA-04 — review workflow

Build the developer-facing NVIDIA code-review capability and routing policy after transport and model qualification are proven.

### Future — OX shared-runtime migration assessment

Only after NVIDIA proves the shared contracts should Byte-MCP compare OX's existing implementation to the provider runtime and decide what can be safely migrated. Historical OX evidence and authorization semantics remain authoritative throughout.

## 21. Acceptance criteria for NVIDIA-00 implementation

NVIDIA-00 is complete only when all of the following are true:

1. Provider-neutral identity, outcome, failure, and model lifecycle contracts exist and are tested.
2. NVIDIA hosted settings use `NVIDIA_API_KEY` only and fail-isolate cleanly.
3. A bounded NVIDIA catalog client/parser exists with an injected-transport test seam.
4. Catalog discovery cannot qualify or enable a model.
5. The initial qualification roster can be represented without hard-coding transport logic per model.
6. No inference MCP tool exists.
7. No live NVIDIA request is required for the test suite.
8. No OX or Wolfram provider request is made during implementation/qualification tests.
9. Existing OX/Wolfram behavior remains unchanged.
10. Full Python tests pass.
11. Ruff check and format verification pass.
12. The implementation contains no automatic retry or fallback path.
13. Secret-redaction/security tests prove the NVIDIA API key cannot enter ordinary representations or catalog outputs.
14. NVIDIA-01 can be designed without redesigning NVIDIA-00's provider/model identity contracts.

## 22. Frozen design decision

Byte-MCP will not build "an NVIDIA API client" as a second bespoke OX-style subsystem.

It will build a small provider-neutral runtime with NVIDIA API Catalog as the first clean adapter. The NVIDIA implementation proves the shared abstractions; it does not force OX to migrate immediately.

The governing separation is:

```text
provider runtime owns:
  identity
  lifecycle
  attempt outcomes
  transport failure vocabulary
  qualification semantics
  retry prohibition

NVIDIA adapter owns:
  NVIDIA credential
  NVIDIA hosted origin
  catalog decoding
  model-specific request dialects
  NVIDIA safe HTTP/application error mapping

routing layer owns:
  which QUALIFIED model is ENABLED for which role
```

This separation is the architectural baseline for all subsequent NVIDIA phases.
