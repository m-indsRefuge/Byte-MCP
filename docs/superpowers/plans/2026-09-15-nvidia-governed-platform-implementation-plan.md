# NVIDIA Governed Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Byte-MCP's qualified NVIDIA review integration into a governed two-surface provider platform with a fluent `nvidia_query` path and the existing approval-gated `nvidia_review` path sharing one authoritative model/runtime foundation.

**Architecture:** Build an immutable shared NVIDIA model registry and surface-specific execution profiles, migrate the review path to consume that registry without changing historical request identities, then add a lightweight query protocol/service that performs at most one provider request per invocation. Add shared typed errors, bounded audit metadata, provider-free readiness/qualification, model maturity artifacts, and failure documentation while preserving the existing review evidence lifecycle.

**Tech Stack:** Python 3.12.10, pytest 9.1.1, Ruff 0.16.1, stdlib HTTP/JSON/hash primitives already used by Byte-MCP, FastMCP/MCP server surface already present in `src/byte_mcp/server.py`, PowerShell 7 for local qualification orchestration.

**Spec:** `docs/superpowers/specs/2026-09-15-nvidia-governed-platform-design.md`

## Frozen Starting Identity

- Design commit: `4e57ad4dac5c0568f38b71b16ef84da37f4f1b50`
- Implementation-plan commit: `<PLAN_COMMIT>` — created as a documentation-only child of the design commit before N05 branch creation.
- Qualified predecessor: `f84e38d4fbe7325e998f8fc7139a7cb1db4635eb`
- Predecessor subject: `feat: add governed NVIDIA review model selection`
- New implementation branch: `feat/nvidia-provider-n05-governed-platform`
- Recommended isolated worktree: `C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n05-governed-platform`
- The N04 design/plan worktree remains frozen after the plan commit and N05 branch creation.

## Global Constraints

- NVIDIA workflow only. Do not call OX or Wolfram while implementing or qualifying this plan.
- No NVIDIA provider request is authorized by this plan.
- `NVIDIA_API_KEY` must be unset for all offline implementation and qualification commands.
- Runtime promotion must not occur during implementation.
- Live runtime at `C:\Users\nolan\AIProjects\Byte-MCP-runtime\daemon` must remain untouched until an explicit promotion step after offline qualification.
- Initial governed aliases are exactly `lightning` and `deepseek-v4-pro`.
- Exact provider IDs are `nvidia/nemotron-3.5-lightning-30b-a3b` and `deepseek-ai/deepseek-v4-pro-0813`.
- Default query alias is `deepseek-v4-pro`.
- Runtime execution must not call NVIDIA `/v1/models`.
- There is no automatic retry, fallback, provider substitution, or dynamic model routing.
- One `nvidia_query` invocation may start at most one provider request.
- `nvidia_review` keeps PREPARE → exact-hash approval → exactly one provider attempt → terminal evidence.
- Review packet identity remains model-neutral.
- Review model/profile become immutable before approval.
- Historical NVR evidence must remain readable.
- Credentials load only after local input/model validation and immediately before provider-bound execution.
- Offline qualification must require no NVIDIA credential and no network.
- Live qualification is a separate future authorization.
- Repository-wide pre-existing pytest/format debt is handled differentially: candidate may introduce zero new failures/debt; every NVIDIA-owned changed file must be individually clean.
- Every implemented subsystem must update the living failure map before the milestone is considered complete.
- Do not push or merge unless explicitly requested.

---

# File Structure

The plan intentionally adds focused modules rather than growing `review_protocol.py`, `review_service.py`, or `server.py` into multi-purpose provider modules.

## New production files

### `src/byte_mcp/nvidia/models.py`

Single authoritative governed model registry.

Defines:

```python
class NvidiaQualificationState(str, Enum): ...
@dataclass(frozen=True)
class NvidiaExecutionProfile: ...
@dataclass(frozen=True)
class NvidiaModelDefinition: ...

NVIDIA_DEFAULT_QUERY_MODEL = "deepseek-v4-pro"
NVIDIA_MODELS: Mapping[str, NvidiaModelDefinition]

def resolve_model(alias: str) -> NvidiaModelDefinition
def resolve_query_model(alias: str | None) -> NvidiaModelDefinition
def resolve_review_model(alias: str) -> NvidiaModelDefinition
def model_for_provider_id(provider_model_id: str) -> NvidiaModelDefinition
```

### `src/byte_mcp/nvidia/query_protocol.py`

Pure, provider-free query validation, canonical request creation, response/result types, and request hashing.

Defines:

```python
@dataclass(frozen=True)
class NvidiaPreparedQuery: ...
@dataclass(frozen=True)
class NvidiaQueryResult: ...

def prepare_nvidia_query(input_text: str, model_alias: str | None = None) -> NvidiaPreparedQuery
def parse_nvidia_query_response(
    prepared: NvidiaPreparedQuery,
    status_code: int,
    response_body: bytes,
    *,
    provider_request_id: str | None = None,
) -> NvidiaQueryResult
```

### `src/byte_mcp/nvidia/query_service.py`

One-invocation/one-attempt orchestration and lazy credential boundary.

Defines:

```python
class NvidiaQueryService:
    def prepare(self, input_text: str, model_alias: str | None = None) -> NvidiaPreparedQuery: ...
    def execute(self, input_text: str, model_alias: str | None = None) -> dict[str, object]: ...
```

The service must call `prepare()` before acquiring credentials.

### `src/byte_mcp/nvidia/query_audit.py`

Bounded metadata-only audit writer for `nvidia_query`; never persists credential or full prompt/response text.

Defines:

```python
@dataclass(frozen=True)
class NvidiaQueryAuditEvent: ...
class NvidiaQueryAuditStore:
    def append(self, event: NvidiaQueryAuditEvent) -> None: ...
```

### `src/byte_mcp/nvidia/qualification.py`

Provider-free readiness and deterministic offline qualification.

Defines:

```python
@dataclass(frozen=True)
class NvidiaReadinessReport: ...
def inspect_nvidia_readiness(...) -> NvidiaReadinessReport
def qualify_nvidia_offline(...) -> dict[str, object]
```

## Modified production files

### `src/byte_mcp/nvidia/review_protocol.py`

Remove the competing authoritative model registry. Keep compatibility exports only if existing tests/importers need them; those exports must be derived from `models.NVIDIA_MODELS`.

`prepare_nvidia_review_request(packet, *, model_id: str)` remains an internal provider-ID-level function so existing evidence derivation and historical identity remain stable.

### `src/byte_mcp/nvidia/review_service.py`

