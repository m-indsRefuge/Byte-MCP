# OX Provider Execution Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one approved OX review attempt execute exactly once, persist a deterministic terminal outcome, and return safe structured status on duplicate Web UI approval without weakening OX's existing approval, manifest, evidence, or retry controls.

**Architecture:** Keep the existing OX review state machine and durable transmission-intent claim, but insert an OX-local execution boundary between lifecycle orchestration and `OXClient.complete()`. Provider exceptions become a small `ProviderAttemptResult` value instead of escaping across the service boundary; the service then performs one durable terminal transition and returns that result. Duplicate initial approval becomes read-only observation of the already-claimed initial attempt, while explicit retry remains a separate approved operation.

**Tech Stack:** Python 3.12, dataclasses/StrEnum, FastMCP, httpx, pytest, Ruff, GitHub Actions, Windows PowerShell/Pester launch verification.

**Spec:** `docs/superpowers/specs/2026-08-30-ox-provider-execution-reliability-design.md`

## Global Constraints

- Baseline implementation starts from accepted combined head `012ea48fbc4924a5aa90cc102c32a5f41c5418ab`; the approved spec commit is `75362294966f3ebcd4ab290af9e0d9d020e4de98`.
- Do not modify any Wolfram production implementation or qualification behavior.
- Keep OX two-phase human approval, immutable manifest/payload binding, exact review identity, and append-only evidence semantics.
- Exactly one provider request per authorized attempt; no automatic retry.
- Attempt outcomes remain exactly `NOT_SENT`, `REJECTED`, `COMPLETED`, `OUTCOME_UNKNOWN`.
- Duplicate `approve=true, retry=false` must never allocate a new attempt or call the provider again.
- `retry=true` remains the only path that can allocate a later initial-review attempt after renewed approval.
- `safe_error_type` may contain only a bounded exception class name; never exception text, credentials, headers, request bodies, response bodies, or absolute paths.
- `OX-000005` remains historical `OUTCOME_UNKNOWN` evidence and must not be mutated or reused for live acceptance.
- No live OX provider call is used during implementation or debugging; mocks and CI first.

---

## File Structure

- Create `src/byte_mcp/ox/execution.py` — pure OX-local one-call execution adapter that converts the existing provider exception taxonomy into `ProviderAttemptResult`.
- Modify `src/byte_mcp/ox/models.py` — add the immutable `ProviderAttemptResult` contract.
- Modify `src/byte_mcp/ox/evidence.py` — persist/reconstruct optional safe error metadata on terminal attempt events and expose a read-only helper for the existing initial attempt.
- Modify `src/byte_mcp/ox/service.py` — centralize terminal attempt persistence/audit and add duplicate-initial-approval observation; retain retry, continuation, and revalidation state rules.
- Modify `src/byte_mcp/ox/natural_service.py` — route initial natural OX review through the new execution result and preserve response-before-thread-before-completion ordering.
- Modify `src/byte_mcp/server.py` only if needed to keep `ox_review`'s public MCP argument contract unchanged while allowing structured replay/status results to pass through.
- Create `tests/ox/test_execution.py` — focused execution-kernel mapping and exactly-one-call tests.
- Modify `tests/ox/test_review_service.py` — lifecycle, retry, sequential/concurrent duplicate approval, evidence, and safe-error tests.
- Modify `tests/ox/test_natural_review_architecture.py` — natural-response success ordering and structured error/replay expectations.
- Modify/add server contract tests under `tests/` only where needed to prove the MCP surface remains unchanged.

---

### Task 1: Define the OX-local execution result contract

**Files:**
- Modify: `src/byte_mcp/ox/models.py`
- Create: `src/byte_mcp/ox/execution.py`
- Create: `tests/ox/test_execution.py`

**Interfaces:**
- Consumes: existing `AttemptOutcome`, `ProviderResult`, `_PROVIDER_ERRORS`, and an object exposing `complete(messages, json_mode, attempt_id)`.
- Produces: `ProviderAttemptResult` and `execute_provider_attempt(...)` for service/natural-service orchestration.

- [ ] **Step 1: Write failing model/execution tests**

