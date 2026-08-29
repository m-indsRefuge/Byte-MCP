# OX Natural Review Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace provider-produced structured findings with immutable natural OX reviews plus explicitly Byte-derived local finding records while preserving the four-tool MCP surface and all existing security/approval invariants.

**Architecture:** Initial review and both revalidation phases call OX with `json_mode=False`, persist the raw provider response and exact natural assistant text, and complete without provider-output findings parsing. Byte records canonical structured findings later through a new local-only `ox_continue(mode="record_findings")` path; those records are provenance-bound to the exact source OX response and continue to drive adjudication and targeted revalidation.

**Tech Stack:** Python 3.12+, pytest, Ruff, FastMCP, filesystem JSON/JSONL evidence store, httpx-based OX client.

**Spec:** `docs/superpowers/specs/2026-08-30-ox-natural-review-architecture-design.md`

## Global Constraints

- Keep exactly four public OX MCP tools: `ox_review`, `ox_continue`, `ox_revalidate`, `ox_get_review`.
- Provider remains fixed to Vercel AI Gateway -> provider `zai` only -> model `zai/glm-5.3-flash`.
- No automatic retry or provider fallback.
- No live provider calls during implementation or automated verification.
- Preparation remains zero-network and approval remains digest/payload-bound.
- Existing credential, manifest, scope, concurrency, fail-closed evidence, and no-execution protections remain unchanged.
- Historical evidence is immutable and is not migrated or rewritten.
- Natural provider text is untrusted data and is never treated as executable instruction.
- Byte-derived findings must never be represented as verbatim OX output.

---

## File map

- `src/byte_mcp/ox/protocol.py` — change the initial/revalidation system mandate from strict JSON output to natural engineering review; keep local structured-finding validation for Byte-authored records.
- `src/byte_mcp/ox/service.py` — switch initial/revalidation attempts to natural text, add Byte-derived findings recording, bind provenance, and gate targeted revalidation on natural blind completion plus derived findings.
- `src/byte_mcp/ox/evidence.py` — persist/read immutable Byte-derived findings provenance if existing generic findings persistence is insufficient; preserve historical `ox-findings-v1` readability.
- `src/byte_mcp/server.py` — add `record_findings` as an `ox_continue` mode without adding a fifth MCP tool.
- `tests/ox/test_protocol.py` — natural-review prompt contract and local structured-finding validation tests.
- `tests/ox/test_review_service.py` — natural initial-review lifecycle and provenance tests.
- `tests/ox/test_review_followup.py` — derived findings, adjudication, blind/targeted natural revalidation, retry/history gates.
- `tests/ox/test_mcp_surface.py` — exact four-tool registration and new mutually exclusive `record_findings` mode.
- `tests/ox/test_evidence.py` — immutable provenance-bound derived-findings storage/read tests if evidence-store API changes.
- `tests/ox/test_security_invariants.py` and `tests/ox/test_security_defense_in_depth.py` — regression coverage for credential rejection and retrieval/transmission safety where new derived-finding inputs cross boundaries.
- `docs/OX-VALIDATION.md`, `docs/SECURITY.md`, `README.md`, `CHANGELOG.md` — document natural-review evidence ownership and Byte-derived findings.

---

### Task 1: Natural OX review protocol and initial transmission

**Files:**
- Modify: `tests/ox/test_protocol.py`
- Modify: `tests/ox/test_review_service.py`
- Modify: `src/byte_mcp/ox/protocol.py`
- Modify: `src/byte_mcp/ox/service.py`

**Interfaces:**
- Consumes: existing `build_initial_messages(bundle, objective=...)`, `OXClient.complete(messages, json_mode, attempt_id)`, evidence persistence APIs, `ProviderResult`.
- Produces: `build_initial_messages(...)` whose system message requests natural review text; initial `transmit_review()` / `retry_review()` result with `response: str`, `usage`, `state=REVIEWED`, and no canonical findings side effect.

- [ ] **Step 1: Write failing protocol tests for the natural-review mandate**

