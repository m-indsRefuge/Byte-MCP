# Q03G Natural Review Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OX initial reviews natural-language authoritative, separate canonical findings recording into an explicit local-only step, and make ordinary initial approval replay-safe without ever creating an implicit provider retry.

**Architecture:** The initial provider attempt persists and returns OX's natural review directly and never parses it as `ox-findings-v1`. Canonical findings remain a separate local evidence artifact written only through `record_findings`. Ordinary `approve=true` becomes idempotent for `TRANSMITTING` and `REVIEWED` by reconstructing a receipt from immutable evidence, while `FAILED` and `OUTCOME_UNKNOWN` continue to require explicit renewed retry approval.

**Tech Stack:** Python 3.12, pytest 9, FastMCP/MCP, HTTPX 0.28.1, append-only JSON evidence, PowerShell/Pester launcher tests.

**Spec:** `docs/superpowers/specs/2026-09-02-ox-q03g-natural-review-idempotency-design.md`

## Global Constraints

- Base implementation checkpoint is `042953a429dd03f08ae749cd0dcc05703ba5db47`.
- No live OX provider request is required for implementation or qualification.
- No live Wolfram provider request is permitted during Q03G implementation or qualification.
- No automatic retry may be introduced.
- `FAILED` and `OUTCOME_UNKNOWN` must still require renewed explicit human retry approval before any resend.
- `OX-000007-A001` remains immutable `OUTCOME_UNKNOWN`.
- `OX-000008-A001` remains exactly-once recovered `OUTCOME_UNKNOWN` with no A002.
- `OX-000009-A001` remains exactly-once `COMPLETED`; its raw response and natural assistant thread remain immutable.
- Q03F's `_TOTAL_DEADLINE_SECONDS = 900.0` remains unchanged.
- Wolfram's six-argument schema remains exactly `input, max_chars, purpose, route_reason, source_finding_id, assumption`.
- Initial natural review success does not require a canonical findings artifact.
- `findings_recorded=false` means no canonical findings decision exists yet.
- `findings_recorded=true` with `findings=[]` means Byte explicitly recorded zero canonical findings.
- Ordinary approval replay in `TRANSMITTING` or `REVIEWED` must perform zero provider requests and allocate no new attempt.
- Historical evidence is read-only during tests; fixture reviews must use temporary evidence roots.

---

## File Structure

Q03G intentionally keeps the existing subsystem boundaries.

- `src/byte_mcp/ox/service.py`
  - Owns initial review orchestration.
  - Stops parsing initial natural responses as findings.
  - Builds initial success/replay receipts.
  - Enforces ordinary-approval replay semantics.
  - Surfaces `findings_recorded`.

- `src/byte_mcp/ox/evidence.py`
  - Adds a read-only canonical-findings artifact existence query.
  - Does not alter event/state meanings.

- `src/byte_mcp/ox/protocol.py`
  - Keeps `parse_findings()` for explicit structured operations.
  - Initial natural-review mandate remains natural Markdown.
  - No Q03G production change should be needed unless tests reveal an undocumented coupling.

- `src/byte_mcp/server.py`
  - Keeps the external tool schema stable.
  - No provider-path behavioral logic belongs here.
  - Only change if response-view tests prove a bounded surface adjustment is required.

- `tests/ox/test_review_service.py`
  - Owns the production-incident RED/green tests for initial natural review and replay after completion.

- `tests/ox/test_evidence.py`
  - Owns canonical findings artifact existence semantics.

- `tests/ox/test_review_followup.py`
  - Owns explicit structured findings recording, including explicit empty findings.

- `tests/ox/test_long_provider_mcp_safety.py`
  - Owns the concurrent `TRANSMITTING` replay safety contract.

- `tests/ox/test_mcp_surface.py`
  - Owns stable MCP schema and returned receipt/view behavior.

- `docs/OX-VALIDATION.md`
  - Documents natural initial reviews, explicit findings recording, and replay-safe ordinary approval.
  - Do not fold deferred Q03F documentation work into this task unless required to avoid contradiction.

---

### Task 1: Lock the Live Q03G Failure Modes as RED Contracts