Public PREPARE path accepts a friendly model alias, resolves it through `resolve_review_model()`, then passes the exact provider ID into the unchanged review request builder.

Approval/transmission continue to accept no model selector.

### `src/byte_mcp/nvidia/errors.py`

Add stable provider/query error codes and structured safe metadata. Existing NVIDIA exception classes must remain compatible unless tests prove a safe migration.

### `src/byte_mcp/nvidia/chat.py`

Reuse the existing transport. Add only the smallest boundary needed for a fully prepared canonical query request to execute exactly once. Do not add retries.

### `src/byte_mcp/nvidia/settings.py`

Add bounded query-specific settings only if not already expressible by existing provider settings: query response byte cap, query audit file path, optional default alias override only if the spec-approved default remains the fallback.

### `src/byte_mcp/server.py`

Expose `nvidia_query`; migrate PREPARE-side `nvidia_review` selection to friendly alias. Tool count becomes eight if no other surface changes.

### `src/byte_mcp/nvidia/__init__.py`

Export only stable provider-platform types/functions needed by other Byte-MCP modules.

## New tests

- `tests/nvidia/test_models.py`
- `tests/nvidia/test_review_shared_model_registry.py`
- `tests/nvidia/test_errors_platform.py`
- `tests/nvidia/test_query_protocol.py`
- `tests/nvidia/test_query_service.py`
- `tests/nvidia/test_query_audit.py`
- `tests/nvidia/test_query_mcp.py`
- `tests/nvidia/test_platform_security_invariants.py`
- `tests/nvidia/test_qualification.py`

## Modified tests

- `tests/nvidia/test_n04_governed_model_selection.py`
- `tests/nvidia/test_n04_immutable_model_identity.py`
- `tests/nvidia/test_review_protocol.py`
- `tests/nvidia/test_review_service_prepare.py`
- `tests/nvidia/test_review_mcp.py`
- `tests/test_server.py`
- `tests/test_nvidia_runtime_integration.py` if it is part of the current lineage surface contract.

## Qualification/docs files

- `qualification/nvidia/README.md`
- `qualification/nvidia/model-registry.json`
- `qualification/nvidia/offline-receipts/.gitkeep`
- `qualification/nvidia/live-canary-receipts/.gitkeep`
- `FAILURE_MAP.md` or the existing root failure map if one already exists.

---

# Task 0: Commit This Plan, Then Create the N05 Isolated Worktree

**Files:**
- No source changes.
- Worktree: `C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n05-governed-platform`
- Branch: `feat/nvidia-provider-n05-governed-platform`

**Interfaces:**
- Consumes: design commit `4e57ad4dac5c0568f38b71b16ef84da37f4f1b50`
- Produces: documentation-only plan commit `<PLAN_COMMIT>`, then a clean isolated implementation workspace rooted at that plan commit with zero provider/runtime changes.

- [ ] **Step 1: Verify the N04 design worktree is clean and on the exact design commit**

Run:

```powershell
cd "C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n04-governed-model-selection"
git rev-parse HEAD
git branch --show-current
git status --porcelain
```

Expected:

```text
4e57ad4dac5c0568f38b71b16ef84da37f4f1b50
feat/nvidia-provider-n04-governed-model-selection
```

`git status --porcelain` must be empty.

- [ ] **Step 2: Commit this implementation plan as the only repository change**

Place this file at:

```text
docs/superpowers/plans/2026-09-15-nvidia-governed-platform-implementation-plan.md
```

Verify the only change is that path, then:

```powershell
git add -- "docs/superpowers/plans/2026-09-15-nvidia-governed-platform-implementation-plan.md"
git diff --cached --check
git diff --cached --name-only
git commit -m "docs: plan governed NVIDIA provider platform"
```

Record:

```powershell
$PlanCommit = (git rev-parse HEAD).Trim()
$PlanParent = (git rev-parse HEAD^).Trim()
```

Require:

```text
PLAN_PARENT=4e57ad4dac5c0568f38b71b16ef84da37f4f1b50
WORKTREE_CLEAN=PASS
```

The actual `$PlanCommit` becomes `<PLAN_COMMIT>` everywhere below.

- [ ] **Step 3: Create the new N05 worktree from the plan commit**

Use the git-worktree workflow at execution time.

Run:

```powershell
git -C "C:\Users\nolan\AIProjects\Byte-MCP" worktree add `
  -b "feat/nvidia-provider-n05-governed-platform" `
  "C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n05-governed-platform" `
  $PlanCommit
```

Expected: worktree is created at the exact implementation-plan commit.

- [ ] **Step 4: Establish provider-free environment**

Run:

```powershell
Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
cd "C:\Users\nolan\AIProjects\Byte-MCP-nvidia-n05-governed-platform"
git rev-parse HEAD
git branch --show-current
git status --porcelain
```

Expected:

```text
HEAD=<PLAN_COMMIT>
branch=feat/nvidia-provider-n05-governed-platform
status=<empty>
```

- [ ] **Step 5: Run frozen NVIDIA baseline**

Use the dev venv:

```powershell
$Python = "C:\Users\nolan\AIProjects\Byte-MCP\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

& $Python -m pytest -q -p no:cacheprovider tests/nvidia tests/test_server.py
& $Python -m ruff check --no-cache src tests
& $Python -m compileall -q src
```

Expected: NVIDIA regression, Ruff check, and compile pass. Do not require repository-wide Ruff formatting to be green; N04 already established pre-existing format debt.

- [ ] **Step 6: Record the N05 baseline locally**

No commit is required. Record:

```text
N05_BASE=<PLAN_COMMIT>
NVIDIA_PROVIDER_CALLS=0
LIVE_RUNTIME_MUTATIONS=0
```

---

# Task 1: Create the Authoritative Governed Model Registry

**Files:**
- Create: `src/byte_mcp/nvidia/models.py`
- Create: `tests/nvidia/test_models.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: exact N04 Lightning/DeepSeek execution controls currently represented in `review_protocol.py`.
- Produces:
  - `NvidiaQualificationState`
  - `NvidiaExecutionProfile`
  - `NvidiaModelDefinition`
  - `NVIDIA_MODELS`
  - `NVIDIA_DEFAULT_QUERY_MODEL`
  - `resolve_model`
  - `resolve_query_model`
  - `resolve_review_model`
  - `model_for_provider_id`

- [ ] **Step 1: Write failing registry tests**

Create tests that assert exactly:

```python
def test_registry_has_exact_initial_aliases() -> None:
    assert set(NVIDIA_MODELS) == {"lightning", "deepseek-v4-pro"}

def test_default_query_model_is_deepseek() -> None:
    assert NVIDIA_DEFAULT_QUERY_MODEL == "deepseek-v4-pro"
    assert resolve_query_model(None).alias == "deepseek-v4-pro"

def test_lightning_provider_identity_is_exact() -> None:
    model = resolve_model("lightning")
    assert model.provider_model_id == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert model.query_enabled is True
    assert model.review_enabled is True

def test_deepseek_provider_identity_is_exact() -> None:
    model = resolve_model("deepseek-v4-pro")
    assert model.provider_model_id == "deepseek-ai/deepseek-v4-pro-0813"
    assert model.query_enabled is True
    assert model.review_enabled is True

def test_unknown_alias_rejected_locally() -> None:
    with pytest.raises(ValueError, match="model is not allowed"):
        resolve_model("unknown-model")

def test_provider_id_reverse_lookup_is_unique() -> None:
    assert model_for_provider_id(
        "deepseek-ai/deepseek-v4-pro-0813"
    ).alias == "deepseek-v4-pro"
```

Also assert the exact N04 review profiles:

```python
assert resolve_review_model("lightning").review_profile.temperature == 0.2
assert resolve_review_model("lightning").review_profile.top_p == 0.95
assert resolve_review_model("lightning").review_profile.max_tokens == 4096
assert resolve_review_model("lightning").review_profile.seed is None
assert dict(resolve_review_model("lightning").review_profile.extra_body) == {
    "chat_template_kwargs": {"enable_thinking": False}
}

assert resolve_review_model("deepseek-v4-pro").review_profile.temperature == 1.0
assert resolve_review_model("deepseek-v4-pro").review_profile.top_p == 0.95
assert resolve_review_model("deepseek-v4-pro").review_profile.max_tokens == 16384
assert resolve_review_model("deepseek-v4-pro").review_profile.seed == 42
assert dict(resolve_review_model("deepseek-v4-pro").review_profile.extra_body) == {
    "chat_template_kwargs": {"thinking": False}
}
```

If the existing N04 body stores the thinking object at a slightly different nesting level, copy the exact existing bytes/structure rather than normalizing it.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
& $Python -m pytest -q tests/nvidia/test_models.py
```

Expected: import/module failures because `models.py` does not exist.

- [ ] **Step 3: Implement immutable registry types**

Create `models.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class NvidiaQualificationState(str, Enum):
    REGISTERED = "REGISTERED"
    OFFLINE_QUALIFIED = "OFFLINE_QUALIFIED"
    QUERY_LIVE_QUALIFIED = "QUERY_LIVE_QUALIFIED"
    REVIEW_LIVE_QUALIFIED = "REVIEW_LIVE_QUALIFIED"


@dataclass(frozen=True)
class NvidiaExecutionProfile:
    temperature: float
    top_p: float
    max_tokens: int
    seed: int | None
    extra_body: Mapping[str, object]


@dataclass(frozen=True)
class NvidiaModelDefinition:
    alias: str
    provider_model_id: str
    query_enabled: bool
    review_enabled: bool
    query_profile: NvidiaExecutionProfile | None
    review_profile: NvidiaExecutionProfile | None
    query_qualification: NvidiaQualificationState
    review_qualification: NvidiaQualificationState
```

Build immutable `MappingProxyType` entries for the exact two approved aliases.

For the first implementation:
- Lightning review qualification = `REVIEW_LIVE_QUALIFIED`.
- DeepSeek review qualification = `OFFLINE_QUALIFIED`.
- Both query qualification values start at `OFFLINE_QUALIFIED` only after the query protocol is offline-qualified later; until Task 8, use `REGISTERED` and update via a deliberate registry edit in Task 8.
- Query execution profiles use the same provider-recommended deterministic profile values approved in the design unless the existing NVIDIA chat tests prove a more exact provider contract. Do not expose query sampling overrides at MCP.

- [ ] **Step 4: Implement strict local resolvers**

Required behavior:

```python
def resolve_model(alias: str) -> NvidiaModelDefinition:
    try:
        return NVIDIA_MODELS[alias]
    except KeyError as exc:
        raise ValueError("model is not allowed") from exc


def resolve_query_model(alias: str | None) -> NvidiaModelDefinition:
    resolved = resolve_model(alias or NVIDIA_DEFAULT_QUERY_MODEL)
    if not resolved.query_enabled or resolved.query_profile is None:
        raise ValueError("model is not enabled for query")
    return resolved


def resolve_review_model(alias: str) -> NvidiaModelDefinition:
    resolved = resolve_model(alias)
    if not resolved.review_enabled or resolved.review_profile is None:
        raise ValueError("model is not enabled for review")
    return resolved
