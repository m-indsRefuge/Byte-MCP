# NVIDIA-02 — Governed Nemotron Lightning Canary Design

Date: 2026-09-09
Repository: `m-indsRefuge/Byte-MCP`
Design branch: `feat/nvidia-provider-n02-lightning-canary`
Qualified predecessor: `29daea6ef68ebb3d46031ce302b0108617bd1221` (NVIDIA-01)
Status: APPROVED ARCHITECTURE — WRITTEN DESIGN AWAITING USER REVIEW

## 1. Purpose

NVIDIA-02 introduces the first governed live NVIDIA inference canary for Byte-MCP.

The phase exists to prove that the provider-neutral request identity and exactly-once transport qualified in NVIDIA-01 can be used in a real provider interaction while preserving Byte-MCP's strongest reliability and authorization guarantees:

- one immutable prepared request identity;
- one explicit human authorization bound to that identity;
- one durable provider-start boundary before transmission;
- exactly one NVIDIA inference request;
- zero automatic retry;
- zero redirect following;
- zero model fallback;
- zero provider fallback;
- durable terminal evidence;
- bounded, secret-safe observations;
- separation of transport success from semantic probe success.

NVIDIA-02 is deliberately a **single-model, single-canary** phase. It does not yet create the general multi-provider runtime or expose NVIDIA inference through the MCP server.

## 2. Architectural decision

NVIDIA-02 uses **Option B — Governed single-canary runner**.

It wraps the already-qualified NVIDIA-01 adapter and provider-neutral transport with the minimum lifecycle/evidence layer needed for a meaningful live canary.

It does **not** duplicate the NVIDIA-01 HTTP client and does **not** refactor OX.

Conceptually:

```text
Byte-MCP
│
├── providers/
│   ├── requests.py       # NVIDIA-01, reused unchanged unless a proven defect exists
│   └── transport.py      # NVIDIA-01, reused unchanged unless a proven defect exists
│
├── nvidia/
│   ├── settings.py       # NVIDIA-01 credential/timeout settings
│   ├── chat.py           # NVIDIA-01 hosted chat adapter
│   ├── registry.py       # NVIDIA-00 candidate roster
│   ├── canary.py         # NVIDIA-02 lifecycle/orchestration
│   └── canary_evidence.py# NVIDIA-02 durable local evidence
│
└── scripts/
    └── nvidia_lightning_canary.py  # prepare / inspect / transmit entry point
```

OX and Wolfram remain frozen.

## 3. External NVIDIA facts used by this design

As of 2026-09-09, NVIDIA's public NIM catalog lists:

```text
model: nvidia/nemotron-3.5-lightning-30b-a3b
hosted base URL: https://integrate.api.nvidia.com/v1
hosted chat endpoint: /v1/chat/completions
credential environment variable: NVIDIA_API_KEY
hosted availability: Free Endpoint — Available
```

The current NVIDIA model page demonstrates hosted access through the OpenAI-compatible API with `NVIDIA_API_KEY`, model `nvidia/nemotron-3.5-lightning-30b-a3b`, and chat-completions inference.

NVIDIA-02 does not treat public catalog availability as a qualification result. Runtime truth comes only from the single governed canary.

## 4. Scope

NVIDIA-02 implements only the following:

1. deterministic Lightning canary request preparation;
2. allocation of one durable canary identity;
3. durable storage of exact prepared request bytes and hashes;
4. read-only inspection of a prepared canary;
5. explicit authorization bound to exact canary ID + request SHA-256;
6. pre-provider validation of credential/configuration/request identity;
7. durable provider-start evidence;
8. exactly one call through `execute_prepared_nvidia_chat()`;
9. durable terminal evidence for success, rejection, transport ambiguity, or local failure;
10. semantic observation of whether the model returned the exact probe string;
11. tests proving no retries, no fallback, no credential persistence, and no second transmission;
12. a final live canary only after separate explicit human authorization.

## 5. Non-goals

NVIDIA-02 does **not**:

- expose NVIDIA inference as an MCP tool;
- add NVIDIA review workflows;
- build the final provider runtime scheduler;
- migrate OX onto provider-neutral transport;
- perform multi-model qualification;
- call `/v1/models` as part of the canary;
- perform a separate NVIDIA catalog API request before inference;
- add streaming;
- add reasoning controls or `extra_body` model dialect fields;
- add tool/function calling;
- add images or multimodal input;
- add JSON mode or structured output;
- add automatic retries;
- add manual retry-in-place;
- create `A002` or any second attempt for the same canary;
- substitute another NVIDIA model if Lightning is unavailable;
- fall back to OX, Wolfram, OpenAI, or another provider;
- persist the NVIDIA API key;
- write the NVIDIA API key to Git, evidence, logs, hashes, terminal receipts, reprs, or test fixtures;
- promote or restart the Byte-MCP runtime;
- merge to `main`;
- add new dependencies unless implementation proves one is strictly necessary and the design is amended first.

## 6. Frozen boundaries

The following paths remain frozen during NVIDIA-02 unless a test proves a predecessor defect that cannot be repaired within approved NVIDIA-02 files:

```text
src/byte_mcp/ox/**
src/byte_mcp/wolfram/**
src/byte_mcp/server.py
src/byte_mcp/nvidia/catalog.py
src/byte_mcp/nvidia/registry.py
pyproject.toml
```

Historical OX evidence is immutable.

The qualified NVIDIA-01 request and transport contracts are treated as stable dependencies. A defect discovered in them may be repaired only with a focused RED test and explicit scope accounting; no opportunistic refactor is permitted.

## 7. Canary identity

The first governed NVIDIA canary identity is:

```text
NVC-000001
```

Format:

```text
NVC-[0-9]{6}
```

NVIDIA-02 supports one attempt only for a canary identity.

There is no `A002` concept in NVIDIA-02. Once provider-start evidence is durably recorded, authorization is consumed regardless of the eventual transport outcome.

If the first live canary ends in `REJECTED`, `NOT_SENT`, or `OUTCOME_UNKNOWN`, NVIDIA-02 stops. Any second live request requires a separately approved new operation and may not silently reuse `NVC-000001`.

## 8. Fixed Lightning probe

The NVIDIA-02 baseline request is fixed to:

```text
provider_id: nvidia-api-catalog
model_id: nvidia/nemotron-3.5-lightning-30b-a3b
method: POST
target_origin: https://integrate.api.nvidia.com
endpoint_path: /v1/chat/completions
stream: false
n: 1
temperature: 1
top_p: 0.95
max_tokens: 64
```

Messages:

```json
[
  {
    "role": "user",
    "content": "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
  }
]
```

The exact canonical body bytes are produced once through the already-qualified `prepare_nvidia_chat_request()` / provider request identity path.

NVIDIA-02 intentionally does not add model-specific thinking/reasoning parameters. Those belong to later model characterization. If the hosted endpoint rejects this minimal non-streaming baseline, the result is recorded and NVIDIA-02 stops rather than mutating the request and retrying.

## 9. Prepared request persistence

The central NVIDIA-02 invariant is:

> The exact canonical request bytes reviewed before authorization are the exact bytes later supplied to the NVIDIA-01 transport.

The request must **not** be reconstructed from high-level parameters after approval.

Preparation writes an immutable local evidence directory containing at minimum:

```text
<evidence-root>/canaries/NVC-000001/
  manifest.json
  request-body.bin
  events.jsonl
```

`request-body.bin` contains the exact `PreparedProviderRequest.body_bytes` bytes.

`manifest.json` contains only bounded metadata:

```text
schema
canary_id
provider_id
model_id
method
target_origin
endpoint_path
payload_sha256
request_sha256
body_bytes
prepared_at
probe_expected_text
qualified_predecessor_sha
```

The manifest does not contain the API key or Authorization header.

Before any later transmission, Byte-MCP must:

1. load `request-body.bin`;
2. verify its byte count against `body_bytes`;
3. recompute `payload_sha256` from the exact bytes;
4. reconstruct the request metadata object using the persisted exact bytes;
5. rely on NVIDIA-01's transport to recompute and verify the complete request identity before send;
6. reject any mismatch locally with zero network calls.

## 10. Evidence root

NVIDIA canary evidence is local runtime evidence and is never stored in the Git repository.

Configuration:

```text
BYTE_MCP_NVIDIA_EVIDENCE_DIR
```

Default on Windows:

```text
%LOCALAPPDATA%\Byte-MCP\nvidia
```