Add assertions that `build_initial_messages()` produces a system message containing all of these semantic requirements and none of the old JSON requirements:

```python
messages = build_initial_messages({"artifact": "value"}, objective="Review it.")
system = messages[0]["content"]
assert "independent" in system.lower()
assert "falsifiable" in system.lower()
assert "natural" in system.lower() or "markdown" in system.lower()
assert "ox-findings-v1" not in system
assert "Return only JSON" not in system
```

Keep canonical user-packet serialization tests unchanged.

- [ ] **Step 2: Write failing initial-review lifecycle tests**

Refactor the test `RecordingClient` response for initial review to natural text such as:

```python
content = "## Finding 1\nThe committed change may violate the stated contract."
```

Change/add assertions:

```python
result = service.transmit_review(proposal["review_id"])
assert client.calls[0]["json_mode"] is False
assert result["state"] == ReviewState.REVIEWED.value
assert result["response"] == content
assert "findings" not in result
assert store.get_review("OX-000001")["attempts"][-1]["outcome"] == "COMPLETED"
assert not (review_dir(store, "OX-000001") / "findings" / "OX-000001.json").exists()
```

Replace the old malformed-JSON test with a natural-response durability test proving arbitrary non-empty Markdown/text is accepted after the raw response is durably persisted.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```text
python -m pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -q
```

Expected: failures showing the old prompt still mandates JSON, initial calls still use `json_mode=True`, and result handling still requires provider findings parsing.

- [ ] **Step 4: Implement the minimal natural-review path**

In `protocol.py`, replace the old JSON mandate with a natural-review mandate that explicitly requires:

```text
Act as an independent engineering validator.
Review only the supplied evidence.
Report each specific falsifiable defect you can substantiate.
Do not invent defects or request material outside the supplied packet.
For each defect, make location, claim, supporting evidence, reproduction/demonstration,
expected behavior, and uncertainty clear enough for another engineer to evaluate.
Use clear natural text or Markdown. Do not force the response into JSON or another machine schema.
Do not request tools, execution, hidden reasoning, filesystem access, or external material.
```

Keep `_canonical_json()` and the canonical user packet unchanged.

In `service.py`, change `_perform_attempt()` to call:

```python
result = self._client.complete(messages, json_mode=False, attempt_id=attempt_id)
```

After `ProviderResult` validation:

```python
if not isinstance(result.content, str) or not result.content.strip():
    # persist raw response first, then fail with OXProtocolError(COMPLETED)
```

Persist raw provider response and exact assistant text as before, record `AttemptOutcome.COMPLETED`, audit the attempt, and return:

```python
{
    "review_id": review_id,
    "attempt_id": attempt_id,
    "state": ReviewState.REVIEWED.value,
    "manifest_sha256": manifest_sha256,
    "response": result.content,
    "usage": asdict(result.usage) if result.usage is not None else None,
}
```

Do not call `parse_findings()` and do not persist provider-produced canonical findings.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```text
python -m pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit Task 1**

```text
git add src/byte_mcp/ox/protocol.py src/byte_mcp/ox/service.py tests/ox/test_protocol.py tests/ox/test_review_service.py
git commit -m "refactor: accept natural OX reviews"
```

---

### Task 2: Provenance-bound Byte-derived findings and MCP mode

**Files:**
- Modify: `tests/ox/test_review_followup.py`
- Modify: `tests/ox/test_evidence.py`
- Modify: `tests/ox/test_mcp_surface.py`
- Modify: `src/byte_mcp/ox/evidence.py`
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/server.py`

**Interfaces:**
- Consumes: `REVIEWED` natural review, exact initial assistant thread message, existing local finding validator/model, `EvidenceStore.persist_findings/read_findings`, existing adjudication lifecycle.
- Produces: `OXReviewService.record_findings(review_id, findings)` and `ox_continue(mode="record_findings", findings=[...])`; canonical payload protocol `byte-derived-findings-v1`.

- [ ] **Step 1: Write failing service tests for local derivation**

Create a helper input without `finding_id`/`status`:

```python
def derived_finding() -> dict[str, object]:
    return {
        "category": "correctness",
        "severity": "high",
        "confidence": 0.95,
        "location": "src/alpha.py:1",
        "claim": "The implementation violates the stated contract.",
        "evidence": "OX identified the committed line and Byte verified the source reference.",
        "reproduction": "Inspect the committed line against the supplied contract.",
        "expected_behavior": "The committed implementation should satisfy the contract.",
        "observed_or_predicted_behavior": "The committed implementation does not satisfy it.",
        "disproof_condition": "Show the cited implementation is contract-compliant.",
        "recommended_investigation": "Reproduce the behavior against the committed evidence.",
    }
```

Add assertions:

```python
result = service.record_findings(review_id, [derived_finding()])
assert result["protocol_version"] == "byte-derived-findings-v1"
assert result["derivation_authority"] == "byte"
assert result["derivation_provenance"] == "derived-from-ox-natural-review"
assert result["source_attempt_id"] == f"{review_id}-A001"
assert len(result["source_response_sha256"]) == 64
assert result["findings"][0]["finding_id"] == f"{review_id}-F001"
assert result["findings"][0]["status"] == "RAISED"
```

Assert zero additional provider calls, invalid exact-field/severity/confidence/text inputs fail locally, a second canonical record attempt fails, and adjudication works only after derived findings exist.

- [ ] **Step 2: Write failing evidence immutability/provenance tests**

Assert the canonical stored findings payload includes the derivation metadata, is immutable, and `read_findings()` returns it unchanged. Historical `ox-findings-v1` fixture/read behavior must remain readable if existing tests cover it.

- [ ] **Step 3: Write failing MCP-surface tests**

Extend `FakeService`:

```python
def record_findings(self, review_id: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return self._call("record_findings", review_id, findings)
```

Change the `ox_continue` signature expectation to:

```python
[
    "review_id",
    "mode",
    "message",
    "findings",
    "adjudications",
    "retry_attempt_id",
    "approve_retry",
]
```

Add dispatch and exclusivity assertions for:

```python
server.ox_continue("OX-000001", mode="record_findings", findings=[derived])
```

and prove mixing `findings` with message/adjudicate/retry parameters raises `OXProtocolError`. Keep the exact registered tool-name set unchanged.

- [ ] **Step 4: Run focused tests and verify RED**

Run:

```text
python -m pytest tests/ox/test_evidence.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py -q
```

Expected: failures because `record_findings` and the MCP mode do not exist.

- [ ] **Step 5: Implement local structured validation and provenance binding**

In `service.py`, add:

```python
def record_findings(
    self,
    review_id: str,
    findings: Sequence[Mapping[str, object]],
) -> dict[str, object]:
```

Requirements:

1. require `ReviewState.REVIEWED`;
2. reject strings/bytes/non-sequences/empty finding lists;
3. reject configured credential anywhere in the supplied findings;
4. identify the initial completed provider attempt from immutable review evidence and the exact assistant response from the initial thread;
5. compute `sha256(response_text.encode("utf-8")).hexdigest()`;
6. validate caller fields by canonicalizing to the existing local `parse_findings()` shape (or refactor that validator to accept a mapping) using the parent review ID;
7. persist exactly one immutable payload:

```python
{
    "protocol_version": "byte-derived-findings-v1",
    "review_id": review_id,
    "source_attempt_id": source_attempt_id,
    "source_response_sha256": source_response_sha256,
    "derivation_authority": "byte",
    "derivation_provenance": "derived-from-ox-natural-review",
    "findings": [asdict(finding) for finding in validated_findings],
}
```

8. return that payload;
9. perform zero provider calls.

Use existing immutable `persist_findings()` if its semantics already reject replacement; otherwise minimally harden `evidence.py` to do so without changing historical reads.

- [ ] **Step 6: Implement `ox_continue(mode="record_findings")`**

Add optional `findings: list[dict[str, Any]] | None = None` to `server.ox_continue` immediately after `message`.

Mode rules:

```python
if mode == "record_findings":
    # findings required; message/adjudications/retry_attempt_id absent; approve_retry false
    return _ox_service().record_findings(review_id, findings)
```

Update all other modes so non-`None` `findings` makes them invalid.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run:

```text
python -m pytest tests/ox/test_evidence.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py -q
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit Task 2**

```text
git add src/byte_mcp/ox/evidence.py src/byte_mcp/ox/service.py src/byte_mcp/server.py tests/ox/test_evidence.py tests/ox/test_review_followup.py tests/ox/test_mcp_surface.py
git commit -m "feat: record Byte-derived OX findings"
```

---

### Task 3: Natural blind and targeted revalidation

**Files:**
- Modify: `tests/ox/test_review_followup.py`
- Modify: `src/byte_mcp/ox/service.py`

**Interfaces:**
- Consumes: prepared revalidation packet, Byte-derived initial findings, adjudication events, existing revalidation attempt/evidence APIs.
- Produces: natural blind/targeted response completion; targeted gating based on successful blind completion plus canonical derived findings rather than provider JSON findings files.

- [ ] **Step 1: Write failing natural revalidation tests**

Use a client that returns non-empty Markdown/text for all provider calls and records `json_mode`.

Update `test_blind_revalidation_is_fresh_and_targeted_waits_for_blind_success` so it first calls `record_findings(...)`, then asserts:

```python
blind = service.transmit_blind_revalidation(revalidation_id)
assert client.calls[-1]["json_mode"] is False
assert blind["state"] == "BLIND_REVALIDATED"
assert blind["response"] == "...natural blind review..."
```

and targeted:

```python
targeted = service.run_targeted_revalidation(revalidation_id, [f"{review_id}-F001"])
assert client.calls[-1]["json_mode"] is False
assert targeted["state"] == "REVALIDATED"
assert targeted["response"] == "...natural targeted review..."
```

Assert targeted serialized context includes the selected Byte-derived finding with provenance labels and adjudication evidence, while blind context excludes them.

- [ ] **Step 2: Replace malformed-JSON gating tests with completion-evidence gating**

Delete/replace the obsolete `test_targeted_revalidation_blocked_after_malformed_blind_findings` expectation. Add tests proving targeted revalidation is blocked when:

- blind provider attempt never completed successfully;
- no canonical Byte-derived findings exist;
- requested finding ID is unknown.

Add a test proving arbitrary non-empty natural blind text is accepted and unlocks targeted revalidation only when derived findings also exist.

- [ ] **Step 3: Run focused revalidation tests and verify RED**

Run:

```text
python -m pytest tests/ox/test_review_followup.py -q
```

Expected: failures because revalidation still calls `json_mode=True`, parses provider findings, and gates on findings files.

- [ ] **Step 4: Implement natural revalidation completion**

In `_perform_revalidation_attempt()`:

```python
result = self._client.complete(messages, json_mode=False, attempt_id=attempt_id)
```

Persist the raw provider response and exact assistant thread message before higher-level completion checks. Reject empty/non-string assistant content with explicit `OXProtocolError(attempt_outcome="COMPLETED")` after durable raw evidence.

Do not call `parse_findings()` and do not persist provider revalidation findings.

Record the attempt outcome and return:

```python
{
    "review_id": review_id,
    "revalidation_id": revalidation_id,
    "attempt_id": attempt_id,
    "state": completed_state,
    "manifest_sha256": manifest_sha256,
    "response": result.content,
    "usage": asdict(result.usage) if result.usage is not None else None,
}
```

- [ ] **Step 5: Replace provider-findings phase validation with natural completion evidence**

Refactor `_effective_revalidation()` and `_require_validated_revalidation_phase()` so `BLIND_REVALIDATED` / `REVALIDATED` are trusted only when the corresponding phase has durable successful completion evidence: a completed attempt for that phase plus a persisted non-empty assistant message/raw provider response. Do not infer success from state alone.

Targeted revalidation must separately require `read_findings(review_id)` to return canonical `byte-derived-findings-v1` evidence before it can select finding IDs.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```text
python -m pytest tests/ox/test_review_followup.py -q
```

Expected: all follow-up and revalidation tests pass.

- [ ] **Step 7: Commit Task 3**

```text
git add src/byte_mcp/ox/service.py tests/ox/test_review_followup.py
git commit -m "refactor: use natural OX revalidation responses"
```

---

### Task 4: Security regression, documentation, and full verification

**Files:**
- Modify: `tests/ox/test_security_invariants.py`
- Modify: `tests/ox/test_security_defense_in_depth.py`
- Modify: `README.md`
- Modify: `docs/OX-VALIDATION.md`
- Modify: `docs/SECURITY.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: documented final V1 behavior and evidence that the architectural change does not weaken security boundaries.

