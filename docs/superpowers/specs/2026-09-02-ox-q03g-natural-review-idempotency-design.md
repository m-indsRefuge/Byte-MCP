# Q03G — Natural Review Authority and Replay-Safe Initial Approval

Date: 2026-09-02  
Status: Approved design  
Repository: Byte-MCP  
Subsystem: OX validation  
Base checkpoint: `d152a9cf8409f8b294c30b7ad8fce327dc23aa61`

## 1. Context

The live `OX-000009` canary proved that the deployed Byte-MCP → Vercel AI Gateway → Z.AI / GLM 5.3 Flash provider path can complete successfully end-to-end.

`OX-000009-A001`:

- was claimed exactly once;
- reached the provider;
- received HTTP 200;
- completed after roughly 190 seconds;
- persisted the raw provider response;
- persisted the assistant response in the immutable review thread;
- recorded `ATTEMPT_OUTCOME=COMPLETED`;
- reconstructs as `REVIEWED`;
- created no A002.

The provider returned a natural Markdown engineering review. That response obeyed the existing OX system mandate, which says:

> Use clear natural text or Markdown. Do not force the response into JSON or another machine schema.

The initial-review service path nevertheless called the client with `json_mode=True` and then passed the returned natural text into `parse_findings()`, which accepts only strict `ox-findings-v1` JSON. The result was an `OXFindingValidationError` after the provider response and `COMPLETED` outcome had already been persisted.

A subsequent approval invocation against the now-`REVIEWED` review encountered `_load_prepared_review(... expected_state=PREPARED)` and surfaced:

`review state does not permit this operation`

The exact transport or orchestration mechanism that caused the duplicate/replayed invocation is not yet proven. Q03G does not depend on proving that upstream cause: the initial approval boundary itself must be replay-safe and must never turn an upstream duplicate into another provider request.

## 2. Problem Statement

The initial OX review path currently combines two incompatible contracts:

1. OX is instructed to produce a rich natural-language engineering review.
2. Byte-MCP treats the same response as if it must be a strict canonical findings document.

This makes a compliant natural review appear as a protocol failure.

Separately, initial approval is state-strict but not idempotent. A duplicate invocation after a successful review surfaces a misleading approval error. The evidence layer prevents a second provider attempt, but the service contract should make replay behavior explicit and safe.

There is also an evidence-semantics ambiguity: a review with no persisted structured findings can currently be surfaced indistinguishably from a review for which Byte explicitly recorded an empty findings set.

## 3. Goals

Q03G will:

1. Make the natural OX review authoritative for the initial provider response.
2. Remove strict findings parsing from the initial provider attempt.
3. Preserve the raw provider response and natural assistant thread exactly.
4. Keep canonical `ox-findings-v1` findings as a separate, explicit, local-only recording step.
5. Make initial approval idempotent for `TRANSMITTING` and `REVIEWED` states without making another provider request.
6. Preserve explicit renewed human approval for retries from `FAILED` or `OUTCOME_UNKNOWN`.
7. Distinguish:
   - structured findings not yet recorded; and
   - structured findings explicitly recorded as an empty set.
8. Preserve Q03A–Q03F provider safety, stale recovery, timeout, async MCP, evidence, and Wolfram behavior.

## 4. Non-Goals

Q03G will not:

- retry `OX-000009`;
- mutate historical OX evidence;
- change revalidation response structure;
- change continuation text behavior;
- change Wolfram tools or schema;
- add automatic retries;
- diagnose or modify ChatGPT, MCP-client, Vercel, or upstream transport replay behavior;
- convert arbitrary Markdown to structured findings automatically;
- use another model/provider call to extract findings;
- add heuristic NLP parsing of OX prose;
- change Q03F's 900-second provider-request deadline.

## 5. Architectural Decision

### 5.1 Natural initial review is authoritative

The initial provider response is a natural-language review.

`OXReviewService._perform_attempt()` will call:

```python
self._client.complete(
    messages,
    json_mode=False,
    attempt_id=attempt_id,
)
```

On a valid `ProviderResult`:

1. persist the raw provider response;
2. append the natural assistant text to the initial thread;
3. record `ATTEMPT_OUTCOME=COMPLETED`;
4. audit the completed attempt;
5. return a natural-review receipt.

The initial path will not call `parse_findings()`.

A natural Markdown response is therefore a successful review result, not an invalid findings document.

### 5.2 Canonical findings are an explicit local step

Structured findings remain `ox-findings-v1`.

They are recorded through the existing local-only path:

`ox_continue(mode="record_findings", findings=[...])`

No provider request is involved in that operation.

Byte is responsible for deciding which claims from OX's natural review should become canonical findings. This preserves the separation between:

- OX's independent engineering analysis; and
- Byte's explicit structured adjudication workflow.