```python
from byte_mcp.errors import OXRateLimitError, OXTransportError
from byte_mcp.ox.execution import execute_provider_attempt
from byte_mcp.ox.models import AttemptOutcome, ProviderAttemptResult, ProviderResult


class SuccessClient:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str):
        self.calls += 1
        return ProviderResult(
            content="review",
            raw_response={"choices": [{"message": {"role": "assistant", "content": "review"}}]},
        )


class ErrorClient:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def complete(self, messages, *, json_mode: bool, attempt_id: str):
        self.calls += 1
        raise self.error


def test_execute_provider_attempt_returns_completed_without_retry():
    client = SuccessClient()
    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )
    assert client.calls == 1
    assert result == ProviderAttemptResult(
        outcome=AttemptOutcome.COMPLETED,
        provider_result=result.provider_result,
        safe_error_type=None,
    )
    assert isinstance(result.provider_result, ProviderResult)


def test_execute_provider_attempt_maps_unknown_transport_without_retry():
    client = ErrorClient(OXTransportError(attempt_outcome="OUTCOME_UNKNOWN"))
    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )
    assert client.calls == 1
    assert result.outcome is AttemptOutcome.OUTCOME_UNKNOWN
    assert result.provider_result is None
    assert result.safe_error_type == "OXTransportError"


def test_execute_provider_attempt_maps_rejected_provider_error():
    client = ErrorClient(OXRateLimitError(attempt_outcome="REJECTED"))
    result = execute_provider_attempt(
        client,
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )
    assert client.calls == 1
    assert result.outcome is AttemptOutcome.REJECTED
    assert result.safe_error_type == "OXRateLimitError"
```

- [ ] **Step 2: Run the focused tests and record RED**

Run:

```bash
python -m pytest tests/ox/test_execution.py -q
```

Expected: collection/import failure because `ProviderAttemptResult` and `byte_mcp.ox.execution` do not exist.

- [ ] **Step 3: Add the immutable result model**

Add to `src/byte_mcp/ox/models.py`:

```python
@dataclass(frozen=True, slots=True)
class ProviderAttemptResult:
    outcome: AttemptOutcome
    provider_result: ProviderResult | None = None
    safe_error_type: str | None = None
```

- [ ] **Step 4: Implement the one-call execution adapter**

Create `src/byte_mcp/ox/execution.py`:

```python
from collections.abc import Mapping, Sequence

from .models import AttemptOutcome, ProviderAttemptResult
from .service import _PROVIDER_ERRORS


def execute_provider_attempt(
    client,
    messages: Sequence[Mapping[str, object]],
    *,
    json_mode: bool,
    attempt_id: str,
) -> ProviderAttemptResult:
    try:
        provider_result = client.complete(
            messages,
            json_mode=json_mode,
            attempt_id=attempt_id,
        )
    except _PROVIDER_ERRORS as exc:
        return ProviderAttemptResult(
            outcome=AttemptOutcome(exc.attempt_outcome),
            safe_error_type=type(exc).__name__,
        )
    return ProviderAttemptResult(
        outcome=AttemptOutcome.COMPLETED,
        provider_result=provider_result,
    )
```

If importing `_PROVIDER_ERRORS` from `service.py` creates a cycle, move the exception tuple into `execution.py` and import it from there in the service modules. Do not duplicate the tuple in two production locations.

- [ ] **Step 5: Run focused tests and Ruff**

```bash
python -m pytest tests/ox/test_execution.py -q
python -m ruff check src/byte_mcp/ox/models.py src/byte_mcp/ox/execution.py tests/ox/test_execution.py
```

Expected: all focused tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit the execution contract**

```bash
git add src/byte_mcp/ox/models.py src/byte_mcp/ox/execution.py tests/ox/test_execution.py
git commit -m "refactor: add OX provider execution result"
```

---

### Task 2: Persist safe terminal attempt diagnostics

**Files:**
- Modify: `src/byte_mcp/ox/evidence.py`
- Modify: `tests/ox/test_review_service.py`

**Interfaces:**
- Consumes: `AttemptOutcome`, current append-only `ATTEMPT_OUTCOME` events.
- Produces: `record_attempt_outcome(..., safe_error_type: str | None = None)` and reconstructed attempt dictionaries containing optional `safe_error_type`.

- [ ] **Step 1: Write failing evidence tests**

Add tests equivalent to:

```python
def test_terminal_attempt_event_round_trips_safe_error_type(tmp_path):
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    service.transmit_review(proposal["review_id"])

    attempt = store.get_review(proposal["review_id"])["attempts"][-1]
    assert attempt["outcome"] == "OUTCOME_UNKNOWN"
    assert attempt["safe_error_type"] == "OXTransportError"


def test_attempt_event_rejects_unbounded_safe_error_type(tmp_path):
    store = EvidenceStore(tmp_path / "evidence")
    # Prepare a normal review fixture and claim A001 using existing helpers.
    # Then verify unsafe diagnostic text is rejected rather than persisted.
    with pytest.raises(OXEvidenceError):
        store.record_attempt_outcome(
            "OX-000001",
            "OX-000001-A001",
            AttemptOutcome.REJECTED,
            safe_error_type="OXRateLimitError: bearer secret",
        )
```

Use the existing fixture helpers rather than hand-writing malformed evidence directories.

- [ ] **Step 2: Run the focused evidence tests and record RED**

```bash
python -m pytest tests/ox/test_review_service.py -k "safe_error_type or unknown_attempt" -q
```

Expected: failure because `record_attempt_outcome` does not accept/persist safe error metadata.

- [ ] **Step 3: Extend the evidence API with bounded safe error metadata**

Change the signature to:

```python
def record_attempt_outcome(
    self,
    review_id: str,
    attempt_id: str,
    outcome: AttemptOutcome | str,
    *,
    safe_error_type: str | None = None,
) -> None:
```

Validate diagnostic values with a strict symbol pattern:

```python
if safe_error_type is not None and re.fullmatch(r"OX[A-Za-z0-9]+Error", safe_error_type) is None:
    raise OXEvidenceError("safe error type is invalid")
```

Append it only when present:

```python
event = {
    "attempt_id": attempt_id,
    "event_type": "ATTEMPT_OUTCOME",
    "outcome": outcome_value,
}
if safe_error_type is not None:
    event["safe_error_type"] = safe_error_type
self._append_event(review_id, event)
```

- [ ] **Step 4: Reconstruct the optional diagnostic metadata**

In `_reconstruct`, when processing `ATTEMPT_OUTCOME`, validate and copy `safe_error_type` into the matching attempt dictionary. Reject malformed values as malformed review evidence.

- [ ] **Step 5: Run focused and evidence regression tests**

```bash
python -m pytest tests/ox/test_review_service.py -q
python -m ruff check src/byte_mcp/ox/evidence.py tests/ox/test_review_service.py
```

Expected: all OX review-service tests pass.

- [ ] **Step 6: Commit durable diagnostics**

```bash
git add src/byte_mcp/ox/evidence.py tests/ox/test_review_service.py
git commit -m "feat: persist safe OX attempt diagnostics"
```

---

### Task 3: Make initial provider failures structured terminal results

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/ox/natural_service.py`
- Modify: `tests/ox/test_review_service.py`
- Modify: `tests/ox/test_natural_review_architecture.py`

**Interfaces:**
- Consumes: `execute_provider_attempt(...) -> ProviderAttemptResult` and extended evidence terminal-outcome persistence.
- Produces: initial `transmit_review` returns a dictionary for known provider outcomes instead of re-raising known provider exceptions after the attempt has been claimed.

- [ ] **Step 1: Write failing structured-outcome tests**

For the base service and natural service, add explicit assertions such as:

```python
def test_unknown_initial_attempt_returns_structured_terminal_result(tmp_path):
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    result = service.transmit_review(proposal["review_id"])

    assert result == {
        "review_id": proposal["review_id"],
        "attempt_id": f"{proposal['review_id']}-A001",
        "state": "OUTCOME_UNKNOWN",
        "manifest_sha256": proposal["manifest_sha256"],
        "attempt_outcome": "OUTCOME_UNKNOWN",
        "safe_error_type": "OXTransportError",
        "response_available": False,
        "replayed": False,
    }
    assert client.calls == 1
    assert store.get_review(proposal["review_id"])["state"] == "OUTCOME_UNKNOWN"