**Files:**
- Modify: `tests/ox/test_review_service.py`
- Modify: `tests/ox/test_long_provider_mcp_safety.py`

**Interfaces:**
- Consumes:
  - `OXReviewService.prepare_review(...) -> dict[str, object]`
  - `OXReviewService.transmit_review(review_id: str) -> dict[str, object]`
  - existing fake provider client pattern in OX service tests
- Produces:
  - RED contracts that later tasks must make green without weakening assertions

- [ ] **Step 1: Add a representative natural-Markdown provider result fixture**

Add a helper in `tests/ox/test_review_service.py` using the existing fake-client conventions:

```python
def _natural_review_result() -> ProviderResult:
    content = """# OX Review — fixture

## Verdict summary

I found no substantiated defect.

## Observation

The supplied implementation satisfies the stated contract.
"""
    return ProviderResult(
        content=content,
        raw_response={
            "id": "gen-q03g",
            "model": "zai/glm-5.3-flash",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
        usage=None,
    )
```

Use the exact `ProviderResult` constructor shape already established in the test file; if the dataclass requires additional fields, copy those required fields from an existing passing fixture instead of changing production models.

- [ ] **Step 2: Add the initial natural-review RED test**

Add:

```python
def test_initial_natural_review_returns_reviewed_receipt_without_findings_parse(
    tmp_path: Path,
) -> None:
    service, client, evidence = build_review_service(
        tmp_path,
        provider_result=_natural_review_result(),
    )
    proposal = prepare_minimal_review(service)

    result = service.transmit_review(proposal["review_id"])

    assert client.call_count == 1
    assert result["state"] == "REVIEWED"
    assert result["review_text"].startswith("# OX Review")
    assert result["findings_recorded"] is False
    assert result["replayed"] is False
    assert result["provider_request_performed"] is True

    review = evidence.get_review(proposal["review_id"])
    assert review["attempts"] == [
        {
            "attempt_id": f'{proposal["review_id"]}-A001',
            "manifest_sha256": proposal["manifest_sha256"],
            "outcome": "COMPLETED",
        }
    ]
```

Do not assert a canonical findings artifact exists.

- [ ] **Step 3: Run the natural-review test and verify the live failure is reproduced**

Run:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest tests/ox/test_review_service.py::test_initial_natural_review_returns_reviewed_receipt_without_findings_parse -vv
```

Expected RED:

```text
OXFindingValidationError
```

The test must fail because `_perform_attempt()` currently calls `parse_findings()` on Markdown.

- [ ] **Step 4: Add replay-after-completion RED**

Add a second test in `tests/ox/test_review_service.py`:

```python
def test_replayed_initial_approval_after_reviewed_returns_existing_result_without_resend(
    tmp_path: Path,
) -> None:
    service, client, evidence = build_review_service(
        tmp_path,
        provider_result=_natural_review_result(),
    )
    proposal = prepare_minimal_review(service)

    with pytest.raises(OXFindingValidationError):
        service.transmit_review(proposal["review_id"])

    assert client.call_count == 1
    assert evidence.get_review(proposal["review_id"])["state"] == "REVIEWED"

    replayed = service.transmit_review(proposal["review_id"])

    assert client.call_count == 1
    assert replayed["state"] == "REVIEWED"
    assert replayed["attempt_id"] == f'{proposal["review_id"]}-A001'
    assert replayed["replayed"] is True
    assert replayed["provider_request_performed"] is False
```

This intentionally models the pre-Q03G completed-but-exceptional path seen with `OX-000009`.

- [ ] **Step 5: Run replay-after-completion and verify the state-error RED**

Run:

```powershell
python -m pytest tests/ox/test_review_service.py::test_replayed_initial_approval_after_reviewed_returns_existing_result_without_resend -vv
```

Expected RED:

```text
OXApprovalError: review state does not permit this operation
```

- [ ] **Step 6: Add a concurrent TRANSMITTING replay RED**

In `tests/ox/test_long_provider_mcp_safety.py`, use a blocking fake client:

```python
class BlockingClient:
    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def complete(self, messages, *, json_mode, attempt_id):
        self.call_count += 1
        self.started.set()
        assert self.release.wait(timeout=5)
        return self.result