Default on Unix-like systems:

```text
$XDG_DATA_HOME/byte-mcp/nvidia
```

or, when `XDG_DATA_HOME` is absent:

```text
~/.local/share/byte-mcp/nvidia
```

The evidence root contains no credential material.

## 11. Immutable evidence semantics

Files that represent identity are create-once and must fail if they already exist unexpectedly.

`manifest.json` and `request-body.bin` are immutable after preparation.

`events.jsonl` is append-only and records bounded lifecycle events.

Minimum events:

```text
CANARY_PREPARED
CANARY_AUTHORIZED
PROVIDER_START
CANARY_TERMINAL
```

Event writes must be flushed and fsynced before the process continues across a consequential boundary.

No event may include:

- API key;
- Authorization header;
- environment dump;
- raw HTTP headers;
- raw exception text;
- provider response body;
- user home paths beyond the evidence root itself;
- arbitrary provider prose.

## 12. Prepare phase

`prepare` is provider-free and credential-free.

It performs:

1. verify branch/runtime code is the qualified NVIDIA-02 implementation when final qualification is reached;
2. allocate the next valid canary identity;
3. build the fixed Lightning request;
4. obtain `body_bytes`, `payload_sha256`, and `request_sha256` from NVIDIA-01;
5. write immutable `request-body.bin`;
6. write immutable `manifest.json`;
7. append and fsync `CANARY_PREPARED`;
8. return a bounded receipt.

The prepare receipt reports:

```text
canary_id
provider_id
model_id
payload_sha256
request_sha256
body_bytes
prepared_at
evidence_root
```

It does not report message body content unless the caller explicitly requests a read-only inspection view.

Preparation never loads `NVIDIA_API_KEY` and never creates an HTTP client.

## 13. Inspect phase

`inspect` is read-only and provider-free.

It returns the exact prepared identity and a bounded rendering of the fixed probe so the human can verify what will be sent.

It must re-verify manifest/body integrity before reporting the canary as eligible for approval.

Inspection must not mutate evidence and must not load the API key.

## 14. Human authorization contract

The live request requires a separate explicit human authorization after preparation.

Authorization is bound to both:

```text
canary_id
request_sha256
```

The transmit interface therefore requires the caller to supply both exact values plus an explicit approval boolean/flag.

A generic `--yes`, environment-only approval, or approval not bound to the exact request hash is insufficient.

Conceptually:

```text
transmit(
    canary_id="NVC-000001",
    expected_request_sha256="<64 lowercase hex>",
    approve=True,
)
```

Before provider-start evidence is written, Byte-MCP must prove:

- the prepared canary exists;
- the canary has no prior `PROVIDER_START` event;
- the canary has no terminal event indicating a consumed attempt;
- supplied request hash equals manifest request hash;
- body bytes still match manifest payload hash;
- prepared provider/model/target are exactly the frozen NVIDIA values;
- the credential is configured;
- all timeout settings are valid;
- no fallback route is configured or selected.

Any failure here stops with zero provider requests and without consuming provider authorization.

## 15. API key handling

The hosted credential remains the existing NVIDIA-01 environment variable:

```text
NVIDIA_API_KEY
```

NVIDIA-02 does not add a credential file.

For the first live canary, the recommended operator setup is a session-only PowerShell environment variable entered without echo:

```powershell
$env:NVIDIA_API_KEY = Read-Host "NVIDIA API key" -MaskInput
```

The key must never be supplied as a CLI argument because command-line arguments may be observable in shell history or process metadata.

The key must never be persisted by NVIDIA-02.

`NvidiaHostedSettings.load()` remains the authority for reading the hosted credential.

If the key is absent or invalid, `transmit` stops before `PROVIDER_START` is persisted.

## 16. Provider-start adjacency

This is the most important live-canary ordering rule.

Before `PROVIDER_START`, all potentially fallible preparation must already be complete:

- evidence loaded;
- exact body bytes loaded;
- hashes revalidated;
- model/target verified;
- API key loaded;
- timeout policy constructed;
- authorization checked;
- transmission context data prepared;
- all deterministic local validation complete.

Then:

```text
append + fsync PROVIDER_START
        ↓
construct ProviderTransmissionContext from the persisted timestamp/hash
        ↓
execute_prepared_nvidia_chat(...)
```