```

Add equivalent `REJECTED` and `NOT_SENT` cases using provider-error clients with those `attempt_outcome` values.

- [ ] **Step 2: Run focused tests and record RED**

```bash
python -m pytest tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py -k "structured_terminal or unknown_initial or rejected_initial or not_sent_initial" -q
```

Expected: failures because provider exceptions are currently re-raised.

- [ ] **Step 3: Add one service helper for terminal result persistence**

In `service.py`, introduce a helper with a single responsibility:

```python
def _terminal_attempt_result(
    self,
    *,
    review_id: str,
    attempt_id: str,
    manifest_sha256: str,
    outcome: AttemptOutcome,
    safe_error_type: str | None,
    response_available: bool,
    replayed: bool,
) -> dict[str, object]:
    if not replayed:
        self._evidence.record_attempt_outcome(
            review_id,
            attempt_id,
            outcome,
            safe_error_type=safe_error_type,
        )
        self._audit_attempt(
            review_id,
            attempt_id,
            manifest_sha256,
            outcome.value,
            safe_error_type=safe_error_type,
        )
    state = self._evidence.get_review(review_id)["state"]
    result = {
        "review_id": review_id,
        "attempt_id": attempt_id,
        "state": state,
        "manifest_sha256": manifest_sha256,
        "attempt_outcome": outcome.value,
        "safe_error_type": safe_error_type,
        "response_available": response_available,
        "replayed": replayed,
    }
    return result
```

Extend `_audit_attempt` with optional `safe_error_type` and include only the bounded symbol when supplied.

- [ ] **Step 4: Route initial base-service execution through the kernel**

Replace the provider-exception re-raise path in `_perform_attempt` with:

```python
execution = execute_provider_attempt(
    self._client,
    messages,
    json_mode=True,
    attempt_id=attempt_id,
)
if execution.outcome is not AttemptOutcome.COMPLETED:
    return self._terminal_attempt_result(
        review_id=review_id,
        attempt_id=attempt_id,
        manifest_sha256=manifest_sha256,
        outcome=execution.outcome,
        safe_error_type=execution.safe_error_type,
        response_available=False,
        replayed=False,
    )
result = execution.provider_result
```

Keep existing successful raw-response/findings ordering after asserting `result` is a valid `ProviderResult`.

- [ ] **Step 5: Route natural initial review through the same kernel**

In `natural_service.py`, use `json_mode=False` and the same non-completed terminal result path. On success preserve this exact order:

```text
persist_provider_response
append assistant thread message
record COMPLETED
return natural response + usage
```

A successful natural result may continue returning its current response payload, but should also include `attempt_outcome="COMPLETED"`, `safe_error_type=None`, `response_available=True`, and `replayed=False` for contract consistency.

- [ ] **Step 6: Run focused and OX service regressions**

```bash
python -m pytest tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py -q
python -m ruff check src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py
```

Expected: all focused OX service tests pass.

- [ ] **Step 7: Commit structured terminal results**

```bash
git add src/byte_mcp/ox/service.py src/byte_mcp/ox/natural_service.py tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py
git commit -m "fix: return structured OX attempt outcomes"
```

---

### Task 4: Make duplicate initial approval observational and non-transmitting

**Files:**
- Modify: `src/byte_mcp/ox/evidence.py`
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_review_service.py`
- Modify: `tests/ox/test_natural_review_architecture.py`

**Interfaces:**
- Consumes: reconstructed review attempt history.
- Produces: a bounded replay/status packet for an already-claimed initial attempt; no new attempt allocation and no provider call.

- [ ] **Step 1: Write failing sequential duplicate tests**

Add:

```python
def test_duplicate_initial_approval_after_unknown_returns_a001_status_without_provider_call(tmp_path):
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    calls_after_first = len(client.calls)
    second = service.transmit_review(proposal["review_id"])

    assert first["attempt_id"] == "OX-000001-A001"
    assert second["attempt_id"] == "OX-000001-A001"
    assert second["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert second["safe_error_type"] == "OXTransportError"
    assert second["replayed"] is True
    assert second["response_available"] is False
    assert len(client.calls) == calls_after_first == 1
    assert [item["attempt_id"] for item in store.get_review(proposal["review_id"])["attempts"]] == [
        "OX-000001-A001"
    ]
```

Add a completed-success equivalent asserting `response_available=True` and one provider call total.

- [ ] **Step 2: Write the concurrent duplicate test**

Update the existing `BlockingClient` concurrency test so the second call no longer expects `OXApprovalError`. It should receive an observational result for A001 while the first call is in flight:

```python
with ThreadPoolExecutor(max_workers=2) as pool:
    first = pool.submit(service.transmit_review, proposal["review_id"])
    assert client.entered.wait(timeout=5)
    second = pool.submit(service.transmit_review, proposal["review_id"])
    duplicate = second.result(timeout=5)
    assert duplicate["attempt_id"] == "OX-000001-A001"
    assert duplicate["state"] == "TRANSMITTING"
    assert duplicate["attempt_outcome"] is None
    assert duplicate["replayed"] is True
    client.release.set()
    first.result(timeout=5)
assert len(client.calls) == 1
```