```

Test:

```python
def test_initial_approval_replay_while_transmitting_never_resends(tmp_path: Path) -> None:
    client = BlockingClient(_natural_review_result())
    service, evidence = build_service_with_client(tmp_path, client)
    proposal = prepare_minimal_review(service)

    first_result: dict[str, object] = {}
    first_error: list[BaseException] = []

    def run_first() -> None:
        try:
            first_result.update(service.transmit_review(proposal["review_id"]))
        except BaseException as exc:
            first_error.append(exc)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert client.started.wait(timeout=5)

    replayed = service.transmit_review(proposal["review_id"])

    assert replayed["state"] == "TRANSMITTING"
    assert replayed["attempt_id"] == f'{proposal["review_id"]}-A001'
    assert replayed["replayed"] is True
    assert replayed["provider_request_performed"] is False
    assert client.call_count == 1

    client.release.set()
    worker.join(timeout=5)

    assert client.call_count == 1
    assert len(evidence.get_review(proposal["review_id"])["attempts"]) == 1
```

- [ ] **Step 7: Run concurrent replay RED**

Run:

```powershell
python -m pytest tests/ox/test_long_provider_mcp_safety.py::test_initial_approval_replay_while_transmitting_never_resends -vv
```

Expected RED: `OXApprovalError` from the second ordinary approval, or equivalent current-state rejection. It must not fail because the fake client was called twice.

- [ ] **Step 8: Verify Task 1 changes are tests only**

Run:

```powershell
git status --short
git diff --check
```

Expected dirty paths:

```text
 M tests/ox/test_review_service.py
 M tests/ox/test_long_provider_mcp_safety.py
```

- [ ] **Step 9: Commit RED contracts**

```powershell
git add tests/ox/test_review_service.py tests/ox/test_long_provider_mcp_safety.py
git commit -m "test: lock Q03G natural review replay contracts"
```

---

### Task 2: Add Explicit Canonical-Findings Recording State

**Files:**
- Modify: `src/byte_mcp/ox/evidence.py`
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_evidence.py`
- Modify: `tests/ox/test_review_followup.py`

**Interfaces:**
- Consumes:
  - existing canonical findings path used by `persist_findings`
  - `EvidenceStore.read_findings(review_id: str) -> dict[str, object]`
- Produces:
  - `EvidenceStore.findings_recorded(review_id: str) -> bool`
  - findings service responses containing `recorded: bool`
  - review summary containing `findings_recorded: bool`

- [ ] **Step 1: Locate and pin the existing findings artifact path**

In `src/byte_mcp/ox/evidence.py`, find `persist_findings()` and `read_findings()`. Do not invent a second findings artifact. Record the existing canonical path in the test by using `persist_findings()` rather than writing files directly.

- [ ] **Step 2: Write EvidenceStore RED for unrecorded vs explicit empty**

In `tests/ox/test_evidence.py`:

```python
def test_findings_recorded_distinguishes_missing_from_explicit_empty(tmp_path: Path) -> None:
    store = build_evidence_store(tmp_path)
    review_id = seed_prepared_review(store)

    assert store.findings_recorded(review_id) is False

    store.persist_findings(
        review_id,
        {
            "protocol_version": "ox-findings-v1",
            "findings": [],
        },
    )

    assert store.findings_recorded(review_id) is True
    assert store.read_findings(review_id) == {
        "protocol_version": "ox-findings-v1",
        "findings": [],
    }
```

Use the existing fixture helper names from the test file where available.

- [ ] **Step 3: Run EvidenceStore RED**

```powershell
python -m pytest tests/ox/test_evidence.py::test_findings_recorded_distinguishes_missing_from_explicit_empty -vv
```

Expected RED:

```text
AttributeError: 'EvidenceStore' object has no attribute 'findings_recorded'
```

- [ ] **Step 4: Implement the minimal read-only existence method**

In `src/byte_mcp/ox/evidence.py`, next to `read_findings()`:

```python
def findings_recorded(self, review_id: str) -> bool:
    path = self._review_dir(review_id) / "findings" / "findings.json"
    return path.is_file()
```

Use the exact private path helper and filename already used by `persist_findings()`. If the existing canonical filename differs, mirror it exactly. Do not create directories or files in this method.

- [ ] **Step 5: Run the EvidenceStore test GREEN**

```powershell
python -m pytest tests/ox/test_evidence.py::test_findings_recorded_distinguishes_missing_from_explicit_empty -vv
```

Expected: PASS.

- [ ] **Step 6: Add service findings-view RED**

In `tests/ox/test_review_followup.py`:

```python
def test_findings_view_reports_recording_state(tmp_path: Path) -> None:
    service = build_review_service(tmp_path)
    review_id = seed_reviewed_natural_review(service)

    before = service.get_review(review_id, view="findings")
    assert before == {
        "review_id": review_id,
        "recorded": False,
        "protocol_version": "ox-findings-v1",
        "findings": [],
    }

    service.record_findings(review_id, [])

    after = service.get_review(review_id, view="findings")
    assert after == {
        "review_id": review_id,
        "recorded": True,
        "protocol_version": "ox-findings-v1",
        "findings": [],
    }
```

Use the current `record_findings` signature exactly. If it accepts a sequence of mappings rather than positional `[]`, retain the existing API shape.

- [ ] **Step 7: Run the service-view RED**

```powershell
python -m pytest tests/ox/test_review_followup.py::test_findings_view_reports_recording_state -vv
```

Expected RED: missing `recorded` field and/or explicit empty recording currently rejected.

- [ ] **Step 8: Surface recording state in `get_review`**

Modify `OXReviewService.get_review()`:

```python
if view == "summary":
    review = self._evidence.get_review(review_id)
    result = {
        **review,
        "findings_recorded": self._evidence.findings_recorded(review_id),
        "revalidations": [
            self._effective_revalidation(item)
            for item in self._evidence.list_revalidations(review_id)
        ],
    }
elif view == "findings":
    result = {
        "review_id": review_id,
        "recorded": self._evidence.findings_recorded(review_id),
        **self._evidence.read_findings(review_id),
    }
```

Do not alter canonical `ox-findings-v1`.

- [ ] **Step 9: Make explicit empty findings recordable only if current code rejects it**

If `record_findings(review_id, [])` currently rejects empty input, change only the validation that conflates an empty sequence with missing/invalid input. Preserve validation for malformed finding objects.

Desired shape:

```python
if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
    raise OXProtocolError(attempt_outcome="NOT_SENT")
```

Do not require `len(findings) > 0`.

- [ ] **Step 10: Run Task 2 focused GREEN**

```powershell
python -m pytest tests/ox/test_evidence.py tests/ox/test_review_followup.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit Task 2**

```powershell
git add src/byte_mcp/ox/evidence.py src/byte_mcp/ox/service.py tests/ox/test_evidence.py tests/ox/test_review_followup.py
git commit -m "feat: expose explicit OX findings recording state"
```

---

### Task 3: Make Initial Natural Review Completion Authoritative

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_review_service.py`
- Test: `tests/ox/test_protocol.py`

**Interfaces:**
- Consumes:
  - `ProviderResult.content: str`
  - `ProviderResult.raw_response: dict[str, object]`
  - `EvidenceStore.persist_provider_response(...)`
  - `EvidenceStore.append_thread_message(...)`
  - `EvidenceStore.record_attempt_outcome(...)`
  - `EvidenceStore.findings_recorded(...)`
- Produces:
  - initial success receipt:
    `review_id`, `attempt_id`, `state`, `manifest_sha256`, `review_text`,
    `findings_recorded`, `usage`, `replayed`, `provider_request_performed`

- [ ] **Step 1: Confirm the Task 1 natural-review test is still RED before production change**

```powershell
python -m pytest tests/ox/test_review_service.py::test_initial_natural_review_returns_reviewed_receipt_without_findings_parse -vv
```

Expected: `OXFindingValidationError`.

