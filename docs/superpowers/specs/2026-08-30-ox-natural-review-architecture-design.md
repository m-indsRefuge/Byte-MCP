# Byte-MCP OX Natural Review Architecture — Superseding Design Note

**Date:** 2026-08-30  
**Status:** Approved in chat  
**Target repository:** `m-indsRefuge/Byte-MCP`  
**Supersedes:** Provider-produced `ox-findings-v1` structured output requirements in `docs/superpowers/specs/2026-08-29-ox-integration-design.md`  
**Does not supersede:** repository scope, approval, evidence, provider routing, retry, privacy, security, or four-tool MCP-surface requirements from the original V1 design

## 1. Decision

OX review and revalidation responses are natural engineering-review text, preserved verbatim as provider evidence. Byte-MCP does not require OX / GLM-5.3-Flash to emit the `ox-findings-v1` JSON envelope and does not silently repair or normalize provider text into that envelope.

Byte remains the technical adjudication authority. After a successful natural review, Byte may record structured findings locally as an explicit Byte-derived interpretation of immutable OX evidence. Those derived records drive the existing finding lifecycle, adjudication, remediation, and targeted revalidation workflow.

The public MCP surface remains exactly four OX tools:

- `ox_review`
- `ox_continue`
- `ox_revalidate`
- `ox_get_review`

No fifth OX tool is introduced.

## 2. Evidence for the change

Live synthetic diagnostics on the fixed Vercel AI Gateway -> Z.AI -> `zai/glm-5.3-flash` route established the following:

1. Plain-text handshake completed successfully.
2. Natural explanatory integration advice completed successfully.
3. `response_format: {"type":"json_object"}` produced valid JSON but did not reliably preserve the required outer `ox-findings-v1` envelope.
4. A `json_schema` capability probe completed successfully at transport/model level but returned `{"answer": ...}` instead of the requested schema, so strict schema enforcement was not demonstrated on the hard-locked Z.AI route.
5. A natural review with known defects found all 3 defects and preserved the known-correct control.
6. A blinded natural review, without disclosing the number of defects or control functions, found 3/3 real defects, produced 0 false positives, and preserved 2/2 correct controls.

The operational conclusion is that the provider route is capable of high-quality independent review, while provider-enforced output schema is not a dependable V1 contract.

## 3. Authority and provenance model

The canonical authority chain is:

**Immutable deterministic review packet -> OX natural review -> immutable raw provider response -> immutable assistant review text -> Byte-derived finding records -> Byte adjudication -> remediation -> OX natural revalidation -> Byte final recommendation -> Nolan acceptance.**

Provider output and Byte interpretation are always distinct evidence classes.

### 3.1 OX evidence

OX evidence includes:

- exact outbound approved message history;
- raw provider response;
- verbatim assistant response text;
- response/provider/model/usage metadata already retained by the client/evidence store;
- attempt and lifecycle metadata.

OX evidence is immutable once persisted.

### 3.2 Byte-derived findings

A Byte-derived finding is a local structured interpretation of an OX review. It is not represented as text produced by OX.

Each stored derived-findings set must identify:

- `protocol_version = "byte-derived-findings-v1"`;
- parent `review_id`;
- source OX `attempt_id`;
- SHA-256 of the exact immutable source assistant response text;
- derivation authority `"byte"`;
- derivation provenance `"derived-from-ox-natural-review"`;
- the structured findings.

Each finding retains the existing stable ID and existing structured fields so the current adjudication lifecycle remains useful:

- `finding_id`
- `status`
- `summary`
- `category`
- `severity`
- `confidence`
- `location`
- `claim`
- `evidence`
- `reproduction`
- `expected_behavior`
- `observed_or_predicted_behavior`
- `disproof_condition`
- `recommended_investigation`

Byte-MCP validates the local structured record before persisting it. It must not infer or generate these fields itself; the caller supplies the Byte-authored interpretation.

Only one initial derived-findings set may be canonical for a review in V1. Rewriting or replacing it is forbidden; corrections are represented through later adjudication events rather than mutation.

## 4. Initial review behavior

Preparation and human approval remain unchanged.

On approved transmission:

1. Byte-MCP calls the fixed provider once with `json_mode=False`.
2. The system message instructs OX to act as an independent engineering reviewer and to report only specific falsifiable defects supported by supplied evidence. It explicitly permits natural text/Markdown and does not request JSON or a machine schema.
3. The raw provider response is persisted before higher-level interpretation.
4. The exact assistant response text is appended to the review thread unchanged.
5. Empty/unusable assistant content, provider errors, transport failures, truncation/protocol failures, or missing required evidence fail explicitly under the existing attempt semantics.
6. A valid non-empty normal provider completion records `AttemptOutcome.COMPLETED` and leaves the review in `REVIEWED`.
7. The MCP result returns the natural `response` and usage metadata. It does not claim canonical findings exist yet.