```

`model_for_provider_id()` must reject unknown IDs and detect impossible duplicate provider IDs during module-level registry construction.

- [ ] **Step 5: Run registry tests GREEN**

```powershell
& $Python -m pytest -q tests/nvidia/test_models.py
& $Python -m ruff check --no-cache src/byte_mcp/nvidia/models.py tests/nvidia/test_models.py
& $Python -m ruff format --check src/byte_mcp/nvidia/models.py tests/nvidia/test_models.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/nvidia/models.py src/byte_mcp/nvidia/__init__.py tests/nvidia/test_models.py
git commit -m "feat: add governed NVIDIA model registry"
```

---

# Task 2: Migrate Review Model Selection to the Shared Registry Without Changing Request Identity

**Files:**
- Modify: `src/byte_mcp/nvidia/review_protocol.py`
- Modify: `src/byte_mcp/nvidia/review_service.py`
- Modify: `src/byte_mcp/server.py`
- Create: `tests/nvidia/test_review_shared_model_registry.py`
- Modify: `tests/nvidia/test_n04_governed_model_selection.py`
- Modify: `tests/nvidia/test_n04_immutable_model_identity.py`
- Modify: `tests/nvidia/test_review_protocol.py`
- Modify: `tests/nvidia/test_review_service_prepare.py`
- Modify: `tests/nvidia/test_review_mcp.py`

**Interfaces:**
- Consumes:
  - `resolve_review_model(alias: str)`
  - `model_for_provider_id(provider_model_id: str)`
- Produces:
  - public review PREPARE selector `model="<friendly alias>"`
  - internal provider-ID request builder preserved for evidence re-derivation
  - unchanged approval surface.

- [ ] **Step 1: Write a request-identity preservation test before moving definitions**

Capture the exact canonical request bytes/hashes produced by the current N04 code for the same deterministic fixture packet and exact provider IDs.

Test structure:

```python
def test_shared_registry_migration_preserves_n04_request_identity(packet) -> None:
    lightning = prepare_nvidia_review_request(
        packet,
        model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
    )
    deepseek = prepare_nvidia_review_request(
        packet,
        model_id="deepseek-ai/deepseek-v4-pro-0813",
    )

    assert lightning.body["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert deepseek.body["model"] == "deepseek-ai/deepseek-v4-pro-0813"

    # Freeze the pre-migration expected body fields from the N04 tests.
    assert lightning.body["temperature"] == 0.2
    assert deepseek.body["temperature"] == 1.0
```

Do not invent new fixed SHA literals unless the fixture is guaranteed byte-stable across machines. Prefer comparing pre/post builders inside the RED/GREEN migration if the current test architecture permits it.

- [ ] **Step 2: Add failing friendly-alias service/MCP tests**

Required PREPARE behavior:

```python
result = service.prepare_review(
    repository="a-scanner",
    subsystem="core",
    target_commit=TARGET,
    base_commit=BASE,
    objective="review objective",
    verification=VERIFICATION,
    model="deepseek-v4-pro",
)
assert result["model_id"] == "deepseek-ai/deepseek-v4-pro-0813"
```

Required approval behavior remains:

```python
service.transmit_review(
    review_id=result["review_id"],
    expected_request_sha256=result["request_sha256"],
)
```

No model argument is accepted after PREPARE.

- [ ] **Step 3: Run focused tests RED**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_review_shared_model_registry.py `
  tests/nvidia/test_review_service_prepare.py `
  tests/nvidia/test_review_mcp.py
```

Expected: failures because review PREPARE still exposes/consumes the N04 `model_id` path.

- [ ] **Step 4: Replace authoritative review profile definitions with compatibility views**

`review_protocol.py` may retain these names if tests/importers rely on them:

```python
NvidiaReviewModelProfile
NVIDIA_REVIEW_MODEL_PROFILES
```

but they must be derived from `models.NVIDIA_MODELS`, not separately authored constants.

The internal function remains:

```python
def prepare_nvidia_review_request(
    packet: NvidiaReviewPacket,
    *,
    model_id: str,
) -> NvidiaPreparedReviewRequest:
```

It obtains the exact profile via `model_for_provider_id(model_id).review_profile`.

This preserves the evidence layer, which already re-derives old requests from `prepared_request.model_id`.

- [ ] **Step 5: Change review PREPARE to friendly alias only**

At the service boundary:

```python
def prepare_review(..., *, model: str) -> dict[str, object]:
    definition = resolve_review_model(model)
    prepared_request = prepare_nvidia_review_request(
        packet,
        model_id=definition.provider_model_id,
    )
```

At the MCP boundary:
- PREPARE accepts `model`.
- PREPARE does not accept public `model_id`.
- approval accepts `review_id`, `expected_request_sha256`, `approve=True`.
- any `model` supplied during approval makes the invocation invalid.

Keep the exact existing review-mode validation discipline.

- [ ] **Step 6: Prove historical evidence remains readable**

Add/retain tests that construct historical manifests with both provider IDs and verify:
- manifest validation passes for approved provider IDs;
- `nvidia_get_review` summary/attempt/manifest views still read them;
- no migration rewrites historical evidence.

- [ ] **Step 7: Run the complete review/N04 regression**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_n04_governed_model_selection.py `
  tests/nvidia/test_n04_immutable_model_identity.py `
  tests/nvidia/test_review_protocol.py `
  tests/nvidia/test_review_service_prepare.py `
  tests/nvidia/test_review_service_transmit.py `
  tests/nvidia/test_review_evidence.py `
  tests/nvidia/test_review_mcp.py `
  tests/nvidia/test_review_shared_model_registry.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add `
  src/byte_mcp/nvidia/review_protocol.py `
  src/byte_mcp/nvidia/review_service.py `
  src/byte_mcp/server.py `
  tests/nvidia/test_review_shared_model_registry.py `
  tests/nvidia/test_n04_governed_model_selection.py `
  tests/nvidia/test_n04_immutable_model_identity.py `
  tests/nvidia/test_review_protocol.py `
  tests/nvidia/test_review_service_prepare.py `
  tests/nvidia/test_review_mcp.py

git commit -m "refactor: share governed NVIDIA model registry"
```

---

# Task 3: Establish the Shared Typed NVIDIA Error Vocabulary

**Files:**
- Modify: `src/byte_mcp/nvidia/errors.py`
- Create: `tests/nvidia/test_errors_platform.py`
- Modify: `src/byte_mcp/nvidia/chat.py` only where transport exceptions are classified.

**Interfaces:**
- Produces:

```python
class NvidiaErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    MODEL_NOT_ENABLED = "MODEL_NOT_ENABLED"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"
    RESPONSE_INVALID = "RESPONSE_INVALID"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"


class NvidiaPlatformError(Exception):
    code: NvidiaErrorCode
    provider_started: bool
    safe_to_invoke_fresh: bool
    status_code: int | None
```

- [ ] **Step 1: Write RED tests for safe structured errors**

Test:

```python
error = NvidiaPlatformError(
    code=NvidiaErrorCode.MODEL_NOT_ALLOWED,
    message="model is not allowed",
    provider_started=False,
    safe_to_invoke_fresh=True,
)
assert error.to_dict() == {
    "code": "MODEL_NOT_ALLOWED",
    "message": "model is not allowed",
    "provider_started": False,
    "safe_to_invoke_fresh": True,
    "status_code": None,
    "automatic_retry": False,
}
```

Assert secrets passed as lower-level exception text are never copied into `to_dict()` unless the message is explicitly safe.

- [ ] **Step 2: Run tests RED**

```powershell
& $Python -m pytest -q tests/nvidia/test_errors_platform.py
```

- [ ] **Step 3: Implement the enum/base exception without deleting existing exceptions**

Existing exception names used by N01-N04 stay available. They may subclass `NvidiaPlatformError` or be mapped at service boundaries.

Do not rewrite all historical exception behavior in one task.

- [ ] **Step 4: Add deterministic HTTP/transport classification helpers**

Required classification:
- HTTP 401/403 → `AUTHENTICATION_FAILED`
- HTTP 429 → `RATE_LIMITED`
- other provider 4xx/5xx → `PROVIDER_REJECTED`
- timeout/socket/TLS/DNS style failures → `TRANSPORT_FAILED`
- malformed JSON/schema → `RESPONSE_INVALID`
- local size cap → `RESPONSE_TOO_LARGE`

No classifier performs retry.

- [ ] **Step 5: Run errors + existing chat tests**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_errors_platform.py `
  tests/nvidia/test_chat_request.py `
  tests/nvidia/test_chat_execution.py `
  tests/nvidia/test_chat_response.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/byte_mcp/nvidia/errors.py src/byte_mcp/nvidia/chat.py tests/nvidia/test_errors_platform.py
git commit -m "feat: add typed NVIDIA platform errors"
```

---

# Task 4: Build the Provider-Free `nvidia_query` Protocol and Request Identity

**Files:**
- Create: `src/byte_mcp/nvidia/query_protocol.py`
- Create: `tests/nvidia/test_query_protocol.py`

**Interfaces:**
- Consumes: `resolve_query_model()`
- Produces:
  - `NvidiaPreparedQuery`
  - `NvidiaQueryResult`
  - `prepare_nvidia_query()`
  - `parse_nvidia_query_response()`

- [ ] **Step 1: Write RED tests for local validation and default model**

Required tests:

```python
def test_prepare_defaults_to_deepseek() -> None:
    prepared = prepare_nvidia_query("Explain Python task cancellation.")
    assert prepared.model_alias == "deepseek-v4-pro"
    assert prepared.provider_model_id == "deepseek-ai/deepseek-v4-pro-0813"

def test_prepare_rejects_blank_input() -> None:
    with pytest.raises(NvidiaPlatformError) as exc:
        prepare_nvidia_query("   ")
    assert exc.value.code is NvidiaErrorCode.INVALID_REQUEST
    assert exc.value.provider_started is False

def test_prepare_rejects_unknown_model_before_network() -> None:
    with pytest.raises(NvidiaPlatformError) as exc:
        prepare_nvidia_query("hello", model_alias="not-real")
    assert exc.value.code is NvidiaErrorCode.MODEL_NOT_ALLOWED
    assert exc.value.provider_started is False
```

- [ ] **Step 2: Write RED deterministic identity tests**

For identical input + alias:

```python
a = prepare_nvidia_query("hello", "deepseek-v4-pro")
b = prepare_nvidia_query("hello", "deepseek-v4-pro")
assert a.body_bytes == b.body_bytes
assert a.request_sha256 == b.request_sha256
```

For same input + different models:

```python
a = prepare_nvidia_query("hello", "deepseek-v4-pro")
b = prepare_nvidia_query("hello", "lightning")
assert a.request_sha256 != b.request_sha256
```

- [ ] **Step 3: Run query protocol tests RED**

```powershell
& $Python -m pytest -q tests/nvidia/test_query_protocol.py
```

- [ ] **Step 4: Implement canonical prepared-query type**

Use an immutable dataclass containing:

```python
@dataclass(frozen=True)
class NvidiaPreparedQuery:
    model_alias: str
    provider_model_id: str
    endpoint: str
    body: Mapping[str, object]
    body_bytes: bytes
    request_sha256: str
```

The body must contain only deterministic profile-owned controls and:

```python
{
    "model": definition.provider_model_id,
    "messages": [{"role": "user", "content": input_text}],
    ...
}
```

No credential/header data is hashed or serialized into this object.

- [ ] **Step 5: Implement bounded response parsing**

`NvidiaQueryResult` contains:

```python
@dataclass(frozen=True)
class NvidiaQueryResult:
    model_alias: str
    provider_model_id: str
    response: str
    request_sha256: str
    finish_reason: str | None
    provider_request_id: str | None
    response_bytes: int
```

Parser requirements:
- require one valid assistant completion;
- reject malformed JSON/schema as `RESPONSE_INVALID`;
- reject response beyond the configured cap as `RESPONSE_TOO_LARGE`;
- do not return raw provider payload by default.

- [ ] **Step 6: Run query protocol tests GREEN**

```powershell
& $Python -m pytest -q tests/nvidia/test_query_protocol.py
& $Python -m ruff check --no-cache src/byte_mcp/nvidia/query_protocol.py tests/nvidia/test_query_protocol.py
& $Python -m ruff format --check src/byte_mcp/nvidia/query_protocol.py tests/nvidia/test_query_protocol.py
```

- [ ] **Step 7: Commit**

```powershell
git add src/byte_mcp/nvidia/query_protocol.py tests/nvidia/test_query_protocol.py
git commit -m "feat: add NVIDIA query protocol"
```

---

# Task 5: Build the Exactly-Once Query Service with Lazy Credential Loading

**Files:**
- Create: `src/byte_mcp/nvidia/query_service.py`
- Create: `tests/nvidia/test_query_service.py`
- Modify: `src/byte_mcp/nvidia/chat.py` only if needed to expose one explicit prepared-request execution method.
- Modify: `src/byte_mcp/nvidia/settings.py` only for bounded query response/audit settings.

**Interfaces:**
- Consumes: `prepare_nvidia_query()`, existing NVIDIA credential loader/client.
- Produces:

```python
class NvidiaQueryService:
    def prepare(self, input_text: str, model_alias: str | None = None) -> NvidiaPreparedQuery
    def execute(self, input_text: str, model_alias: str | None = None) -> dict[str, object]
```

- [ ] **Step 1: Write RED test proving credential acquisition happens after validation**

Use a credential loader stub that raises if called.

```python
def test_invalid_model_fails_before_credential_load() -> None:
    credential_calls = 0

    def credential_loader() -> str:
        nonlocal credential_calls
        credential_calls += 1
        raise AssertionError("credential loader must not run")

    service = NvidiaQueryService(..., credential_loader=credential_loader)

    with pytest.raises(NvidiaPlatformError) as exc:
        service.execute("hello", "not-real")

    assert exc.value.code is NvidiaErrorCode.MODEL_NOT_ALLOWED
    assert credential_calls == 0
```

- [ ] **Step 2: Write RED exactly-one-provider-call tests**

Success case:

```python
transport_calls = 0

def transport(prepared, api_key):
    nonlocal transport_calls
    transport_calls += 1
    return FakeResponse(...)

result = service.execute("hello", "lightning")
assert transport_calls == 1
assert result["model"] == "lightning"
```

Failure case:

```python
def transport(prepared, api_key):
    nonlocal transport_calls
    transport_calls += 1
    raise TimeoutError("timeout")

with pytest.raises(NvidiaPlatformError) as exc:
    service.execute("hello", "lightning")

assert transport_calls == 1
assert exc.value.code is NvidiaErrorCode.TRANSPORT_FAILED
assert exc.value.provider_started is True
```

There must be no second call.

- [ ] **Step 3: Run service tests RED**

```powershell
& $Python -m pytest -q tests/nvidia/test_query_service.py
```

- [ ] **Step 4: Implement `prepare()` as provider-free**

It calls only `prepare_nvidia_query()`.

- [ ] **Step 5: Implement `execute()` with explicit sequence**

The implementation sequence is fixed:

```python
prepared = self.prepare(input_text, model_alias)
api_key = self._credential_loader()
started = self._clock()
response = self._transport.send_once(prepared, api_key)
result = parse_nvidia_query_response(...)
return result_dict
```

Do not wrap this in retry libraries or loops.

Credential failure maps to `CREDENTIAL_UNAVAILABLE` with `provider_started=False`.

- [ ] **Step 6: Run query service + chat/security tests**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_query_service.py `
  tests/nvidia/test_chat_execution.py `
  tests/nvidia/test_security_invariants.py `
  tests/nvidia/test_n03_security_invariants.py
```

- [ ] **Step 7: Commit**

```powershell
git add `
  src/byte_mcp/nvidia/query_service.py `
  src/byte_mcp/nvidia/chat.py `
  src/byte_mcp/nvidia/settings.py `
  tests/nvidia/test_query_service.py

git commit -m "feat: add NVIDIA query service"
```

Stage only files actually changed; do not stage unchanged files merely because they appear in this command template.

---

# Task 6: Add Bounded Query Audit Metadata and Provider-Free Readiness

**Files:**
- Create: `src/byte_mcp/nvidia/query_audit.py`
- Create: `tests/nvidia/test_query_audit.py`
- Create: `src/byte_mcp/nvidia/qualification.py`
- Create: `tests/nvidia/test_qualification.py`
- Modify: `src/byte_mcp/nvidia/query_service.py`
- Modify: `src/byte_mcp/nvidia/settings.py`

**Interfaces:**
- Produces:
  - metadata-only append store;
  - `inspect_nvidia_readiness()`;
  - no MCP tool yet.

- [ ] **Step 1: Write RED audit secrecy tests**

Audit event serialization must include:

```text
timestamp
surface
model_alias
provider_model_id
request_sha256
provider_started
status_code
finish_reason
request_bytes
response_bytes
duration_ms
outcome
```

It must not contain:
- full input;
- full model response;
- API key;
- Authorization header.

Test with unique sentinel secrets and assert they are absent from the written JSONL bytes.

- [ ] **Step 2: Write RED readiness tests**

Provider-free readiness report must include:
- endpoint;
- default query alias;
- enabled query aliases;
- enabled review aliases;
- credential presence boolean only;
- request-builder status;
- response-bounds status;
- review-evidence status;
- expected MCP surface names.

Use an injected environment mapping/credential-presence function; do not require a real key.

- [ ] **Step 3: Run RED**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_query_audit.py `
  tests/nvidia/test_qualification.py
```

- [ ] **Step 4: Implement metadata-only JSONL writer**

Use deterministic UTF-8 JSON with one event per line. The audit layer receives only the safe metadata dataclass, never raw prompt/response.

- [ ] **Step 5: Wire query service audit events**

Required events:
- local rejection: `provider_started=False`;
- credential unavailable: `provider_started=False`;
- provider started/success: `provider_started=True`, outcome `SUCCESS`;
- provider error after start: `provider_started=True`, typed outcome.

Do not let audit-write failure trigger a second provider request.

- [ ] **Step 6: Implement provider-free readiness**

`inspect_nvidia_readiness()` must not instantiate a provider client in a way that loads credentials or makes network calls.

- [ ] **Step 7: Run GREEN**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_query_audit.py `
  tests/nvidia/test_qualification.py `
  tests/nvidia/test_query_service.py
```

- [ ] **Step 8: Commit**

```powershell
git add `
  src/byte_mcp/nvidia/query_audit.py `
  src/byte_mcp/nvidia/qualification.py `
  src/byte_mcp/nvidia/query_service.py `
  src/byte_mcp/nvidia/settings.py `
  tests/nvidia/test_query_audit.py `
  tests/nvidia/test_qualification.py

git commit -m "feat: add NVIDIA query audit and readiness"
```

---

# Task 7: Expose the Fluent `nvidia_query` MCP Surface

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`
- Create: `tests/nvidia/test_query_mcp.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_nvidia_runtime_integration.py` if present in the current branch surface tests.
- Create: `tests/nvidia/test_platform_security_invariants.py`

**Interfaces:**
- Public MCP call:

```python
nvidia_query(
    input: str,
    model: str | None = None,
) -> dict[str, object]
```

- Public review PREPARE uses `model="<alias>"`.
- Public NVIDIA tools become:
  - `nvidia_query`
  - `nvidia_review`
  - `nvidia_get_review`

- [ ] **Step 1: Write RED MCP contract tests**

Assert `nvidia_query` registration and schema.

Test default:

```python
result = await server.nvidia_query(input="hello")
assert result["model"] == "deepseek-v4-pro"
```

with injected fake service.

Test explicit alias:

```python
result = await server.nvidia_query(input="hello", model="lightning")
assert result["model"] == "lightning"
```

Test unknown alias returns/raises the safe typed local error without provider invocation.

- [ ] **Step 2: Add RED surface-count test**

The current live lineage had seven tools. With `nvidia_query`, expected tool names become exactly:

```python
{
    "list_roots",
    "list_directory",
    "search",
    "fetch",
    "wolfram_query",
    "nvidia_query",
    "nvidia_review",
    "nvidia_get_review",
}
```

This plan does not call Wolfram; this test only verifies its existing registration remains present.

- [ ] **Step 3: Run RED**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_query_mcp.py `
  tests/test_server.py
```

- [ ] **Step 4: Add one narrow MCP function**

`server.py` should delegate directly to one query service instance. Do not put request construction, credential logic, or error classification into `server.py`.

- [ ] **Step 5: Add platform security invariants**

Tests must prove:
- no `model_id` arbitrary provider string on `nvidia_query`;
- no temperature/top_p/max_tokens/seed MCP parameters;
- no retry/fallback parameter;
- no endpoint override;
- no API key parameter;
- query local validation does not touch credential loader;
- review approval still cannot accept model selector;
- public tool schemas contain no secret-bearing fields.

- [ ] **Step 6: Run complete server/NVIDIA surface regression**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_query_mcp.py `
  tests/nvidia/test_platform_security_invariants.py `
  tests/nvidia/test_review_mcp.py `
  tests/test_server.py `
  tests/test_nvidia_runtime_integration.py
```

If `tests/test_nvidia_runtime_integration.py` does not exist on this branch, omit only that path and document the absence in the task receipt.

- [ ] **Step 7: Commit**

```powershell
git add `
  src/byte_mcp/server.py `
  src/byte_mcp/nvidia/__init__.py `
  tests/nvidia/test_query_mcp.py `
  tests/nvidia/test_platform_security_invariants.py `
  tests/test_server.py `
  tests/test_nvidia_runtime_integration.py

git commit -m "feat: expose governed NVIDIA query tool"
```

Again, stage only paths that exist and changed.

---

# Task 8: Add Model Maturity and Deterministic Offline Qualification Artifacts

**Files:**
- Modify: `src/byte_mcp/nvidia/models.py`
- Modify: `src/byte_mcp/nvidia/qualification.py`
- Modify: `tests/nvidia/test_models.py`
- Modify: `tests/nvidia/test_qualification.py`
- Create: `qualification/nvidia/README.md`
- Create: `qualification/nvidia/model-registry.json`
- Create: `qualification/nvidia/offline-receipts/.gitkeep`
- Create: `qualification/nvidia/live-canary-receipts/.gitkeep`

**Interfaces:**
- Produces repository-auditable model state without network access.

- [ ] **Step 1: Write RED registry-artifact parity test**

Generate the runtime registry projection in-memory and compare it against `qualification/nvidia/model-registry.json`.

The artifact contains for each alias:
- provider model ID;
- query enabled;
- review enabled;
- query qualification;
- review qualification;
- profile identity/version if implemented.

It must not contain API keys, endpoint auth headers, or review evidence.

- [ ] **Step 2: Write RED offline qualification tests**

`qualify_nvidia_offline()` must fail if:
- duplicate alias/provider identity;
- missing query/review profile for an enabled surface;
- default alias absent;
- registry artifact differs from runtime registry;
- request construction is nondeterministic;
- credential-like sentinel appears in serialized artifacts.

It must report pass without network access.

- [ ] **Step 3: Run RED**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_models.py `
  tests/nvidia/test_qualification.py
```

- [ ] **Step 4: Mark query profiles `OFFLINE_QUALIFIED` only after query tests are green**

Update both query qualification values from `REGISTERED` to `OFFLINE_QUALIFIED`.

Do not mark either model `QUERY_LIVE_QUALIFIED`; no query live canary has been authorized.

Keep:
- Lightning review = `REVIEW_LIVE_QUALIFIED` from the completed N03 review path.
- DeepSeek review = `OFFLINE_QUALIFIED` until a future successful live review.

- [ ] **Step 5: Create qualification documentation/artifact**

`qualification/nvidia/README.md` must explicitly state:
- artifacts contain no secrets;
- offline qualification performs zero provider calls;
- live canaries require separate explicit authorization;
- runtime promotion itself performs zero provider calls;
- query and review live qualification are separate.

- [ ] **Step 6: Run GREEN**

```powershell
& $Python -m pytest -q `
  tests/nvidia/test_models.py `
  tests/nvidia/test_qualification.py
```

- [ ] **Step 7: Commit**

```powershell
git add `
  src/byte_mcp/nvidia/models.py `
  src/byte_mcp/nvidia/qualification.py `
  tests/nvidia/test_models.py `
  tests/nvidia/test_qualification.py `
  qualification/nvidia

git commit -m "feat: add NVIDIA offline qualification registry"
```

---

# Task 9: Document the NVIDIA Failure Map

**Files:**
- Create or modify: `FAILURE_MAP.md`
- Modify tests only if documentation invariants are already enforced in the repository.

**Interfaces:**
- Produces living operational failure documentation required by the design.

- [ ] **Step 1: Inspect existing root failure map**

If `FAILURE_MAP.md` exists, add a bounded NVIDIA Governed Platform section. If absent, create it and state its repository-wide purpose before the NVIDIA section.

- [ ] **Step 2: Document each required NVIDIA failure boundary**

For each row/section include:
- symptom;
- likely cause;
- first diagnostic;
- propagation;
- safe recovery;
- data/evidence risk;
- do-not action;
- related test.

Required boundaries:
1. missing credential;
2. malformed credential;
3. authentication rejected;
4. rate limited;
5. provider 4xx;
6. provider 5xx;
7. DNS/TLS/socket failure;
8. timeout;
9. malformed JSON;
10. unexpected response schema;
11. empty completion;
12. oversized response;
13. invalid alias;
14. surface-disabled model;
15. registry/artifact mismatch;
16. accidental runtime model discovery;
17. retry-policy regression;
18. fallback regression;
19. query audit write failure;
20. review evidence corruption;
21. review manifest mismatch;
22. ambiguous post-provider-start review outcome.

- [ ] **Step 3: Link each failure boundary to concrete tests**

Use actual test node/file names created in Tasks 1-8. Do not write "add tests" or generic placeholders.

- [ ] **Step 4: Verify documentation diff**

```powershell
git diff --check
```

- [ ] **Step 5: Commit**

```powershell
git add FAILURE_MAP.md
git commit -m "docs: map NVIDIA platform failure boundaries"
```

---

# Task 10: Full Offline Differential Qualification and N05 Feature Commit Boundary

**Files:**
- No new production behavior unless qualification reveals a bug.
- Qualification receipt should be saved under:
  `qualification/nvidia/offline-receipts/`
- Do not create a receipt claiming PASS until commands have actually passed.

**Interfaces:**
- Consumes all Tasks 1-9.
- Produces provider-free offline qualification evidence suitable for runtime-promotion planning.

- [ ] **Step 1: Verify provider/runtime boundary**

```powershell
Remove-Item Env:NVIDIA_API_KEY -ErrorAction SilentlyContinue
git status --porcelain
git branch --show-current
```

Expected branch:

```text
feat/nvidia-provider-n05-governed-platform
```

No live runtime command is run.

- [ ] **Step 2: Run NVIDIA unit/contract regression**

```powershell
& $Python -m pytest -q -p no:cacheprovider `
  tests/nvidia `
  tests/test_server.py
```

Expected: PASS.

- [ ] **Step 3: Run compile and Ruff check**

```powershell
& $Python -m compileall -q src
& $Python -m ruff check --no-cache src tests
```

Expected: PASS.

- [ ] **Step 4: Run Ruff format on N05-owned changed Python files only**

Build the list from:

```powershell
git diff --name-only <PLAN_COMMIT>...HEAD
```

Filter `.py` paths under `src/` and `tests/`, then:

```powershell
& $Python -m ruff format --check @ChangedPythonFiles
```

Expected: PASS.

Do not autoformat unrelated baseline files.

- [ ] **Step 5: Run provider-free offline qualification API**

Example:

```powershell
& $Python -c @'
from byte_mcp.nvidia.qualification import qualify_nvidia_offline
result = qualify_nvidia_offline()
assert result["status"] == "PASS", result
print(result)
'@
```

Expected:
- no network;
- no credential required;
- registry/artifact parity;
- deterministic request builders;
- expected MCP surfaces;
- zero provider calls.

- [ ] **Step 6: Differential full-suite baseline**

Create a temporary detached worktree at the implementation-plan commit:

```text
<PLAN_COMMIT>
```

Run identical full pytest commands in base and candidate using the shared dev venv, external `--basetemp`, `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.

Compare sorted unique `FAILED <node id>` sets.

Qualification rule:

```text
candidate new full-suite failures = 0
```

Do not patch unrelated OX-era failures simply to make the full suite green.

- [ ] **Step 7: Differential repository-wide format debt**

Run repository-wide `ruff format --check src tests` on both frozen base and candidate, parse unformatted file paths, and require:

```text
candidate_unformatted - base_unformatted = {}
```

In addition, N05-owned Python files must have passed Step 4.

- [ ] **Step 8: Verify forbidden implementation patterns by source inspection/tests**

Required assertions:
- runtime NVIDIA path contains no `/v1/models` invocation;
- no retry loop/backoff/retry decorator in query transport;
- no fallback model sequence;
- MCP query schema has no endpoint, credential, sampling, or retry override;
- review approval/transmission have no model selector;
- provider calls remain mocked in all offline tests.

- [ ] **Step 9: Save actual offline receipt**

Only after all prior steps pass, create a receipt such as:

```text
qualification/nvidia/offline-receipts/2026-09-15-n05-governed-platform.txt
```

with actual commit SHA and counts:

```text
N05_BASE=<PLAN_COMMIT>
N05_COMMIT=<actual HEAD>
NVIDIA_TESTS=PASS
COMPILE=PASS
RUFF_CHECK=PASS
N05_SCOPED_FORMAT=PASS
FULL_SUITE_DIFFERENTIAL=PASS
N05_NEW_FULL_SUITE_FAILURES=0
FORMAT_BASELINE_DIFFERENTIAL=PASS
N05_NEW_UNFORMATTED_FILES=0
OFFLINE_QUALIFICATION=PASS
NVIDIA_PROVIDER_CALLS=0
OTHER_PROVIDER_CALLS=0
LIVE_RUNTIME_MUTATIONS=0
PUSH=NO
MERGE=NO
```

The receipt itself is a final documentation commit after all verification evidence exists.

- [ ] **Step 10: Commit the qualification receipt**

```powershell
git add qualification/nvidia/offline-receipts/<actual-receipt-name>
git commit -m "docs: record NVIDIA platform offline qualification"
```

- [ ] **Step 11: Verify clean branch state**

```powershell
git status --porcelain
git log --oneline --decorate -10
```

Expected: clean worktree.

---

# Task 11: Prepare Runtime Promotion — Provider-Free Only

This task is deliberately a planning/verification boundary. It does **not** perform a live NVIDIA call.

**Files:**
- No source changes expected.
- Optional promotion receipt under `qualification/nvidia/` only after actual promotion.

**Interfaces:**
- Consumes: N05 offline-qualified commit.
- Produces: exact runtime promotion procedure for separate explicit execution.

- [ ] **Step 1: Verify current live runtime identity before touching it**

Expected predecessor at the time this plan was written:

```text
fb87e39d24ee2e74f648da0495059f147f30fb89
```

Do not assume it is still current; inspect before promotion.

- [ ] **Step 2: Confirm promotion topology**

The N05 branch descends from:
- N04 qualified commit `f84e38d4...`
- design commit `4e57ad4d...`
- implementation-plan commit `<PLAN_COMMIT>`

Determine whether the live runtime can fast-forward/cherry-pick cleanly from its actual current state.

- [ ] **Step 3: Require explicit user approval before runtime mutation**

No shutdown, task quiesce, worktree mutation, or runtime promotion occurs merely because offline qualification passed.

- [ ] **Step 4: Promotion verification requirements**

When separately authorized:
- stop/quiesce supervisor safely;
- promote exact commit;
- verify clean runtime;
- verify ports 8000/8080;
- verify expected MCP surface now includes `nvidia_query`;
- verify `nvidia_get_review` can still read NVR-000001 and NVR-000002;
- run provider-free smoke tests;
- make zero NVIDIA calls;
- make zero Wolfram/OX calls.

- [ ] **Step 5: Stop before live canary**

After provider-free runtime verification, do not call `nvidia_query` against NVIDIA until a separate explicit live-canary authorization is given.

---

# Task 12: Future Explicit Live Qualification Gates

This task is intentionally **not executable under the current authorization**. It documents the next governed actions after runtime promotion.

## Query live canary

A future explicit authorization must name:
- model alias;
- exact prepared request identity or bounded canary contract;
- exactly one provider request.

After a successful DeepSeek query canary:
- DeepSeek query state may become `QUERY_LIVE_QUALIFIED`.

After a successful Lightning query canary:
- Lightning query state may become `QUERY_LIVE_QUALIFIED`.

## Review live qualification

DeepSeek review remains only `OFFLINE_QUALIFIED` until one separately authorized complete review lifecycle succeeds.

Do not reuse or retransmit NVR-000001 or NVR-000002.

A future review receives a new review ID and exact hash before approval.

---

# Plan Self-Review

## Spec coverage

Covered:
- shared governed core → Tasks 1-3;
- friendly aliases → Tasks 1, 2, 7;
- query path → Tasks 4-7;
- review preservation → Task 2;
- typed errors → Task 3;
- lazy credentials/exactly-once → Task 5;
- lightweight audit → Task 6;
- readiness → Task 6;
- offline qualification → Tasks 8, 10;
- model maturity → Task 8;
- qualification artifacts → Task 8;
- failure map → Task 9;
- differential baseline → Task 10;
- provider-free promotion → Task 11;
- separate live qualification → Task 12;
- no retry/fallback/dynamic discovery → Global Constraints + Tasks 3, 5, 7, 10;
- historical review evidence readability → Task 2 + Task 11.

## Type consistency

Public model selector is consistently named `model` at MCP/service boundaries and uses friendly aliases.

Internal review request construction keeps `model_id` as the exact provider model ID to preserve historical evidence/request semantics.

Query protocol uses `model_alias` internally where ambiguity matters.

## Scope

No OX repair, Wolfram modification, autonomous routing, dynamic model discovery, provider retry, fallback, or live call is part of this plan.

---

# Execution Handoff

Recommended execution in this environment is **inline, task-by-task**, with Nolan running the exact PowerShell/test commands and Byte reviewing every receipt before the next commit. This fits the existing NVIDIA workflow and keeps provider authorization boundaries explicit.

If executing in an agentic coding environment, use a fresh implementation worker per task with review gates between tasks. Do not parallelize tasks that depend on shared registry/service interfaces.