- [ ] **Step 2: Change the initial provider request to natural mode**

In `OXReviewService._perform_attempt()`:

```python
result = self._client.complete(
    messages,
    json_mode=False,
    attempt_id=attempt_id,
)
```

Do not change continuation or revalidation JSON/text modes in this step.

- [ ] **Step 3: Remove initial `parse_findings()` and invalid-findings persistence**

Replace the initial parser block with direct completion:

```python
self._evidence.persist_provider_response(review_id, attempt_id, result.raw_response)
self._evidence.append_thread_message(
    review_id,
    "initial",
    {"role": "assistant", "content": result.content},
)
self._evidence.record_attempt_outcome(
    review_id,
    attempt_id,
    AttemptOutcome.COMPLETED,
)
self._audit_attempt(
    review_id,
    attempt_id,
    manifest_sha256,
    AttemptOutcome.COMPLETED.value,
)
return {
    "review_id": review_id,
    "attempt_id": attempt_id,
    "state": ReviewState.REVIEWED.value,
    "manifest_sha256": manifest_sha256,
    "review_text": result.content,
    "findings_recorded": self._evidence.findings_recorded(review_id),
    "usage": asdict(result.usage) if result.usage is not None else None,
    "replayed": False,
    "provider_request_performed": True,
}
```

Delete no generic findings parser. `_persist_invalid_findings()` remains if another path still uses it; remove it only if repository-wide references prove it is now dead code.

- [ ] **Step 4: Run natural-review test GREEN**

```powershell
python -m pytest tests/ox/test_review_service.py::test_initial_natural_review_returns_reviewed_receipt_without_findings_parse -vv
```

Expected: PASS.

- [ ] **Step 5: Add a regression proving `parse_findings` remains strict for explicit structured use**

In `tests/ox/test_protocol.py`, retain/add:

```python
def test_parse_findings_rejects_natural_markdown() -> None:
    with pytest.raises(OXFindingValidationError):
        parse_findings("# OX Review\n\nNo substantiated defect.", "OX-000001")
```

This is intentional: Q03G removes the parser from the initial natural path; it does not weaken canonical findings validation.

- [ ] **Step 6: Run protocol + review service focused suite**

```powershell
python -m pytest tests/ox/test_protocol.py tests/ox/test_review_service.py -q
```

Expected: replay tests may still be RED; natural-review completion must now pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add src/byte_mcp/ox/service.py tests/ox/test_review_service.py tests/ox/test_protocol.py
git commit -m "feat: return natural OX initial reviews directly"
```

---

### Task 4: Make Ordinary Initial Approval Replay-Safe and Race-Safe

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_review_service.py`
- Modify: `tests/ox/test_long_provider_mcp_safety.py`
- Test: `tests/ox/test_orphaned_transmission_recovery.py`

**Interfaces:**
- Produces:
  - `_initial_review_receipt(review_id: str, review: Mapping[str, object], *, replayed: bool) -> dict[str, object]`
  - ordinary `transmit_review(review_id)` behavior:
    - `PREPARED`: provider-capable first attempt
    - `TRANSMITTING`: local replay receipt
    - `REVIEWED`: local replay receipt
    - `FAILED`/`OUTCOME_UNKNOWN`: `OXApprovalError`, zero provider calls

- [ ] **Step 1: Add a private helper to reconstruct an initial review receipt**

In `src/byte_mcp/ox/service.py`:

```python
def _initial_review_receipt(
    self,
    review_id: str,
    review: Mapping[str, object],
    *,
    replayed: bool,
) -> dict[str, object]:
    attempts = review.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise OXEvidenceError("initial review attempt evidence is unavailable")

    latest = attempts[-1]
    attempt_id = latest.get("attempt_id")
    manifest_sha256 = latest.get("manifest_sha256")
    if not isinstance(attempt_id, str) or not isinstance(manifest_sha256, str):
        raise OXEvidenceError("initial review attempt evidence is invalid")

    state = review.get("state")
    review_text: str | None = None
    if state == ReviewState.REVIEWED.value:
        messages = self._evidence.read_thread(review_id, "initial")
        assistants = [
            message
            for message in messages
            if message.get("role") == "assistant"
            and isinstance(message.get("content"), str)
        ]
        if not assistants:
            raise OXEvidenceError("completed initial review text is unavailable")
        review_text = str(assistants[-1]["content"])

    return {
        "review_id": review_id,
        "attempt_id": attempt_id,
        "state": state,
        "manifest_sha256": manifest_sha256,
        "review_text": review_text,
        "findings_recorded": self._evidence.findings_recorded(review_id),
        "usage": None,
        "replayed": replayed,
        "provider_request_performed": False,
    }
```