There must be no catalog call, filesystem read, model routing decision, prompt reconstruction, credential lookup, or other provider call between durable provider-start evidence and the single NVIDIA transmission.

The only allowed local work after provider-start and before transmission is bounded in-memory construction/consistency checking required to call the already-qualified NVIDIA-01 adapter.

## 17. Authorization consumption

Once `PROVIDER_START` is durably persisted, the one live authorization is consumed.

This remains true if:

- DNS/connect fails;
- connect timeout maps to `NOT_SENT`;
- write/read fails;
- absolute deadline expires;
- NVIDIA returns a rejection;
- the response is malformed;
- model identity mismatches;
- the process receives an ambiguous transport outcome.

NVIDIA-02 never retries automatically and never creates another attempt for the same canary.

## 18. Exactly-one transmission

The live path calls exactly:

```text
execute_prepared_nvidia_chat(...)
```

once.

That wrapper must continue to delegate to the NVIDIA-01 provider-neutral `execute_once()` transport.

NVIDIA-02 must not:

- create an additional HTTP client;
- perform a HEAD/GET probe first;
- call `/v1/models` first;
- call another model;
- call the same request again after any exception;
- use SDK-level retry behavior;
- follow redirects;
- replay the request on connection uncertainty.

## 19. Terminal outcomes

NVIDIA-02 preserves NVIDIA-01 transport/application semantics.

Possible attempt outcomes:

```text
COMPLETED
REJECTED
NOT_SENT
OUTCOME_UNKNOWN
```

Terminal evidence records:

```text
canary_id
request_sha256
provider_id
model_id
provider_started_at
provider_finished_at
attempt_outcome
transport_failure_kind
http_status_code
response_headers_received
response_body_started
decoded_body_bytes_received
elapsed_ms
finish_reason
response_id
usage counters
semantic_probe_match
terminal_at
```

Fields not applicable to the outcome are null/omitted according to one fixed schema.

Raw provider response content is not copied into the terminal receipt.

The parsed model response text may be shown to the operator in the immediate command result, but durable evidence stores only bounded semantic metadata for this canary unless a later phase explicitly expands evidence policy.

## 20. Transport success vs semantic probe success

NVIDIA-02 distinguishes two independent questions.

### 20.1 Transport/protocol success

The transport canary succeeds when:

- the single request is transmitted through NVIDIA-01;
- the response is fully received as a valid successful HTTP response;
- NVIDIA-01 parses it successfully;
- returned model ID exactly matches the requested Lightning model.

This is the primary NVIDIA-02 objective.

### 20.2 Semantic probe match

The semantic probe matches only when the parsed assistant content, after no normalization beyond exact string comparison, equals:

```text
BYTE_NVIDIA_CANARY_OK
```

A transport/protocol success with different wording is still recorded as a successful transport canary with `semantic_probe_match=false`.

It is **not** reclassified as `REJECTED` or `OUTCOME_UNKNOWN` and does not trigger a retry.

## 21. No `/v1/models` preflight

NVIDIA-02 intentionally does not call NVIDIA's authenticated `/v1/models` endpoint before the canary.

Reasons:

1. it would consume a second provider request;
2. it would weaken the exact-single-request test;
3. public NVIDIA evidence already identifies Lightning as a currently hosted free endpoint;
4. the inference response itself is the authoritative live compatibility test.

If NVIDIA returns 404/model-unavailable, NVIDIA-02 records the single rejection and stops.

## 22. CLI / operator surface

NVIDIA-02 adds a narrow script-oriented operator surface, not an MCP tool.

Conceptual commands:

```text
python scripts/nvidia_lightning_canary.py prepare
python scripts/nvidia_lightning_canary.py inspect --canary-id NVC-000001
python scripts/nvidia_lightning_canary.py transmit \
  --canary-id NVC-000001 \
  --expected-request-sha256 <hash> \
  --approve
```

The implementation plan may refine exact argparse spelling, but the semantic phases and approval binding are frozen by this design.

The script must never accept the API key as an argument.

## 23. Concurrency and double-send protection

NVIDIA-02 must protect against two local processes transmitting the same prepared canary concurrently.

Before provider-start, transmit obtains a per-canary exclusive local lock/lease covering the eligibility check and provider-start append.