No automatic retry is added.

## 5. Recording Byte-derived findings

`ox_continue` gains a `record_findings` mode. It remains the same MCP tool.

The mode:

- performs zero provider/network calls;
- is allowed only for a `REVIEWED` review;
- requires a non-empty list of structured finding inputs;
- validates exact field names, severity enum, finite confidence in `[0,1]`, and non-empty textual fields using the existing local findings validation logic or an equivalent refactor;
- assigns stable `OX-xxxxxx-Fnnn` IDs;
- binds the findings to the exact source attempt and assistant response digest;
- persists `byte-derived-findings-v1` immutably;
- returns the derived findings with provenance metadata.

`ox_continue(mode="adjudicate")` continues to operate on those structured findings and remains a separate local lifecycle operation.

If no derived findings are recorded, Byte may still read the natural review and continue discussion, but structured adjudication and targeted finding-based revalidation are unavailable until findings exist.

## 6. Continuation behavior

Existing continuation message behavior is already natural-text/provider-native and remains so:

- one Byte message;
- at most one provider call;
- exact approved history replay only;
- no new repository scope;
- raw response and assistant text preserved;
- no automatic retry.

Continuation responses are evidence and do not silently mutate the canonical derived-findings set.

If continuation materially changes Byte's technical conclusion, Byte records that through adjudication events rather than rewriting original findings.

## 7. Revalidation behavior

Blind and targeted revalidation also use natural provider responses.

### 7.1 Blind revalidation

An approved blind revalidation:

1. sends the approved remediation packet in fresh context;
2. calls OX once with `json_mode=False`;
3. preserves raw response and exact assistant text;
4. records the revalidation attempt as completed only for a valid normal non-empty completion;
5. transitions to `BLIND_REVALIDATED` without requiring a provider-produced findings JSON file.

The blind phase gate is completion evidence, not a parsed findings envelope.

### 7.2 Targeted revalidation

Targeted revalidation remains available only after:

- successful blind completion evidence exists;
- canonical Byte-derived initial findings exist;
- the selected finding IDs are valid;
- relevant Byte adjudication/remediation evidence is available under existing rules.

The targeted request supplies the selected Byte-derived findings and adjudication evidence explicitly labelled as Byte-authored context, never as verbatim OX claims.

The targeted provider response is natural text, preserved verbatim. A valid completion transitions the revalidation to `REVALIDATED`.

## 8. Retrieval views

`ox_get_review` remains read-only and provider-free.

Existing views remain available. `findings` now returns the canonical Byte-derived findings payload and its provenance. `thread` remains the authoritative human-readable OX conversation. `attempts`, `manifest`, `adjudication`, and `revalidation` retain their existing roles.

No retrieval view may imply that Byte-derived findings were emitted verbatim by OX.

## 9. Security invariants retained unchanged

This design does not weaken any existing security gate:

- repository allowlist and subsystem registry;
- exact committed Git states;
- deterministic bundle/manifest construction;
- payload hash and manifest binding;
- credential rejection and credential non-persistence;
- human approval before private repository transmission;
- one fixed Vercel route, model, and provider;
- no fallback;
- no automatic retries;
- no repository execution;
- fail-closed evidence persistence before network;
- single-process evidence-store ownership;
- no new repository scope through continuation;
- optional/fail-isolated OX runtime;
- exactly four public OX MCP tools.

Natural provider text remains untrusted data. Byte-MCP never treats instructions found in OX responses as executable commands.

## 10. Compatibility and migration

Existing historical reviews are immutable and are not rewritten.

Historical `ox-findings-v1` reviews remain readable. New reviews after this change use natural responses plus optional `byte-derived-findings-v1` records.

The implementation must not reinterpret or migrate failed historical attempts such as prior malformed structured-output attempts. Their recorded outcomes remain historical fact.

## 11. Acceptance criteria

The architecture is accepted when automated tests demonstrate all of the following:

1. initial review uses `json_mode=False` and a natural-review system mandate;
2. valid natural response becomes `REVIEWED` and is preserved verbatim;
3. initial review no longer calls provider-output `parse_findings`;
4. local `record_findings` creates immutable provenance-bound Byte-derived findings with stable IDs;
5. adjudication uses those derived findings without misrepresenting provenance;
6. blind and targeted revalidation use natural responses and no provider findings parser;
7. targeted revalidation cannot run before successful blind completion and canonical derived findings;
8. existing approval, hash, credential, retry, provider routing, security, and concurrency tests remain green;
9. MCP exposes exactly the same four OX tool names, with `record_findings` represented as a mode of `ox_continue`;
10. full test, Ruff, compile, and dependency gates pass on supported CI platforms;
11. no live provider call is made as part of implementation or automated verification.