Do not reconstruct usage unless an existing bounded evidence API already provides it cleanly. YAGNI: `usage=None` on replay is permitted by the approved spec.

- [ ] **Step 2: Replace initial state-strict load with explicit ordinary-approval routing**

At the start of `transmit_review()`:

```python
try:
    current = self._evidence.get_review(review_id)
except OXEvidenceError as exc:
    raise OXApprovalError("review evidence is unavailable") from exc

state = current.get("state")
if state in {ReviewState.TRANSMITTING.value, ReviewState.REVIEWED.value}:
    return self._initial_review_receipt(review_id, current, replayed=True)

if state in {ReviewState.FAILED.value, ReviewState.OUTCOME_UNKNOWN.value}:
    raise OXApprovalError("review requires renewed explicit retry approval")

if state != ReviewState.PREPARED.value:
    raise OXApprovalError("review state does not permit this operation")
```

Then rebuild/verify from the already-loaded PREPARED review rather than calling `_load_prepared_review()` again.

- [ ] **Step 3: Make the claim race idempotent**

Wrap `claim_initial_transmission()`:

```python
try:
    attempt = self._evidence.claim_initial_transmission(
        review_id,
        prepared.manifest.manifest_sha256,
    )
except OXEvidenceError as exc:
    current = self._evidence.get_review(review_id)
    if current.get("state") in {
        ReviewState.TRANSMITTING.value,
        ReviewState.REVIEWED.value,
    }:
        return self._initial_review_receipt(review_id, current, replayed=True)
    raise OXApprovalError("review is not available for initial approval") from exc
```

This is the concurrency-critical branch. It must never call the provider.

- [ ] **Step 4: Run replay-after-REVIEWED GREEN**

```powershell
python -m pytest tests/ox/test_review_service.py::test_replayed_initial_approval_after_reviewed_returns_existing_result_without_resend -vv
```

Expected: PASS, provider call count exactly 1.

- [ ] **Step 5: Run concurrent TRANSMITTING replay GREEN**

```powershell
python -m pytest tests/ox/test_long_provider_mcp_safety.py::test_initial_approval_replay_while_transmitting_never_resends -vv
```

Expected: PASS, provider call count exactly 1, one A001, no A002.

- [ ] **Step 6: Add ordinary-approval retry-boundary regressions**

In `tests/ox/test_review_service.py` or `test_orphaned_transmission_recovery.py`:

```python
@pytest.mark.parametrize("terminal_state", ["FAILED", "OUTCOME_UNKNOWN"])
def test_ordinary_approval_never_resends_terminal_retryable_review(
    tmp_path: Path,
    terminal_state: str,
) -> None:
    service, client, evidence = seed_terminal_review(tmp_path, terminal_state)

    with pytest.raises(
        OXApprovalError,
        match="renewed explicit retry approval",
    ):
        service.transmit_review("OX-000001")

    assert client.call_count == 0
    assert len(evidence.get_review("OX-000001")["attempts"]) == 1
```

Use existing recovery helpers rather than manually editing event JSON.

- [ ] **Step 7: Run retry-boundary and Q03E orphan recovery suite**

```powershell
python -m pytest tests/ox/test_orphaned_transmission_recovery.py tests/ox/test_review_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Run all async-provider safety tests**

```powershell
python -m pytest `
  tests/ox/test_long_provider_mcp_safety.py `
  tests/ox/test_continue_provider_mcp_safety.py `
  tests/ox/test_revalidate_provider_mcp_safety.py `
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```powershell
git add src/byte_mcp/ox/service.py tests/ox/test_review_service.py tests/ox/test_long_provider_mcp_safety.py tests/ox/test_orphaned_transmission_recovery.py
git commit -m "fix: make OX initial approval replay safe"
```