Within that lock it re-reads lifecycle evidence and refuses if `PROVIDER_START` or terminal evidence already exists.

The lock is not a retry queue and does not serialize multiple canaries into a provider scheduler. It exists only to prevent duplicate transmission of the same NVC identity.

A second process must fail locally with zero provider calls.

## 24. Crash semantics

If the process crashes:

### Before `PROVIDER_START`

Authorization is not consumed. No provider request is assumed to have occurred.

### After durable `PROVIDER_START` and before terminal evidence

The canary is treated as **consumed and ambiguous**.

On the next inspection, Byte-MCP must not retransmit. It reports that provider-start was recorded without a durable terminal event and requires explicit human adjudication outside NVIDIA-02.

NVIDIA-02 must not invent a terminal result or create a second attempt.

## 25. Evidence integrity and recovery

On every read, NVIDIA-02 verifies:

- canary ID syntax;
- manifest schema;
- request body byte count;
- payload SHA-256;
- request SHA-256 consistency;
- event ordering;
- at most one `CANARY_AUTHORIZED`;
- at most one `PROVIDER_START`;
- at most one terminal event;
- terminal event cannot precede provider-start;
- no transmission after terminal state.

Malformed or contradictory evidence puts the canary into a local evidence-error state and forbids provider contact.

No automatic evidence repair is allowed in NVIDIA-02.

## 26. Safe errors and output

Errors exposed to the operator must be bounded enums/messages.

They may include:

- canary ID;
- request hash;
- lifecycle state;
- HTTP status code;
- safe NVIDIA failure kind;
- provider-neutral transport failure kind.

They must not include:

- API key;
- Authorization header;
- raw environment values;
- raw exception text from `httpx`;
- response body;
- full HTTP header maps.

## 27. Qualification state

A successful NVIDIA-02 transport canary does not automatically mark Lightning broadly production-ready.

The progression remains:

```text
DISCOVERED
    ↓
NVIDIA-02 live transport canary passed
    ↓
CANARY_VALIDATED (phase-local evidence)
    ↓
NVIDIA-03 multi-model/model-behavior qualification
    ↓
later role enablement decision
```

NVIDIA-02 may record a phase-local canary result but should not silently mutate the existing NVIDIA-00 registry qualification state unless a later approved design explicitly defines that lifecycle transition.

## 28. Testing strategy

All implementation tests before the live canary are provider-free.

They must use mocks/fakes/temporary evidence roots and prove at least:

### Preparation

- fixed Lightning model and fixed probe;
- exact canonical body bytes persisted unchanged;
- manifest hashes match NVIDIA-01 prepared request;
- preparation succeeds with no `NVIDIA_API_KEY` configured;
- preparation makes zero HTTP calls;
- duplicate immutable identity cannot overwrite evidence.

### Inspection

- read-only behavior;
- body/hash integrity revalidation;
- no API key load;
- no HTTP call;
- malformed evidence fails closed.

### Authorization/transmit preflight

- missing approval => zero calls;
- wrong canary ID => zero calls;
- wrong request hash => zero calls;
- missing API key => zero calls and no provider-start event;
- invalid timeout config => zero calls and no provider-start event;
- tampered body => zero calls;
- wrong provider/model/target => zero calls;
- already-started canary => zero calls;
- already-terminal canary => zero calls;
- concurrent duplicate invocation => at most one provider-start and one mock call.

### Provider-start ordering

- provider-start is durably written before mock transport is invoked;
- the timestamp used by `ProviderTransmissionContext` exactly equals persisted provider-start time;
- expected request hash exactly equals manifest request hash;
- no filesystem read/catalog call/routing operation occurs between start persistence and adapter invocation.

### Terminalization

- COMPLETED writes one terminal event;
- REJECTED writes one terminal event;
- NOT_SENT after consumed start writes one terminal event;
- OUTCOME_UNKNOWN writes one terminal event;
- protocol failure after complete 2xx is terminalized without retry;
- exact semantic match true/false is recorded separately;
- no terminal receipt contains response body or credential.

### Crash/recovery

- provider-start without terminal event blocks retransmission;
- malformed events block retransmission;
- no A002 / retry path exists.

### Isolation