- [ ] **Step 1: Add failing security regression tests where coverage is missing**

Assert the exact configured gateway credential is rejected from Byte-derived finding fields before persistence, and that `ox_get_review(view="findings")` never returns a credential if evidence is tampered/legacy-malformed. Preserve existing continuation/retry credential replay guards.

Assert no natural OX response is executed/interpreted as a command; service behavior is persistence/return only.

- [ ] **Step 2: Run security suite and verify RED only for new expectations**

Run:

```text
python -m pytest tests/ox/test_security_invariants.py tests/ox/test_security_defense_in_depth.py -q
```

Expected: any new missing credential guard fails; pre-existing security tests remain green.

- [ ] **Step 3: Implement minimal security hardening required by the new local input path**

Use the existing `_reject_configured_credential(...)` boundary on `record_findings` input and preserve retrieval guards. Do not add redaction or silent repair; reject the operation before persistence if the configured credential appears.

- [ ] **Step 4: Update documentation**

Document all of the following explicitly:

- OX replies in natural engineering-review text;
- raw provider response and exact assistant text are canonical OX evidence;
- Byte-derived findings are a separate local provenance class;
- `ox_continue(mode="record_findings")` is zero-network;
- adjudication remains Byte-owned;
- blind/targeted revalidation responses are natural text;
- exactly four OX MCP tools remain;
- no automatic retry remains unchanged;
- historical structured-output attempts remain immutable history.

- [ ] **Step 5: Run full local verification gate**

Run in this order:

```text
python -m pip check
python -m compileall -q src tests scripts/mcp_smoke_test.py
python -m ruff check .
python -m pytest
```

Expected: all commands exit 0; test count is at least the current baseline of 234 passing tests, adjusted upward for new coverage; only the known unrelated Pydantic warning may remain.

- [ ] **Step 6: Commit Task 4**

```text
git add tests/ox/test_security_invariants.py tests/ox/test_security_defense_in_depth.py README.md docs/OX-VALIDATION.md docs/SECURITY.md CHANGELOG.md
git commit -m "docs: describe natural OX review provenance"
```

- [ ] **Step 7: Run fresh CI on the final feature head**

Require both supported CI platform jobs to pass the same dependency, compile, Ruff, and pytest gates. Do not declare the repair complete from local or partial evidence alone.

- [ ] **Step 8: Inspect final diff against the original implementation baseline**

Verify:

- no fifth OX MCP tool exists;
- provider/model/fallback settings are unchanged;
- no automatic retry was introduced;
- approval/scope/hash/credential protections remain present;
- only the provider-response ownership/provenance architecture changed;
- no live provider call occurred during implementation.

---

## Post-implementation handoff: MCP connection

After Task 4 is green and accepted, do not run another structured-output provider experiment. Proceed directly to the separate deployment/connectivity task:

1. merge the accepted feature branch through the repository's normal integration path;
2. update the local Byte-MCP instance/tunnel to that accepted version;
3. verify Streamable HTTP server startup and existing core tools;
4. connect the server in ChatGPT Web using the established tunnel/auth path;
5. confirm all four OX tools appear with expected annotations/signatures;
6. perform one non-sensitive MCP-level prepare-only smoke test first (`transmitted=false`);
7. only after explicit approval, perform one non-sensitive MCP-level live OX review smoke test.