---

### Task 5: Lock MCP Surface, Documentation, and Full Q03G Qualification

**Files:**
- Modify: `tests/ox/test_mcp_surface.py`
- Modify: `docs/OX-VALIDATION.md`
- Modify only if required by failing surface tests: `src/byte_mcp/server.py`
- Verify: all OX source/test files

**Interfaces:**
- Consumes the final Task 2–4 service contract.
- Produces a fully qualified Q03G checkpoint ready for transactional promotion.

- [ ] **Step 1: Add MCP receipt-shape regression**

In `tests/ox/test_mcp_surface.py`, mock `_ox_service()` with an async-safe fake whose `transmit_review()` returns:

```python
{
    "review_id": "OX-000001",
    "attempt_id": "OX-000001-A001",
    "state": "REVIEWED",
    "manifest_sha256": "a" * 64,
    "review_text": "# OX Review\n\nNo substantiated defect.",
    "findings_recorded": False,
    "usage": None,
    "replayed": False,
    "provider_request_performed": True,
}
```

Assert:

```python
result = await server.ox_review(review_id="OX-000001", approve=True)

assert result["state"] == "REVIEWED"
assert result["review_text"].startswith("# OX Review")
assert result["findings_recorded"] is False
assert result["provider_request_performed"] is True
```

Also retain the existing assertion that provider-capable `ox_review` uses `asyncio.to_thread`.

- [ ] **Step 2: Add findings-view MCP regression**

Mock `get_review(..., view="findings")` to return:

```python
{
    "review_id": "OX-000001",
    "recorded": False,
    "protocol_version": "ox-findings-v1",
    "findings": [],
}
```

Assert `ox_get_review` preserves `recorded=False`.

No tool argument names change.

- [ ] **Step 3: Run MCP surface tests**

```powershell
python -m pytest tests/ox/test_mcp_surface.py -q
```

Expected: PASS without changing `server.py`. If a production server change is required, keep it to response forwarding only; do not move service-state logic into the MCP layer.

- [ ] **Step 4: Update OX validation documentation**

In `docs/OX-VALIDATION.md`, document these exact rules:

```markdown
### Initial review response

The provider's initial review is authoritative natural text/Markdown.
Byte-MCP persists the raw provider response and assistant thread before
recording the attempt COMPLETED. Initial review success does not require
an `ox-findings-v1` artifact.

### Canonical findings

Canonical findings are recorded explicitly and locally through
`ox_continue(mode="record_findings")`. `recorded=false` means no canonical
findings decision has been written. `recorded=true` with `findings=[]`
means an explicit zero-finding decision.

### Ordinary approval replay

Repeated ordinary approval for a TRANSMITTING or REVIEWED initial review
is idempotent and performs zero provider requests. FAILED and
OUTCOME_UNKNOWN still require explicit renewed retry approval.
```

Do not change the deferred Q03F read-timeout documentation in this task unless existing prose becomes directly false because of Q03G.

- [ ] **Step 5: Run focused Q03G suite**

```powershell
python -m pytest `
  tests/ox/test_review_service.py `
  tests/ox/test_evidence.py `
  tests/ox/test_review_followup.py `
  tests/ox/test_long_provider_mcp_safety.py `
  tests/ox/test_mcp_surface.py `
  -q
```

Expected: PASS.

- [ ] **Step 6: Run Q03A–Q03F safety/regression suite**

```powershell
python -m pytest `
  tests/ox/test_client.py `
  tests/ox/test_client_timeout.py `
  tests/ox/test_provider_total_deadline.py `
  tests/ox/test_continue_provider_mcp_safety.py `
  tests/ox/test_revalidate_provider_mcp_safety.py `
  tests/ox/test_orphaned_transmission_recovery.py `
  tests/ox/test_protocol.py `
  tests/ox/test_review_followup.py `
  -q