An explicit empty findings list is meaningful: it means Byte reviewed the natural response and recorded that no canonical defects were raised.

### 5.3 Findings recording state must be observable

The system must distinguish:

- `findings_recorded = false` — no canonical findings decision has been recorded yet;
- `findings_recorded = true` with `findings=[]` — Byte explicitly recorded zero findings.

The persisted canonical findings payload remains unchanged:

```json
{
  "protocol_version": "ox-findings-v1",
  "findings": []
}
```

Recording status is service/evidence metadata, not an extra field inside the canonical findings protocol.

The evidence layer will expose a bounded way to determine whether the canonical findings artifact exists. The service layer will surface that status in review/findings responses.

## 6. Initial Approval State Machine

`ox_review(review_id=..., approve=true, retry=false)` becomes idempotent.

### PREPARED

Normal first approval:

```text
PREPARED
  → claim A001
  → persist attempt identity
  → persist outbound thread
  → exactly one provider request
  → persist provider response
  → persist natural review
  → COMPLETED
  → REVIEWED
```

The returned receipt includes at minimum:

- `review_id`
- `attempt_id`
- `state`
- `manifest_sha256`
- `review_text`
- `findings_recorded`
- `usage`
- `replayed`
- `provider_request_performed`

For the original successful invocation:

- `replayed = false`
- `provider_request_performed = true`

### TRANSMITTING

A duplicate/replayed ordinary approval while the current initial attempt is still in flight:

- performs zero provider requests;
- allocates no new attempt;
- returns a local receipt for the current attempt;
- reports `state=TRANSMITTING`;
- reports `replayed=true`;
- reports `provider_request_performed=false`.

It must not wait for, join, or cancel the original provider worker.

### REVIEWED

A duplicate/replayed ordinary approval after successful completion:

- performs zero provider requests;
- allocates no new attempt;
- returns the existing natural review from local evidence;
- reports the existing completed attempt;
- reports `state=REVIEWED`;
- reports `replayed=true`;
- reports `provider_request_performed=false`.

No A002 is created.

### FAILED / OUTCOME_UNKNOWN

Ordinary approval remains prohibited.

The service returns an approval error indicating that renewed explicit retry approval is required.

The only provider-capable next path is the existing explicit retry operation.

### Recovered or malformed evidence

Existing recovery and evidence-integrity guards remain authoritative. Idempotency must not bypass recovery warnings, malformed evidence, manifest checks, or attempt-integrity rules.

## 7. Replay Receipt Reconstruction

Q03G will not add a second mutable "result" database.

Replay receipts are reconstructed from existing immutable evidence:

- review state and attempts from `EvidenceStore.get_review`;
- manifest digest from the persisted manifest;
- natural review text from the final assistant message in the initial thread;
- findings-recorded status from canonical findings artifact existence.

Provider usage may be returned on the original successful invocation from `ProviderResult`. A replayed receipt may omit usage or return locally reconstructable usage only if the existing persisted response can supply it through a bounded evidence API.

Q03G must not parse arbitrary raw provider JSON directly from the server layer.

## 8. Evidence Changes

Historical review evidence remains immutable.

Q03G may add read-only EvidenceStore capabilities needed to:

- determine whether canonical findings have been explicitly persisted;
- read the existing provider response if replay receipt reconstruction requires it.

No existing event meaning changes.

The canonical state transition remains:

`ATTEMPT_OUTCOME=COMPLETED → REVIEWED`

A successful natural review does not require a findings artifact for the review itself to be `REVIEWED`.

## 9. Service/API Behavior

### Initial success

Illustrative receipt:

```json
{
  "review_id": "OX-000010",
  "attempt_id": "OX-000010-A001",
  "state": "REVIEWED",
  "manifest_sha256": "...",
  "review_text": "# OX Review ...",
  "findings_recorded": false,
  "usage": {},
  "replayed": false,
  "provider_request_performed": true
}
```

### Replay after success

```json
{
  "review_id": "OX-000010",
  "attempt_id": "OX-000010-A001",
  "state": "REVIEWED",
  "manifest_sha256": "...",
  "review_text": "# OX Review ...",
  "findings_recorded": false,
  "replayed": true,
  "provider_request_performed": false
}
```

### Replay while transmitting

```json
{
  "review_id": "OX-000010",
  "attempt_id": "OX-000010-A001",
  "state": "TRANSMITTING",
  "manifest_sha256": "...",
  "findings_recorded": false,
  "replayed": true,
  "provider_request_performed": false
}
```

### Findings view before explicit recording

The read-only findings view will indicate `recorded=false`. It must not imply that an empty canonical decision has already been made.

### Findings view after explicit empty recording

After:

`ox_continue(mode="record_findings", findings=[])`

the findings view reports:

- `recorded=true`;
- `protocol_version="ox-findings-v1"`;
- `findings=[]`.