- no OX import in NVIDIA canary code;
- no Wolfram import;
- no server registration;
- no live provider call in CI;
- no key in tracked content;
- no retry/backoff/fallback implementation.

## 29. Live canary authorization gate

Construction and offline qualification do **not** authorize the live NVIDIA request.

After the implementation branch passes local and GitHub CI qualification, the prepare phase will create `NVC-000001` and report its exact identities.

Byte will then present at minimum:

```text
canary_id
model_id
payload_sha256
request_sha256
body_bytes
probe text
```

The user must explicitly approve that exact prepared identity before the transmit command may be run.

Only then will the operator set `NVIDIA_API_KEY` in the local shell session and execute the single live canary.

## 30. Live canary stop conditions

Before transmission, stop with zero provider calls if:

1. branch/head identity is not the qualified NVIDIA-02 implementation;
2. prepared canary identity is missing or malformed;
3. persisted body/hash integrity fails;
4. expected request hash does not exactly match;
5. explicit approval is absent;
6. API key is absent/invalid;
7. timeout configuration is invalid;
8. provider/model/origin/path differs from the frozen request;
9. provider-start already exists;
10. terminal evidence already exists;
11. evidence requires recovery;
12. exclusive canary lock cannot be safely obtained;
13. execution would require `/v1/models`, fallback, or a second provider request;
14. any secret would be written to durable evidence.

After provider-start, stop after the one transport outcome. Never retry.

## 31. Success criteria

NVIDIA-02 implementation is qualified for a live canary when all provider-free tests and CI gates pass and the final branch scope is limited to approved NVIDIA-02 files.

The live canary itself is considered a **transport/protocol pass** when:

1. exactly one NVIDIA provider request is made;
2. the request uses the exact persisted canonical bytes and exact model identity;
3. provider-start evidence precedes the request;
4. NVIDIA-01 returns a valid parsed successful response from the exact Lightning model;
5. one durable terminal event is written;
6. no retry/fallback/provider substitution occurs;
7. no secret is persisted.

`semantic_probe_match` is reported separately and does not change the transport/protocol classification.

## 32. Provider activity accounting

Before the explicit live-canary approval, expected activity is exactly:

```text
NVIDIA catalog calls: 0
NVIDIA inference calls: 0
OX calls: 0
Wolfram calls: 0
other provider/model calls: 0
automatic retries: 0
fallbacks: 0
runtime promotion: NO
NVIDIA inference MCP registration: NO
```

For the authorized live canary, the maximum allowed new activity is:

```text
NVIDIA inference calls: exactly 1
all other provider calls: 0
retries: 0
fallbacks: 0
```

## 33. Expected implementation surface

The implementation plan should aim for the narrowest viable change set, expected to include:

```text
src/byte_mcp/nvidia/canary.py
src/byte_mcp/nvidia/canary_evidence.py
src/byte_mcp/nvidia/__init__.py
src/byte_mcp/nvidia/settings.py        # evidence-root configuration only if needed
scripts/nvidia_lightning_canary.py
tests/nvidia/test_canary.py
tests/nvidia/test_canary_evidence.py
tests/nvidia/test_n02_security_invariants.py
```

Any need to modify provider-neutral NVIDIA-01 production files must be justified by a failing test and called out explicitly.

No OX/Wolfram/server/dependency modification is expected.

## 34. Design invariants summary

NVIDIA-02 is acceptable only if all of the following remain true:

```text
PREPARE != AUTHORIZE
AUTHORIZE != PROVIDER_START
PROVIDER_START happens durably before transmission
PROVIDER_START consumes the one authorization
prepared bytes are the transmitted bytes
one canary identity has at most one live attempt
one live canary performs exactly one NVIDIA inference request
no /v1/models preflight
no retry
no redirect following
no model fallback
no provider fallback
no API key persistence
transport result != semantic probe result
crash after provider-start blocks retransmission
OX remains frozen
Wolfram remains frozen
MCP server remains unchanged
```

## 35. Next phase after NVIDIA-02

If the live Lightning canary succeeds, NVIDIA-03 may characterize and qualify multiple NVIDIA-hosted models and model-specific dialects.

That later phase may compare Lightning, Ultra, DeepSeek, and Kimi, and may define qualification thresholds and role enablement.

NVIDIA-02 must not pre-implement those concerns.