```

Expected: PASS.

- [ ] **Step 7: Run all OX tests**

```powershell
python -m pytest tests/ox -q
```

Expected: PASS.

- [ ] **Step 8: Run full Byte-MCP Python regression**

```powershell
python -m pytest tests -q
```

Expected: PASS. Existing known non-failing Pydantic warnings may remain unchanged.

- [ ] **Step 9: Run Ruff**

```powershell
python -m ruff check src tests scripts
```

Expected:

```text
All checks passed!
```

- [ ] **Step 10: Run compile gate**

```powershell
python -m compileall -q src
```

Expected exit code: `0`.

- [ ] **Step 11: Run launcher Pester regression**

```powershell
Invoke-Pester -Path 'tests/launcher' -PassThru -Output Detailed
```

Expected: all launcher tests pass; deployed Q03F baseline was 69/69.

- [ ] **Step 12: Verify Wolfram schema source contract remains unchanged**

Run a provider-free source/schema test or existing MCP-surface assertion that proves exact `wolfram_query` arguments:

```text
input
max_chars
purpose
route_reason
source_finding_id
assumption
```

No Wolfram provider call.

- [ ] **Step 13: Add a provider-free historical-evidence acceptance script/test**

The local acceptance harness must fingerprint, without mutation:

```text
OX-000007:
  A001 = OUTCOME_UNKNOWN
  no retry

OX-000008:
  A001 = OUTCOME_UNKNOWN
  no A002

OX-000009:
  A001 = COMPLETED
  no A002
  raw provider response unchanged
  initial thread unchanged
```

Use hashes captured during the incident for promotion acceptance; do not copy historical evidence into unit-test fixtures.

- [ ] **Step 14: Run `git diff --check` and scope review**

```powershell
git diff --check
git status --short
git diff --stat 042953a429dd03f08ae749cd0dcc05703ba5db47..HEAD
```

Expected Q03G production scope is limited to OX service/evidence behavior, tests, and OX documentation. No Wolfram source should change.

- [ ] **Step 15: Commit Task 5**

```powershell
git add tests/ox/test_mcp_surface.py docs/OX-VALIDATION.md
git add src/byte_mcp/server.py  # only if Step 3 proved a bounded forwarding change necessary
git commit -m "docs: lock Q03G natural review contract"
```

- [ ] **Step 16: Final clean-checkpoint verification**

```powershell
git status --porcelain
git log -6 --oneline --decorate
```

Expected: clean Q03G worktree with all five task checkpoints visible.

---

## Plan Self-Review

### Spec coverage

- Natural-language initial review authority: Task 3.
- No initial `parse_findings()`: Task 3.
- Explicit local canonical findings: Task 2.
- Unrecorded vs explicit-zero findings: Task 2.
- PREPARED first send: existing path preserved by Tasks 3–4.
- TRANSMITTING replay receipt: Task 4.
- REVIEWED replay receipt: Task 4.
- FAILED/OUTCOME_UNKNOWN renewed retry boundary: Task 4.
- Race-safe concurrent approval: Task 4.
- No automatic retry: global constraint + Task 4 tests.
- Existing Q03E recovery: Task 4 regression.
- Existing Q03F deadline: Task 5 regression.
- Stable MCP/Wolfram surface: Task 5.
- Historical OX-000007/8/9 preservation: Task 5.
- Provider-free local qualification: all tasks.
- Future live canary requires fresh human authorization: global constraint; deployment occurs only after this plan completes.

### Placeholder scan

The plan contains no unresolved implementation placeholders.

### Type consistency

The plan consistently uses:

```python
EvidenceStore.findings_recorded(review_id: str) -> bool
OXReviewService.transmit_review(review_id: str) -> dict[str, object]
OXReviewService._initial_review_receipt(
    review_id: str,
    review: Mapping[str, object],
    *,
    replayed: bool,
) -> dict[str, object]
```

Receipt field names are consistent across Tasks 1, 3, 4, and 5:

```text
review_id
attempt_id
state
manifest_sha256
review_text
findings_recorded
usage
replayed
provider_request_performed
```