- [ ] **Step 3: Run duplicate tests and record RED**

```bash
python -m pytest tests/ox/test_review_service.py -k "duplicate_initial or concurrent_transmit" -q
```

Expected: failures with current `review state does not permit this operation` / `OXApprovalError` behavior.

- [ ] **Step 4: Add a read-only initial-attempt observation helper**

In `EvidenceStore`, add a helper that performs no writes:

```python
def observe_initial_attempt(self, review_id: str) -> dict[str, object] | None:
    with self._lock_for(review_id):
        review = self._reconstruct(review_id)
        self._reject_recovered_review(review)
        attempts = review["attempts"]
        if not attempts:
            return None
        attempt = attempts[0]
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str):
            raise OXEvidenceError("initial attempt evidence is malformed")
        identity = self.read_attempt_identity(review_id, attempt_id)
        if identity.get("phase") not in {"initial", "initial-retry"}:
            raise OXEvidenceError("initial attempt evidence is malformed")
        return {
            "review_id": review_id,
            "state": review["state"],
            "attempt": dict(attempt),
            "identity": identity,
        }
```

Because `read_attempt_identity` also acquires the per-review lock, avoid lock recursion in the actual implementation by reading the immutable attempt file directly through a private no-lock helper or by obtaining the identity outside the locked block after copying the attempt ID. Keep the store's single-process locking contract intact.

- [ ] **Step 5: Make `transmit_review` observe before rejecting non-PREPARED state**

Refactor the top of `transmit_review` to:

```text
load current review
if PREPARED:
    rebuild/verify and attempt normal atomic claim
else if at least one initial attempt exists:
    return bounded observational result for the existing first/current initial attempt
else:
    raise OXApprovalError("review state does not permit this operation")
```

For `TRANSMITTING`, return `attempt_outcome=None`, `safe_error_type=None`, `response_available=False`, `replayed=True`.

For terminal attempts, derive `response_available` only from durable response evidence, not from state alone. A completed protocol failure may have a raw provider response even if natural response evidence is unavailable; natural-service replay should report whether its natural assistant response exists.

- [ ] **Step 6: Preserve atomic first-claim concurrency**

Keep `claim_initial_transmission` as the authoritative write gate. If two calls both initially observe `PREPARED`, exactly one claim succeeds. If the second claim loses the race with `OXEvidenceError`, re-read/observe the now-existing initial attempt and return replay/status instead of raising.

- [ ] **Step 7: Run duplicate, retry, and natural-service regressions**

```bash
python -m pytest tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py -q
```

Expected: all pass; exactly one provider call in every sequential/concurrent duplicate-approval scenario.

- [ ] **Step 8: Commit duplicate approval safety**

```bash
git add src/byte_mcp/ox/evidence.py src/byte_mcp/ox/service.py tests/ox/test_review_service.py tests/ox/test_natural_review_architecture.py
git commit -m "fix: make duplicate OX approval observational"
```

---

### Task 5: Preserve explicit retry semantics after `OUTCOME_UNKNOWN`

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `tests/ox/test_review_service.py`

**Interfaces:**
- Consumes: existing `retry_review(review_id, renewed_approval=True)` and execution result contract.
- Produces: A002 only for an explicit approved retry, with exactly one new provider request.

- [ ] **Step 1: Update the retry test for structured first failure**

Replace exception-based first-attempt assertions with:

```python
def test_unknown_attempt_requires_explicit_renewed_retry_for_a002(tmp_path):
    client = UnknownThenSuccessClient()
    service, store, _, base, target, _ = make_service(tmp_path, client)
    proposal = prepare(service, base, target)

    first = service.transmit_review(proposal["review_id"])
    assert first["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert len(client.calls) == 1

    duplicate = service.transmit_review(proposal["review_id"])
    assert duplicate["replayed"] is True
    assert len(client.calls) == 1

    with pytest.raises(OXApprovalError):
        service.retry_review(proposal["review_id"], renewed_approval=False)
    assert len(client.calls) == 1

    retried = service.retry_review(proposal["review_id"], renewed_approval=True)
    assert retried["attempt_id"] == "OX-000001-A002"
    assert retried["attempt_outcome"] == "COMPLETED"
    assert len(client.calls) == 2
    assert [item["attempt_id"] for item in store.get_review(proposal["review_id"])["attempts"]] == [
        "OX-000001-A001",
        "OX-000001-A002",
    ]
```