## 10. Error Handling

Provider error outcome mappings remain unchanged.

If the initial natural response is returned successfully by the provider:

- response persistence failure remains an evidence error;
- thread persistence failure remains an evidence error;
- successful natural text is not subjected to findings-schema validation.

`OXFindingValidationError` remains relevant to operations that explicitly validate structured findings/revalidation findings.

Q03G must not relabel a provider-completed attempt as `NOT_SENT`.

## 11. Concurrency and Safety

EvidenceStore's per-review lock remains the authority for attempt claiming.

Q03G's idempotency logic must be race-safe:

- exactly one concurrent PREPARED caller may claim A001;
- another caller observing TRANSMITTING returns a replay receipt;
- no second caller may allocate A002 through ordinary approval;
- no duplicate provider request occurs.

A concurrency regression test will hold the first provider call open while issuing a second ordinary approval and assert provider client call count remains exactly one.

## 12. Test Strategy

Q03G follows TDD.

### RED contracts

1. **Natural Markdown initial review**
   - provider returns representative Markdown;
   - current implementation raises `OXFindingValidationError`;
   - desired behavior is a normal `REVIEWED` receipt.

2. **Replay after completed initial review**
   - first approval completes;
   - second ordinary approval currently raises `review state does not permit this operation`;
   - desired behavior is a local replay receipt;
   - provider call count must remain exactly one.

3. **Replay during active transmission**
   - first call blocks inside a fake provider client;
   - second ordinary approval occurs while state is `TRANSMITTING`;
   - desired behavior is a local replay receipt;
   - provider call count remains exactly one;
   - no A002.

4. **Findings-recording distinction**
   - completed natural review before `record_findings` reports `recorded=false`;
   - explicit `record_findings([])` persists the canonical empty set;
   - subsequent view reports `recorded=true`.

5. **Retry boundary**
   - FAILED and OUTCOME_UNKNOWN ordinary approval still cannot send;
   - explicit renewed retry remains required.

### GREEN/regression gates

Run:

- focused Q03G tests;
- OX review service tests;
- OX evidence tests;
- OX continuation tests;
- OX MCP surface tests;
- Q03A/Q03B/Q03C async-provider safety tests;
- Q03E orphan recovery tests;
- Q03F total-deadline tests;
- revalidation tests;
- complete Python regression;
- Ruff;
- compileall;
- launcher Pester suite.

No live provider call is needed for local Q03G qualification.

## 13. Historical Evidence Acceptance

Q03G implementation and promotion must fingerprint and preserve:

### OX-000007

Historical immutable `OUTCOME_UNKNOWN`; never retry.

### OX-000008

Recovered exactly-once `OUTCOME_UNKNOWN`; no A002.

### OX-000009

Successful exactly-once completed canary:

- A001 only;
- `ATTEMPT_OUTCOME=COMPLETED`;
- raw provider response preserved;
- natural assistant thread preserved;
- no A002.

Q03G must not retrofit or mutate `OX-000009` findings evidence. Its natural review remains historical evidence of the pre-Q03G contract mismatch.

## 14. Deployment Acceptance

After local qualification:

1. promote one exact Q03G checkpoint transactionally;
2. preserve the qualified Q03D supervisor unless Q03G explicitly changes launcher behavior (not expected);
3. restart managed Byte-MCP;
4. confirm all readiness dimensions;
5. verify live tool schemas;
6. verify the three historical OX incidents remain unchanged;
7. perform provider-free MCP acceptance.

A future live Q03G canary requires fresh explicit human authorization.

Its success contract is:

- exactly one provider request;
- one A001;
- natural review returned directly through `ox_review`;
- `REVIEWED`;
- no parser exception;
- `findings_recorded=false` initially;
- a repeated ordinary approval makes zero additional provider requests and returns the local existing result.

## 15. Security Invariants

Q03G preserves these invariants:

- no automatic retry;
- no implicit resend after ambiguous outcomes;
- renewed human approval for retry;
- immutable attempt identity;
- append-only state history;
- provider response persistence before completion state;
- local-only findings recording;
- no credential leakage into review packets or returned evidence;
- strict repository and manifest verification before first transmission;
- Q03F absolute provider-request deadline remains 900 seconds;
- Wolfram provider behavior and schema remain unaffected.

## 16. Deferred Follow-Ups

The following observations are intentionally outside Q03G:

1. identify which upstream MCP/tool lifecycle produced the duplicate/replayed approval invocation observed during `OX-000009`;
2. update provider-boundary documentation for the already-deployed Q03F absolute deadline;
3. add dedicated connect-phase and write-phase absolute-deadline tests for the uncertainty noted by OX;
4. review the cosmetic HTTPX transport type annotation noted by OX.

Q03G makes duplicate initial approval harmless even before the upstream replay source is fully diagnosed.