- [ ] **Step 2: Run the retry test and record RED if required**

```bash
python -m pytest tests/ox/test_review_service.py -k "explicit_renewed_retry" -q
```

Expected: fail until `retry_review` also uses the execution result contract rather than re-raising known provider errors.

- [ ] **Step 3: Route retry execution through the same one-call kernel**

Keep manifest rebuild/verification and `claim_retry_transmission(..., renewed_approval=True)` unchanged. Reuse the same terminal result path so retry attempts also persist bounded safe error metadata and return structured outcomes.

- [ ] **Step 4: Run retry and full OX service tests**

```bash
python -m pytest tests/ox/test_review_service.py -q
```

Expected: all pass and no test observes an implicit A002.

- [ ] **Step 5: Commit retry preservation**

```bash
git add src/byte_mcp/ox/service.py tests/ox/test_review_service.py
git commit -m "refactor: preserve explicit OX retry contract"
```

---

### Task 6: Harden audit and MCP-facing contract

**Files:**
- Modify: `src/byte_mcp/ox/service.py`
- Modify: `src/byte_mcp/server.py` only if tests show wrapper changes are necessary
- Modify/add: appropriate OX/server tests under `tests/`

**Interfaces:**
- Consumes: structured attempt results.
- Produces: safe error-class audit metadata and unchanged public MCP tool names/arguments.

- [ ] **Step 1: Add failing audit test**

Using `FakeAudit`, assert a rejected/unknown attempt creates an audit event containing only bounded diagnostics:

```python
event = service._audit.events[-1]
action, outcome, fields = event
assert action == "ox_review"
assert outcome == "error"
assert fields["attempt_outcome"] == "OUTCOME_UNKNOWN"
assert fields["safe_error_type"] == "OXTransportError"
assert "Bearer" not in json.dumps(fields)
assert "messages" not in fields
assert "response" not in fields
```

- [ ] **Step 2: Add/adjust MCP wrapper contract test**

Assert `ox_review` still exposes the same caller inputs:

```text
repository, subsystem, target_commit, base_commit, objective, verification,
review_id, approve, retry
```

and that `approve=true` simply returns whatever structured service result is produced; it must not catch and reinterpret terminal provider outcomes.

- [ ] **Step 3: Run focused tests and record RED**

```bash
python -m pytest tests/ox -k "audit or server or wrapper" -q
```

- [ ] **Step 4: Extend `_audit_attempt` safely**

Signature:

```python
def _audit_attempt(
    ...,
    safe_error_type: str | None = None,
) -> None:
```

Add `safe_error_type` to audit fields only when non-null. Never add exception strings.

- [ ] **Step 5: Keep server wrapper minimal**

If no wrapper change is required, do not modify `server.py`. If tests expose exception/result rewriting in the wrapper, change only that behavior and retain the existing FastMCP annotations and exact nine-tool surface.

- [ ] **Step 6: Run OX and server contract tests**

```bash
python -m pytest tests/ox tests/test_combined_smoke_contract.py -q
python -m ruff check src/byte_mcp/ox src/byte_mcp/server.py tests/ox tests/test_combined_smoke_contract.py
```

Expected: pass, with nine-tool discovery contract unchanged.

- [ ] **Step 7: Commit observability/MCP hardening**

```bash
git add src/byte_mcp/ox/service.py src/byte_mcp/server.py tests/ox tests/test_combined_smoke_contract.py
git commit -m "feat: expose safe OX attempt diagnostics"
```

Only stage `server.py` if it actually changed.

---

### Task 7: Prove continuation/revalidation regressions and Wolfram isolation

**Files:**
- Test-only changes if required by intentionally changed shared helper signatures.
- No Wolfram production file may change.

**Interfaces:**
- Consumes: all prior implementation.
- Produces: evidence that the repair did not weaken adjacent OX lifecycle operations or the combined specialist server.

- [ ] **Step 1: Run all OX tests**

```bash
python -m pytest tests/ox -q
```

Expected: all OX tests pass.

- [ ] **Step 2: Run Wolfram tests unchanged**

```bash
python -m pytest tests/wolfram -q
```

Expected: all Wolfram tests pass with zero Wolfram production modifications.

- [ ] **Step 3: Verify no Wolfram production diff exists**

```bash
git diff 75362294966f3ebcd4ab290af9e0d9d020e4de98 -- src/byte_mcp/wolfram
```

Expected: empty output.

- [ ] **Step 4: Run combined smoke contract**

```bash
python -m pytest tests/test_combined_smoke_contract.py -q
```

Expected: pass; exact nine tools remain registered.

- [ ] **Step 5: Run compile and Ruff gates**

```bash
python -m compileall -q src tests scripts
python -m ruff check .
```

Expected: success.

- [ ] **Step 6: Commit any necessary test-only compatibility updates**

```bash
git add tests
git commit -m "test: verify OX execution reliability regressions"
```

Skip the commit if no files changed.

---

### Task 8: Full verification gate and fresh Web UI acceptance protocol

**Files:**
- Modify documentation only if implementation behavior differs from currently documented OX acceptance semantics.
- No live provider call until all automated gates are green.

**Interfaces:**
- Consumes: completed implementation head.
- Produces: exact-head CI evidence and a fresh, bounded live acceptance test using a new review ID.

- [ ] **Step 1: Run repository verification locally where available**

On Windows deployment/worktree:

```powershell
.\scripts\Check.ps1
```

Expected: Python tests, compile/Ruff, and launcher checks pass according to repository script contract.

- [ ] **Step 2: Push the isolated implementation branch and wait for CI**

Required CI lanes:

```text
Python 3.12 Ubuntu: success
Python 3.12 Windows: success
Windows launcher: success
Windows launcher on Pester 6: success
```

Do not describe the implementation as complete until exact-head CI is green.

- [ ] **Step 3: Verify exact implementation diff**

Confirm:

```text
- no src/byte_mcp/wolfram production changes
- no provider/model/endpoint change
- no removed human approval step
- no automatic retry
- no weakened manifest/payload verification
```

- [ ] **Step 4: Deploy the exact green head to the combined local Byte-MCP server**

Use the established guarded stop/start/status/smoke flow. Do not kill processes blindly if launcher identity reports stale; inspect guarded evidence first.

- [ ] **Step 5: Prepare a brand-new OX Web UI acceptance review**

Use a new review ID; never reuse `OX-000005`. Phase 1 must return `transmitted=false` and the exact immutable approval hashes before any provider call.

- [ ] **Step 6: Obtain explicit human approval of that exact new proposal**

Approval must be bound to the new review ID, manifest SHA-256, payload SHA-256, commits, artifact count, byte count, provider, and model.

- [ ] **Step 7: Run exactly one live approved OX provider attempt**

Acceptance is satisfied by either:

```text
COMPLETED with durable natural assistant response and exactly one provider attempt
```

or, if the provider genuinely fails:

```text
structured terminal NOT_SENT / REJECTED / OUTCOME_UNKNOWN
with safe_error_type, exactly one A001, and no masked lifecycle error
```

A duplicate `approve=true, retry=false` observation may then be issued deliberately to prove it returns the same A001 status and makes zero additional provider calls.

- [ ] **Step 8: Final acceptance evidence**

Require:

```text
initial attempt count: 1
duplicate approval provider-call delta: 0
no A002 without explicit retry
safe terminal outcome visible to Web UI
safe_error_type present for non-completed known provider failures
raw/natural evidence ordering correct on success
OX-000005 unchanged
Wolfram untouched
```

- [ ] **Step 9: Commit any final documentation-only closeout**

```bash
git add docs CHANGELOG.md
git commit -m "docs: close OX provider execution reliability"
```

Only include files that genuinely need documentation updates.

---

## Plan Self-Review

- Spec coverage: provider execution, duplicate approval, retry, durable error diagnostics, audit, success ordering, regression isolation, and live rollout are each mapped to explicit tasks.
- Placeholder scan: no `TBD`, `TODO`, generic "add tests", or unspecified implementation steps remain.
- Type consistency: `ProviderAttemptResult`, `AttemptOutcome`, `safe_error_type`, `attempt_outcome`, `response_available`, and `replayed` use the same names throughout.
- Scope check: this plan is one bounded architectural subsystem repair; continuation/revalidation are regression consumers, not independent redesigns.
- Safety check: no task authorizes debugging through live provider retries; the first live call occurs only after exact-head automated verification and a new two-phase approval.