# Byte-MCP Wolfram LLM Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure, quota-aware `wolfram_query` capability to Byte-MCP using the Wolfram|Alpha LLM API, preserve the existing filesystem and OX trust boundaries, and run a fixed evidence-based qualification campaign before granting Wolfram any broader engineering tool surface.

**Architecture:** Preserve the accepted `FileService` and launcher/tunnel model. Add an isolated `byte_mcp.wolfram` package containing exact domain/settings contracts, outbound data policy, conservative local quota accounting, a fixed Wolfram|Alpha LLM API client, and a fail-isolated service/runtime boundary. The launcher stores the Wolfram AppID with the same Windows user-bound DPAPI mechanism already used for the tunnel credential and injects it only into the Byte-MCP server child process. Phase 1 exposes only `wolfram_query`; `wolfram_review`, `wolfram_continue`, `wolfram_revalidate`, `wolfram_get_review`, the Full Results API, and the local Wolfram Engine remain outside this implementation until qualification evidence justifies a new approved gate.

**Tech Stack:** Python `>=3.12,<3.14`; `mcp[cli]==1.28.1`; `httpx>=0.28.1,<1`; stdlib dataclasses/enums/JSON/SHA-256/threading/atomic file replacement; pytest; ruff; existing PowerShell/Pester launcher; existing Windows and Ubuntu CI.

**Spec:** `docs/superpowers/specs/2026-08-30-wolfram-coengineer-integration-design.md`

## Global Constraints

- One Byte-MCP server only; Wolfram is a separately governed capability inside the existing server, not a second MCP server or tunnel.
- Existing filesystem tools remain `list_roots`, `list_directory`, `search`, and `fetch`; no repository write, shell, registry, process-control, computer-use, unrestricted-path, or generic HTTP authority is introduced.
- Phase 1 exposes exactly one new Wolfram MCP tool: `wolfram_query`.
- The fixed provider route is `https://www.wolframalpha.com/api/v1/llm-api` using HTTP GET.
- Authentication uses `Authorization: Bearer <AppID>` created only inside the Wolfram client; the AppID is never passed as an MCP argument or query-string parameter.
- `input` is required, non-blank, and bounded to 8,000 characters after normalization.
- `max_chars` defaults to 6,800 and is clamped to `250..6800`.
- Each MCP invocation makes at most one provider request; automatic retries are zero.
- Wolfram normal co-engineering calls do not use OX's two-phase human approval gate; Tier A and bounded Tier B calls are permitted by the approved outbound policy.
- Tier C secret-bearing payloads fail before network transmission.
- Machine-specific absolute Windows paths are sanitized before transmission; repository-relative paths may remain.
- OX and Wolfram never communicate directly. The Wolfram subsystem contains no OX client dependency and accepts no raw OX conversation field.
- Local operational audit stores fingerprints/metadata only, never raw Wolfram input, raw Wolfram result, AppID, authorization header, or secret-bearing payload.
- No permanent Wolfram result cache is created.
- Local quota accounting is conservative operational telemetry, not provider billing authority. It reserves an attempt before the network call, so a crash or local audit failure may over-count rather than under-count.
- Initial local soft ceiling is 1,800 reserved attempts per UTC calendar month; provider limits remain authoritative.
- Wolfram being disabled, misconfigured, rate-limited, or unavailable must not prevent Byte-MCP's existing filesystem service from starting or operating.
- Automated tests never use Nolan's AppID or real Wolfram quota.
- Phase 1 qualification uses exactly 30 primary tasks and at most 5 deliberate follow-up calls.
- Qualification results do not automatically register broader MCP tools. Even Profile A requires a separate approved implementation cycle.
- The existing V1.1 accepted release remains frozen; this feature branch is a separately reviewed next-version capability and must not rewrite the V1.1 closeout record.

## Locked Phase 1 File Structure

Create:

```text
src/byte_mcp/wolfram/
├── __init__.py
├── domain.py
├── settings.py
├── policy.py
├── quota.py
├── client.py
├── service.py
├── runtime.py
└── qualification.py

tests/wolfram/
├── __init__.py
├── conftest.py
├── test_domain.py
├── test_settings.py
├── test_policy.py
├── test_quota.py
├── test_client.py
├── test_service.py
├── test_runtime.py
├── test_mcp_surface.py
├── test_security_invariants.py
└── test_qualification.py

qualification/wolfram/
└── llm-api-v1.json

scripts/
├── Setup-Wolfram.ps1
└── wolfram_qualification.py
```

Modify only where required:

```text
pyproject.toml
.gitignore
src/byte_mcp/errors.py
src/byte_mcp/server.py
scripts/Launcher.Common.ps1
scripts/Check.ps1
scripts/mcp_smoke_test.py
tests/test_server.py
tests/launcher/Launcher.Common.Tests.ps1
tests/launcher/Launcher.Runtime.Tests.ps1
README.md
docs/SECURITY.md
CHANGELOG.md
.github/workflows/ci.yml
```

Do not add Wolfram behavior to `src/byte_mcp/service.py`; `FileService` remains focused on local filesystem access.

---

### Task 1: Wolfram domain contracts, settings, errors, dependency, and local-runtime ignore rule

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `src/byte_mcp/errors.py`
- Create: `src/byte_mcp/wolfram/__init__.py`
- Create: `src/byte_mcp/wolfram/domain.py`
- Create: `src/byte_mcp/wolfram/settings.py`
- Create: `tests/wolfram/__init__.py`
- Create: `tests/wolfram/conftest.py`
- Create: `tests/wolfram/test_domain.py`
- Create: `tests/wolfram/test_settings.py`

**Interfaces:**

```python
# src/byte_mcp/wolfram/domain.py
from dataclasses import dataclass
from enum import StrEnum


class WolframAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    MISCONFIGURED = "MISCONFIGURED"


class WolframPurpose(StrEnum):
    COENGINEERING = "COENGINEERING"
    FALLBACK_VALIDATION = "FALLBACK_VALIDATION"


class WolframRouteReason(StrEnum):
    DIRECT_COMPUTATION = "DIRECT_COMPUTATION"
    KNOWLEDGE_LOOKUP = "KNOWLEDGE_LOOKUP"
    VERIFY_BYTE_HYPOTHESIS = "VERIFY_BYTE_HYPOTHESIS"
    GENERATE_TEST_ORACLE = "GENERATE_TEST_ORACLE"
    SEARCH_COUNTEREXAMPLE = "SEARCH_COUNTEREXAMPLE"
    DEBUG_NUMERICAL_BEHAVIOR = "DEBUG_NUMERICAL_BEHAVIOR"
    CODE_COMPREHENSION = "CODE_COMPREHENSION"
    OX_FALLBACK = "OX_FALLBACK"
    OTHER_BOUNDED_REASON = "OTHER_BOUNDED_REASON"


@dataclass(frozen=True, slots=True)
class WolframQueryRequest:
    input: str
    max_chars: int | None = None
    purpose: WolframPurpose = WolframPurpose.COENGINEERING
    route_reason: WolframRouteReason = WolframRouteReason.OTHER_BOUNDED_REASON
    source_finding_id: str | None = None


@dataclass(frozen=True, slots=True)
class WolframClientResult:
    text: str
    result_url: str | None
    response_chars: int
    response_at_limit: bool
```

`WolframQueryRequest.__post_init__()` rejects blank input; requires `purpose=FALLBACK_VALIDATION` plus non-blank `source_finding_id` for `route_reason=OX_FALLBACK`; rejects `source_finding_id` on all other routes. Input-size and `max_chars` policy are applied later by settings/policy so there is one mechanical bounds implementation.

`WolframSettings` exposes:

```python
@dataclass(frozen=True, slots=True, repr=False)
class WolframSettings:
    repo_root: Path
    usage_file: Path
    app_id: str | None
    endpoint: str = "https://www.wolframalpha.com/api/v1/llm-api"
    max_input_chars: int = 8_000
    min_response_chars: int = 250
    default_max_chars: int = 6_800
    max_response_chars: int = 6_800
    soft_monthly_limit: int = 1_800
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0

    @classmethod
    def load(cls, repo_root: Path) -> "WolframSettings": ...

    def apply_max_chars(self, requested: int | None) -> int: ...
```

- [ ] **Step 1: Write RED settings tests**

```python
from pathlib import Path

import pytest

from byte_mcp.wolfram.settings import WolframSettings


def test_missing_appid_disables_only_wolfram(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert settings.app_id is None
    assert settings.endpoint == "https://www.wolframalpha.com/api/v1/llm-api"
    assert settings.max_input_chars == 8_000
    assert settings.default_max_chars == 6_800
    assert settings.max_response_chars == 6_800
    assert settings.soft_monthly_limit == 1_800


def test_settings_repr_never_contains_appid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WOLFRAM_APP_ID", "SENTINEL-WOLFRAM-SECRET")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert "SENTINEL-WOLFRAM-SECRET" not in repr(settings)
    assert "app_id_configured=True" in repr(settings)


def test_max_chars_is_clamped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    settings = WolframSettings.load(tmp_path)
    assert settings.apply_max_chars(None) == 6800
    assert settings.apply_max_chars(1) == 250
    assert settings.apply_max_chars(9000) == 6800
```

Add explicit tests that `BYTE_MCP_WOLFRAM_ENDPOINT` is ignored/not supported, blank AppIDs normalize to `None`, `BYTE_MCP_WOLFRAM_SOFT_LIMIT=1801` raises `WolframConfigurationError`, and values `1..1800` are accepted.

- [ ] **Step 2: Write RED domain tests**

```python
import pytest

from byte_mcp.wolfram.domain import (
    WolframPurpose,
    WolframQueryRequest,
    WolframRouteReason,
)


def test_ox_fallback_requires_fallback_purpose_and_local_finding_id() -> None:
    with pytest.raises(ValueError):
        WolframQueryRequest(input="check invariant", route_reason=WolframRouteReason.OX_FALLBACK)

    request = WolframQueryRequest(
        input="check invariant",
        purpose=WolframPurpose.FALLBACK_VALIDATION,
        route_reason=WolframRouteReason.OX_FALLBACK,
        source_finding_id="F-local-1",
    )
    assert request.source_finding_id == "F-local-1"


def test_non_fallback_route_rejects_source_finding_id() -> None:
    with pytest.raises(ValueError):
        WolframQueryRequest(input="2+2", source_finding_id="F-local-1")
```

Also prove blank/whitespace input is rejected.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/wolfram/test_settings.py tests/wolfram/test_domain.py -v
```

Expected: import failures because `byte_mcp.wolfram` does not yet exist.

- [ ] **Step 4: Add the only new Python dependency and ignore direct-development runtime state**

Add to `[project].dependencies`:

```toml
"httpx>=0.28.1,<1",
```

Add to `.gitignore`:

```gitignore
# Wolfram local operational state
data/wolfram-usage.json*
```

Do not add a Wolfram SDK, generic model SDK, retry library, ORM, vector store, or database server.

- [ ] **Step 5: Add exact Wolfram errors**

Append to `src/byte_mcp/errors.py`:

```python
class WolframError(ByteMCPError):
    """Base error for expected Wolfram capability failures."""

class WolframUnavailableError(WolframError):
    """Raised when the Wolfram capability is disabled or unavailable."""

class WolframConfigurationError(WolframError):
    """Raised when Wolfram configuration is invalid."""

class WolframPolicyError(WolframError):
    """Raised when outbound content violates the Wolfram data policy."""

class WolframQuotaError(WolframError):
    """Raised when the local conservative Wolfram budget is exhausted."""

class WolframAuthenticationError(WolframError):
    """Raised when Wolfram rejects the AppID."""

class WolframRequestError(WolframError):
    """Raised when the request itself is invalid."""

class WolframUninterpretableError(WolframError):
    """Raised when Wolfram cannot interpret the input."""

class WolframRateLimitError(WolframError):
    """Raised when Wolfram rate-limits the request."""

class WolframTimeoutError(WolframError):
    """Raised on a bounded provider timeout."""

class WolframTransportError(WolframError):
    """Raised for DNS, TLS, connection, or transport failures."""

class WolframProviderError(WolframError):
    """Raised for Wolfram provider/server failures."""

class WolframProtocolError(WolframError):
    """Raised for malformed or unusable provider responses."""
```

- [ ] **Step 6: Implement domain/settings exactly**

`WolframSettings.load()` reads only `WOLFRAM_APP_ID`, `BYTE_MCP_WOLFRAM_USAGE_FILE`, and `BYTE_MCP_WOLFRAM_SOFT_LIMIT`. The usage file defaults to `<repo_root>/data/wolfram-usage.json` for direct development. Strip blank AppIDs to `None`. `repr()` reports `app_id_configured=True/False` only. Use the fixed endpoint constant in the dataclass; do not read it from environment.

- [ ] **Step 7: Create shared test fixture**

```python
# tests/wolfram/conftest.py
from pathlib import Path
import pytest
from byte_mcp.wolfram.settings import WolframSettings


@pytest.fixture
def wolfram_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WolframSettings:
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-WOLFRAM-APPID")
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("BYTE_MCP_WOLFRAM_SOFT_LIMIT", "10")
    return WolframSettings.load(tmp_path)
```

- [ ] **Step 8: Run GREEN and commit**

```bash
python -m compileall -q src tests
python -m ruff check src/byte_mcp/wolfram src/byte_mcp/errors.py tests/wolfram
python -m pytest tests/wolfram/test_settings.py tests/wolfram/test_domain.py -v
python -m pip check
git add pyproject.toml .gitignore src/byte_mcp/errors.py src/byte_mcp/wolfram tests/wolfram
git commit -m "feat: add Wolfram Phase 1 contracts"
```

---

### Task 2: Outbound data policy and path sanitization

**Files:**
- Create: `src/byte_mcp/wolfram/policy.py`
- Create: `tests/wolfram/test_policy.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class PreparedWolframInput:
    text: str
    sha256: str
    original_chars: int
    transmitted_chars: int
    paths_sanitized: int


class WolframOutboundPolicy:
    def __init__(self, max_input_chars: int, user_profile: Path | None = None) -> None: ...
    def prepare(self, input_text: str) -> PreparedWolframInput: ...
```

Secret detection raises `WolframPolicyError` before quota reservation or transport.

- [ ] **Step 1: Write RED secret-denial tests**

```python
import pytest
from byte_mcp.errors import WolframPolicyError
from byte_mcp.wolfram.policy import WolframOutboundPolicy


@pytest.mark.parametrize(
    "payload",
    [
        "OPENAI_API_KEY=sk-test-secret",
        "AI_GATEWAY_API_KEY=ox-secret",
        "WOLFRAM_APP_ID=APP-SECRET",
        "CONTROL_PLANE_API_KEY=tunnel-secret",
        "Authorization: Bearer secret-token",
        "-----BEGIN PRIVATE KEY-----",
        "password=hunter2",
        "postgresql://user:secret@localhost/db?password=secret",
    ],
)
def test_secret_like_payload_is_denied(payload: str) -> None:
    with pytest.raises(WolframPolicyError, match="sensitive"):
        WolframOutboundPolicy(max_input_chars=8000).prepare(payload)
```

- [ ] **Step 2: Write RED path-sanitization tests**

```python
from pathlib import Path
from byte_mcp.wolfram.policy import WolframOutboundPolicy


def test_windows_absolute_paths_are_replaced() -> None:
    prepared = WolframOutboundPolicy(
        max_input_chars=8000,
        user_profile=Path(r"C:\Users\test-user"),
    ).prepare(r"Failure in C:\Users\test-user\AIProjects\tidy\src\tidy\core.py line 12")
    assert r"C:\Users\test-user" not in prepared.text
    assert "<local-path>" in prepared.text
    assert prepared.paths_sanitized == 1


def test_repository_relative_path_is_preserved() -> None:
    prepared = WolframOutboundPolicy(max_input_chars=8000).prepare("Failure in src/tidy/core.py")
    assert "src/tidy/core.py" in prepared.text
```

- [ ] **Step 3: Write RED normalization/bound tests**

Test that input is stripped, CRLF is normalized to LF, NUL raises `WolframPolicyError`, and normalized input of 8,001 chars raises `WolframPolicyError`. Do not silently truncate engineering input.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/wolfram/test_policy.py -v
```

- [ ] **Step 5: Implement deny-first policy**

Compile case-insensitive patterns for explicit credential names, bearer headers, private-key headers, password/pwd assignments, common token prefixes, and credential-bearing URL/query forms. Run secret detection before path replacement. Replace absolute Windows drive/UNC paths with `<local-path>` while preserving surrounding diagnostics. Hash the final transmitted UTF-8 text with SHA-256.

Do not attempt to infer whether arbitrary source code is proprietary or personal. Byte selects bounded context; the policy mechanically rejects secret-like data and machine-identifying paths.

- [ ] **Step 6: Run GREEN and commit**

```bash
python -m ruff check src/byte_mcp/wolfram/policy.py tests/wolfram/test_policy.py
python -m pytest tests/wolfram/test_policy.py -v
git add src/byte_mcp/wolfram/policy.py tests/wolfram/test_policy.py
git commit -m "feat: enforce Wolfram outbound policy"
```

---

### Task 3: Conservative local quota ledger

**Files:**
- Create: `src/byte_mcp/wolfram/quota.py`
- Create: `tests/wolfram/test_quota.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class QuotaReservation:
    period_utc: str
    period_count: int
    soft_limit: int


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    period_utc: str
    period_count: int
    soft_limit: int
    remaining: int


class WolframQuotaLedger:
    def __init__(self, path: Path, soft_limit: int) -> None: ...
    def reserve_attempt(self, now: datetime | None = None) -> QuotaReservation: ...
    def snapshot(self, now: datetime | None = None) -> QuotaSnapshot: ...
```

A reservation increments before network transmission and is never decremented after provider/local failure.

- [ ] **Step 1: Write RED quota tests**

```python
from datetime import UTC, datetime
import pytest
from byte_mcp.errors import WolframQuotaError
from byte_mcp.wolfram.quota import WolframQuotaLedger


def test_quota_reserves_before_outbound_attempt(tmp_path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=2)
    now = datetime(2026, 8, 30, tzinfo=UTC)
    assert ledger.reserve_attempt(now).period_count == 1
    assert ledger.reserve_attempt(now).period_count == 2
    with pytest.raises(WolframQuotaError):
        ledger.reserve_attempt(now)
```

Add exact tests for UTC month rollover, malformed JSON/schema fail-closed, atomic temp-file cleanup, `remaining`, and two threads reserving concurrently without duplicate counts.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/wolfram/test_quota.py -v
```

- [ ] **Step 3: Implement schema and atomic persistence**

Persist only:

```json
{
  "schema_version": 1,
  "period_utc": "2026-08",
  "attempt_count": 12
}
```

Use an in-process lock, same-directory temporary file, `flush()`, `os.fsync()`, and `os.replace()`. Never store query text, response content, result URLs, AppID, or error bodies.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m ruff check src/byte_mcp/wolfram/quota.py tests/wolfram/test_quota.py
python -m pytest tests/wolfram/test_quota.py -v
git add src/byte_mcp/wolfram/quota.py tests/wolfram/test_quota.py
git commit -m "feat: add Wolfram quota ledger"
```

---

### Task 4: Fixed Wolfram|Alpha LLM API client

**Files:**
- Create: `src/byte_mcp/wolfram/client.py`
- Create: `tests/wolfram/test_client.py`

**Consumes:** `WolframSettings`, `WolframClientResult`, Wolfram error subclasses.

**Produces:**

```python
class WolframLLMClient:
    def __init__(
        self,
        settings: WolframSettings,
        transport: httpx.BaseTransport | None = None,
    ) -> None: ...

    def query(self, input_text: str, max_chars: int) -> WolframClientResult: ...
```

No other module sends Wolfram HTTP traffic.

- [ ] **Step 1: Write RED exact request-shape test with `httpx.MockTransport`**

```python
import httpx
from byte_mcp.wolfram.client import WolframLLMClient


def test_client_uses_fixed_endpoint_bearer_auth_and_input_only(wolfram_settings) -> None:
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            text=(
                'Query:\n"2+2"\n\nResult:\n4\n\n'
                'Wolfram|Alpha website result for "2+2":\n'
                'https://www.wolframalpha.com/input?i=2%2B2'
            ),
        )
    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    result = client.query("2+2", 6800)
    request = seen["request"]
    assert request.method == "GET"
    assert str(request.url).startswith("https://www.wolframalpha.com/api/v1/llm-api?")
    assert request.url.params["input"] == "2+2"
    assert request.url.params["maxchars"] == "6800"
    assert "appid" not in request.url.params
    assert request.headers["Authorization"] == "Bearer TEST-WOLFRAM-APPID"
    assert result.result_url.startswith("https://www.wolframalpha.com/input?")
```

- [ ] **Step 2: Write RED one-request/no-retry test**

Mock a `503`; assert the transport handler is invoked exactly once and `WolframProviderError` is raised.

- [ ] **Step 3: Write RED exact error mapping tests**

```text
400 -> WolframRequestError
403 -> WolframAuthenticationError
429 -> WolframRateLimitError
501 -> WolframUninterpretableError
5xx -> WolframProviderError
httpx.ConnectError / ConnectTimeout -> WolframTransportError
httpx.ReadTimeout -> WolframTimeoutError
other httpx.TransportError -> WolframTransportError
```

For 501, permit a bounded safe suggested-input excerpt in the exception message, capped at 500 characters. Error strings must never contain AppID or authorization header.

- [ ] **Step 4: Write RED response parsing tests**

A `200` response must contain non-empty decoded text. Extract the final line matching `https://www.wolframalpha.com/input?...` as `result_url`; otherwise return `result_url=None`. Set `response_chars=len(text)` and `response_at_limit=(len(text) >= max_chars)`. Keep result text only in the in-memory returned object.

- [ ] **Step 5: Run RED**

```bash
python -m pytest tests/wolfram/test_client.py -v
```

- [ ] **Step 6: Implement bounded non-streaming GET**

Use:

```python
httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
```

The client owns endpoint and headers. Set `follow_redirects=False`. Do not create retry middleware. Expose only `input` and `maxchars` query parameters; do not expose host, URL, assumptions, location, Full Results parameters, or arbitrary headers.

- [ ] **Step 7: Run GREEN and commit**

```bash
python -m ruff check src/byte_mcp/wolfram/client.py tests/wolfram/test_client.py
python -m pytest tests/wolfram/test_client.py -v
git add src/byte_mcp/wolfram/client.py tests/wolfram/test_client.py
git commit -m "feat: add Wolfram LLM API client"
```

---

### Task 5: Wolfram service, metadata-only audit, and fail-isolated runtime

**Files:**
- Create: `src/byte_mcp/wolfram/service.py`
- Create: `src/byte_mcp/wolfram/runtime.py`
- Create: `tests/wolfram/test_service.py`
- Create: `tests/wolfram/test_runtime.py`

**Consumes:** `WolframQueryRequest`, `PreparedWolframInput`, `QuotaReservation`, `WolframClientResult`, `AuditLog`.

**Produces:**

```python
class WolframService:
    def __init__(
        self,
        settings: WolframSettings,
        audit: AuditLog,
        policy: WolframOutboundPolicy,
        quota: WolframQuotaLedger,
        client: WolframLLMClient,
    ) -> None: ...

    def query(self, request: WolframQueryRequest) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class WolframRuntime:
    availability: WolframAvailability
    service: WolframService | None
    safe_error: str | None

    @classmethod
    def load(cls, repo_root: Path, audit: AuditLog) -> "WolframRuntime": ...
```

- [ ] **Step 1: Write RED happy-path service test**

With fake policy/quota/client, assert this exact order:

```text
validate request dataclass
apply max_chars
prepare/sanitize payload
reserve quota
persist metadata-only transmission intent
perform one client call
persist metadata-only success event
return public result
```

Expected public shape:

```python
{
    "status": "success",
    "provider": "Wolfram|Alpha",
    "purpose": "COENGINEERING",
    "route_reason": "DIRECT_COMPUTATION",
    "result": "...",
    "result_url": "https://www.wolframalpha.com/input?...",
    "response_chars": 123,
    "response_at_limit": False,
    "usage": {
        "local_period_utc": "2026-08",
        "local_period_count": 1,
        "soft_limit": 10,
    },
}
```

The generated internal `request_id` is a random UUID4 string used in audit correlation only and is not returned by Phase 1 MCP output.

- [ ] **Step 2: Write RED audit privacy test**

Use sentinels in query/result/AppID. Read JSONL and prove all are absent. Audit fields are limited to:

```text
action=wolfram_query
outcome
provider=wolfram
purpose
route_reason
request_id
input_sha256
input_chars
transmitted_chars
paths_sanitized
max_chars_applied
period_utc
period_count
response_chars
duration_ms
error_type
source_finding_id (local identifier only, only for OX_FALLBACK)
```

- [ ] **Step 3: Write RED policy-before-quota/network test**

A secret-bearing payload raises `WolframPolicyError`; fake quota and fake client each report zero calls.

- [ ] **Step 4: Write RED quota-before-network test**

An exhausted local budget raises `WolframQuotaError`; fake client receives zero calls.

- [ ] **Step 5: Write RED fail-isolated runtime tests**

No `WOLFRAM_APP_ID` -> `WolframRuntime(availability=DISABLED, service=None, safe_error=None)`. An invalid soft-limit setting -> `MISCONFIGURED`, `service=None`, bounded `safe_error` with no secret. In either state ordinary core `Settings` and `FileService` remain constructible.

- [ ] **Step 6: Run RED**

```bash
python -m pytest tests/wolfram/test_service.py tests/wolfram/test_runtime.py -v
```

- [ ] **Step 7: Implement service routing and audit ordering**

Generate UUID4 `request_id`. Call `settings.apply_max_chars()`, policy, quota, then `audit.record(... outcome="transmitting" ...)` before HTTP. If transmission-intent audit fails, abort before network; the already-reserved quota remains conservatively consumed. Perform exactly one `client.query()`. On typed provider failure, write metadata-only failure audit and re-raise. On success, write metadata-only success audit then return the public dict. If final success audit fails after a provider success, raise `AuditError`, do not return the result, and never retry the provider call.

`OX_FALLBACK` linkage is only `source_finding_id`; the service has no OX service/client import.

- [ ] **Step 8: Implement runtime construction**

`WolframRuntime.load()` loads `WolframSettings`; returns `DISABLED` if AppID absent; returns `MISCONFIGURED` for `WolframConfigurationError`; otherwise creates policy with `settings.max_input_chars`, quota ledger, client, and service and returns `AVAILABLE`. It performs zero provider calls during construction.

- [ ] **Step 9: Run GREEN and commit**

```bash
python -m ruff check src/byte_mcp/wolfram/service.py src/byte_mcp/wolfram/runtime.py tests/wolfram
python -m pytest tests/wolfram/test_service.py tests/wolfram/test_runtime.py -v
git add src/byte_mcp/wolfram/service.py src/byte_mcp/wolfram/runtime.py tests/wolfram
git commit -m "feat: orchestrate Wolfram queries safely"
```

---

### Task 6: Expose `wolfram_query` through FastMCP without weakening startup

**Files:**
- Modify: `src/byte_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/wolfram/test_mcp_surface.py`
- Modify: `scripts/mcp_smoke_test.py`

**Consumes:** `WolframRuntime`, `WolframQueryRequest`, enums from Task 1.

**Produces:**

```python
WOLFRAM_EXTERNAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


def wolfram_runtime() -> WolframRuntime: ...


@mcp.tool(annotations=WOLFRAM_EXTERNAL)
def wolfram_query(
    input: str,
    max_chars: int | None = None,
    purpose: str = "COENGINEERING",
    route_reason: str = "OTHER_BOUNDED_REASON",
    source_finding_id: str | None = None,
) -> dict[str, object]: ...
```

`wolfram_query` converts `purpose` and `route_reason` to the enums; invalid enum strings become `WolframRequestError` with allowed values and no provider call.

- [ ] **Step 1: Write RED MCP catalog/annotation test**

Assert `wolfram_query` exists and these do not:

```text
wolfram_review
wolfram_continue
wolfram_revalidate
wolfram_get_review
wolfram_compute
http_request
fetch_url
```

Assert the annotation object has `readOnlyHint=True`, `destructiveHint=False`, `idempotentHint=False`, `openWorldHint=True`.

- [ ] **Step 2: Write RED startup-isolation test**

Keep existing proof that `service()` is initialized before `mcp.run()`. Add a spy proving `wolfram_runtime()` is not called from `main()`. With `WOLFRAM_APP_ID` absent, `main()` still reaches `mcp.run()`.

- [ ] **Step 3: Write RED argument-surface test**

Inspect FastMCP tool schema; allowed names are exactly `input`, `max_chars`, `purpose`, `route_reason`, `source_finding_id`. Assert no `appid`, `url`, `endpoint`, `headers`, `method`, `assumption`, or arbitrary-options field exists.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/test_server.py tests/wolfram/test_mcp_surface.py -v
```

- [ ] **Step 5: Implement lazy runtime using existing audit file**

Create a module-level `_wolfram_runtime: WolframRuntime | None = None`. On first call construct `AuditLog(SETTINGS.audit_file)` and `WolframRuntime.load(SETTINGS.repo_root, audit)`. If runtime is `DISABLED` or `MISCONFIGURED`, `wolfram_query` raises `WolframUnavailableError`/`WolframConfigurationError` without touching core FileService state.

- [ ] **Step 6: Update protocol smoke discovery**

Add only `wolfram_query` to `EXPECTED_TOOLS`. Ordinary filesystem smoke must not invoke it or require an AppID; discovery alone proves registration.

- [ ] **Step 7: Run GREEN + legacy regression and commit**

```bash
python -m compileall -q src tests scripts/mcp_smoke_test.py
python -m ruff check .
python -m pytest tests/test_server.py tests/wolfram/test_mcp_surface.py -v
python -m pytest
python -m pip check
git add src/byte_mcp/server.py tests/test_server.py tests/wolfram/test_mcp_surface.py scripts/mcp_smoke_test.py
git commit -m "feat: expose bounded Wolfram query tool"
```

---

### Task 7: Windows DPAPI Wolfram credential setup and child-only injection

**Files:**
- Modify: `scripts/Launcher.Common.ps1`
- Create: `scripts/Setup-Wolfram.ps1`
- Modify: `tests/launcher/Launcher.Common.Tests.ps1`
- Modify: `tests/launcher/Launcher.Runtime.Tests.ps1`
- Create: `tests/launcher/Setup-Wolfram.Tests.ps1`

**Interfaces:**
- `Get-ByteMcpLauncherPaths` adds `WolframCredentialFile` and `WolframUsageFile`.
- `Setup-Wolfram.ps1` accepts only `[switch] $ReplaceCredential`.
- Server child receives `WOLFRAM_APP_ID` only when encrypted Wolfram credential exists.
- Parent PowerShell process environment is restored after child creation.

- [ ] **Step 1: Write RED path/config tests**

Add:

```powershell
$paths.WolframCredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\wolfram-appid.dpapi'
$paths.WolframUsageFile | Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
$map = Get-ByteMcpServerEnvironment -UserProfile 'C:\Users\test'
$map.BYTE_MCP_WOLFRAM_USAGE_FILE | Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
$map.Keys | Should -Not -Contain 'WOLFRAM_APP_ID'
```

- [ ] **Step 2: Write RED setup-script contract test**

`Setup-Wolfram.ps1` must load platform before common, expose `ReplaceCredential`, expose no `AppId`/`ApiKey`/`Credential` plaintext parameter, call `Read-Host 'Paste the Wolfram|Alpha LLM API AppID' -AsSecureString`, write only to `WolframCredentialFile`, and round-trip with `Unprotect-ByteMcpCredential`.

- [ ] **Step 3: Write RED optional injection/restoration tests**

For both `Start-LauncherServerProcess` and `Start-LauncherForegroundServer`:

- no credential file -> child does not observe `WOLFRAM_APP_ID` even if parent had an unrelated value;
- mocked DPAPI credential -> child observes `child-wolfram-secret`;
- after `Start-Process` returns, parent environment is restored to its exact prior presence/value.

- [ ] **Step 4: Run RED Pester**

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: new Wolfram launcher assertions fail.

- [ ] **Step 5: Add exact setup script**

```powershell
[CmdletBinding()]
param(
    [switch] $ReplaceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Launcher.Platform.ps1')
. (Join-Path $PSScriptRoot 'Launcher.Common.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
$paths = Get-ByteMcpLauncherPaths -RepoRoot $repoRoot -UserProfile $env:USERPROFILE

Assert-ByteMcpLauncherPrerequisites -Paths $paths -SkipCredentialCheck
Assert-CredentialWriteAllowed -Path $paths.WolframCredentialFile -ReplaceCredential:$ReplaceCredential

$credential = Read-Host 'Paste the Wolfram|Alpha LLM API AppID' -AsSecureString
Protect-ByteMcpCredential -Credential $credential -Path $paths.WolframCredentialFile
$null = Unprotect-ByteMcpCredential -Path $paths.WolframCredentialFile

Write-Host 'PASS: Wolfram AppID setup complete'
```

- [ ] **Step 6: Extend server-child creation without making Wolfram mandatory**

For background and foreground starts:

1. Build existing non-secret server environment map.
2. Snapshot all map keys plus `WOLFRAM_APP_ID` using existing snapshot/restore helpers.
3. If `WolframCredentialFile` exists, decrypt to `SecureString`, convert to plaintext only immediately before `Start-Process`, set process-scope `WOLFRAM_APP_ID`, and set the plaintext local variable to `$null` in `finally`.
4. If file does not exist, remove process-scope `WOLFRAM_APP_ID` before child creation so an unrelated inherited secret cannot silently configure Byte-MCP.
5. Restore parent snapshot in `finally`.

Never add the secret to launcher state, command-line arguments, logs, status output, or `Get-ByteMcpServerEnvironment`.

- [ ] **Step 7: Run GREEN and commit**

```powershell
.\scripts\Check-Launcher.ps1
```

Then:

```bash
git add scripts/Launcher.Common.ps1 scripts/Setup-Wolfram.ps1 tests/launcher
git commit -m "feat: protect Wolfram launcher credential"
```

---

### Task 8: Security invariants and failure injection

**Files:**
- Create: `tests/wolfram/test_security_invariants.py`
- Modify production files only when a failing invariant demonstrates a defect.

**Interfaces:** No new public interface.

- [ ] **Step 1: Add sentinel leakage matrix**

Seed:

```text
SENTINEL-WOLFRAM-APPID
SENTINEL-OX-CONTENT
SENTINEL-PRIVATE-PATH
SENTINEL-QUERY-CONTENT
SENTINEL-RESULT-CONTENT
```

Inspect returned errors, audit JSONL, quota JSON, settings/runtime repr, test-generated logs, and public metadata. AppID/query/result sentinels must never appear in persistent operational files.

- [ ] **Step 2: Add forbidden-transport matrix**

Try to supply/inject localhost, Full Results API, another Wolfram endpoint, arbitrary domain, alternate method, extra headers, and arbitrary query parameters. There must be no supported public field/setter/path that changes the fixed client route.

- [ ] **Step 3: Add no-auto-retry matrix**

For timeout, 429, 500, malformed 200, and transport failure, assert exactly one `httpx.MockTransport` handler invocation and exactly one quota reservation.

- [ ] **Step 4: Add core isolation matrix**

Under `DISABLED`, `MISCONFIGURED`, quota-exhausted, and provider-failing Wolfram states, exercise existing FileService operations with existing fixtures. Results/errors must match legacy behavior.

- [ ] **Step 5: Add OX isolation characterization**

Inspect `WolframQueryRequest` fields and FastMCP schema: only `source_finding_id` may carry an OX-linked local identifier for `OX_FALLBACK`; there are no `ox_prompt`, `ox_response`, `ox_thread`, `ox_messages`, or `provider_context` fields. No `byte_mcp.wolfram` production module imports `byte_mcp.ox`.

- [ ] **Step 6: Run focused security gate and repair from evidence only**

```bash
python -m pytest tests/wolfram/test_security_invariants.py -v
```

Do not weaken assertions to accommodate an implementation defect.

- [ ] **Step 7: Run full repository gate and commit**

```powershell
.\scripts\Check.ps1
```

Only after clean exit:

```bash
git add src tests scripts
git commit -m "test: harden Wolfram Phase 1 boundary"
```

---

### Task 9: Deterministic LLM API qualification fixture, scoring model, and CLI

**Files:**
- Create: `qualification/wolfram/llm-api-v1.json`
- Create: `src/byte_mcp/wolfram/qualification.py`
- Create: `tests/wolfram/test_qualification.py`
- Create: `scripts/wolfram_qualification.py`
- Modify: `scripts/Check.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class QualificationTask:
    task_id: str
    family: str
    prompt: str
    ground_truth: str
    coding_task: bool


@dataclass(frozen=True, slots=True)
class QualificationScore:
    task_id: str
    fixture_sha256: str
    correctness: int
    specificity: int
    evidence_quality: int
    engineering_usefulness: int
    unsupported_claim_discipline: int
    hard_label: str | None = None
    defect_found: bool | None = None
    root_cause_correct: bool | None = None
    location_correct: bool | None = None
    fix_correct: bool | None = None
    tests_useful: bool | None = None
    invented_facts: bool | None = None
    byte_baseline_correct: bool | None = None
    follow_up: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class QualificationSummary:
    primary_task_count: int
    follow_up_count: int
    overall_average: float
    family_averages: dict[str, float]
    coding_root_cause_correctness: float | None
    unsupported_or_invented_claim_rate: float
    classification_counts: dict[str, int]
    computational_core_average: float
    computational_family_pass_count: int
    improved_families: tuple[str, ...]
    profile: str
```

Functions:

```python
def load_campaign(path: Path) -> tuple[QualificationTask, ...]: ...
def campaign_sha256(path: Path) -> str: ...
def score_total(score: QualificationScore) -> int: ...
def classify_total(total: int) -> str: ...
def append_score(path: Path, score: QualificationScore) -> None: ...
def load_scores(path: Path) -> tuple[QualificationScore, ...]: ...
def summarize(
    tasks: Sequence[QualificationTask],
    scores: Sequence[QualificationScore],
    improved_families: Sequence[str],
) -> QualificationSummary: ...
```

Scoring validation: every dimension integer `0..4`; note <=500 chars; hard label is `None` or one of `UNINTERPRETABLE`, `API_ERROR`, `TIMEOUT`, `UNSUPPORTED_CLAIM`, `FACTUALLY_WRONG`; task ID must exist in the supplied campaign; fixture hash must match current campaign; at most one primary score per task; at most five follow-up records total.

CLI contract:

```text
python scripts/wolfram_qualification.py list
    --campaign qualification/wolfram/llm-api-v1.json

python scripts/wolfram_qualification.py record
    --campaign qualification/wolfram/llm-api-v1.json
    --scores-file <path-or-default>
    --task-id WA-05-02
    --correctness 0..4
    --specificity 0..4
    --evidence-quality 0..4
    --engineering-usefulness 0..4
    --unsupported-claim-discipline 0..4
    [--hard-label UNINTERPRETABLE|API_ERROR|TIMEOUT|UNSUPPORTED_CLAIM|FACTUALLY_WRONG]
    [--defect-found true|false]
    [--root-cause-correct true|false]
    [--location-correct true|false]
    [--fix-correct true|false]
    [--tests-useful true|false]
    [--invented-facts true|false]
    [--byte-baseline-correct true|false]
    [--follow-up]
    [--note <max-500-chars>]

python scripts/wolfram_qualification.py summary
    --campaign qualification/wolfram/llm-api-v1.json
    --scores-file <path-or-default>
    [--improved-family WA-01]...
```

Default score path: `%USERPROFILE%\.byte-mcp\wolfram\qualification\llm-api-v1-scores.jsonl` on Windows, otherwise `~/.byte-mcp/wolfram/qualification/llm-api-v1-scores.jsonl`.

- [ ] **Step 1: Write RED fixture-integrity tests**

Require exactly 30 tasks: three each for `WA-01` through `WA-10`; unique IDs; all prompts non-blank and <=8,000 chars; ground truth non-blank; no prompt contains a real machine path or credential-pattern sentinel; campaign SHA-256 is stable and printed by `list`.

- [ ] **Step 2: Write RED scoring/profile tests**

Classifications:

```text
18-20 EXCELLENT
14-17 USEFUL
10-13 PARTIAL
5-9 WEAK
0-4 NOT_USEFUL
```

Define metrics using **primary scores only**:

```text
coding_root_cause_correctness =
  root_cause_correct=true / coding tasks whose ground truth contains a defect

unsupported_or_invented_claim_rate =
  primary tasks with hard_label=UNSUPPORTED_CLAIM OR invented_facts=true
  / 30

computational families = WA-01, WA-02, WA-03, WA-07, WA-08, WA-10
computational_core_average = average score across their 18 primary tasks
computational_family_pass_count = number of those six family averages >=14
```

Profile assignment is deterministic:

```text
A if:
  overall_average >=14
  AND coding_root_cause_correctness >=0.70
  AND unsupported_or_invented_claim_rate <=0.10
  AND len(improved_families) >=1

B if not A AND:
  computational_core_average >=14
  AND computational_family_pass_count >=4
  AND unsupported_or_invented_claim_rate <=0.10

C if not A/B AND:
  WA-01 family average >=14
  AND unsupported_or_invented_claim_rate <=0.20

D otherwise
```

`--improved-family` accepts only `WA-01..WA-10`; it is a Byte-authored evidence judgment, not inferred from model scores.

- [ ] **Step 3: Create the fixed 30-task campaign**

Use exactly these IDs/prompts/ground-truth conditions. JSON uses fields `task_id`, `family`, `prompt`, `ground_truth`, `coding_task`.

```text
WA-01-01: "Compute 2^100 exactly." -> 1267650600228229401496703205376
WA-01-02: "Evaluate the definite integral of x^2 from x=0 to x=3." -> 9
WA-01-03: "Solve x^3 - 6 x^2 + 11 x - 6 = 0 over the reals." -> roots 1,2,3

WA-02-01: "Is (a+b)^2 = a^2 + 2 a b + b^2 for all real a,b?" -> yes
WA-02-02: "For real x>=0,y>=0,x+y=10, maximize x y." -> 25 at x=y=5
WA-02-03: "Claim: (x+y)^2 = x^2+y^2 for all real x,y. Verify or give a counterexample." -> false; e.g. x=y=1

WA-03-01: "Solve the asymptotic recurrence T(n)=2 T(n/2)+n for powers of two." -> Theta(n log n)
WA-03-02: "For d(n)=min(2*2^n,60), list d(n) for n=0 through 6." -> 2,4,8,16,32,60,60
WA-03-03: "A system has 8 independent boolean flags and one independent 5-state mode. How many total states?" -> 1280

WA-04-01: "Review Python function def clamp(x, lo, hi): return min(max(x, lo), hi) under precondition lo<=hi. State whether it satisfies inclusive clamping." -> correct under precondition; no invented defect
WA-04-02: "Review Python function def unique(xs): return list(set(xs)) against requirement: return first occurrence of each item while preserving input order." -> defect: set loses stable first-occurrence order; use seen-set plus output list or dict-based stable approach
WA-04-03: "Review Python function def get_or_set(cache, key, loader):\n    if cache.get(key):\n        return cache[key]\n    value = loader()\n    cache[key] = value\n    return value\nRequirement: any cached value, including 0, False, empty string or None, is a valid hit." -> subtle defect: truthiness check reloads falsey cached values; use `if key in cache`

WA-05-01: "Debug Python def last(xs): return xs[len(xs)] for non-empty xs. Identify root cause and correction." -> IndexError; valid last index is len(xs)-1; use xs[-1]
WA-05-02: "Debug Python function def is_prefix(xs, ys): return all(a == b for a, b in zip(xs, ys)). Requirement: return True exactly when every element of xs matches the start of ys and xs is not longer than ys." -> subtle defect: zip truncates, so longer xs can incorrectly pass; require len(xs)<=len(ys) plus element comparison
WA-05-03: "Debug Python function def consume(cache, key, loader):\n    value = cache.pop(key, None)\n    if value is None:\n        value = loader(key)\n    return value\nRequirement: cached None is a legitimate stored value and must not call loader." -> subtle ambiguity bug: sentinel conflates missing key with stored None; use membership or unique sentinel

WA-06-01: "Generate a minimal boundary-focused test set for inclusive clamp(x,lo,hi) with lo=0,hi=10." -> must cover below, at low, interior, at high, above
WA-06-02: "Generate tests for parser accepting only decimal integers 1 through 999 inclusive." -> must cover 1,999,0,1000,nonnumeric; leading-zero behavior may be explicitly stated
WA-06-03: "Generate tests for retry delay min(2*2^n,60) for nonnegative integer n." -> must include pre-cap, first cap, post-cap cases

WA-07-01: "For Python expression [x*x for x in range(5) if x%2==0], give exact output." -> [0,4,16]
WA-07-02: "For mapping {'a':1,'b':2}, transform values v to 2*v and list key-value results in key order a,b." -> a=2,b=4
WA-07-03: "State machine starts CLOSED. Event open -> OPEN, event close -> CLOSED; duplicate close while CLOSED leaves CLOSED. Apply open, close, close." -> CLOSED

WA-08-01: "States DRAFT,SUBMITTED,APPROVED,REJECTED. Allowed DRAFT->SUBMITTED; SUBMITTED->APPROVED or REJECTED; APPROVED and REJECTED terminal. Is APPROVED->DRAFT reachable?" -> no
WA-08-02: "Transaction states CLEAN,WRITING,COMMITTED,ROLLED_BACK. Allowed CLEAN->WRITING; WRITING->COMMITTED or ROLLED_BACK; terminal after COMMITTED/ROLLED_BACK. Can COMMITTED and ROLLED_BACK both be reached in one execution?" -> no under model
WA-08-03: "Login state has failure count 0..3; each failed login increments to max 3; count 3 is LOCKED; success before 3 resets to 0. From 0 after fail,fail,success,fail,fail,fail what is state?" -> LOCKED/count 3

WA-09-01: "Service base memory is 1 GB. At most 4 concurrent workers each add 200 MB. Give bounded peak memory ignoring other overhead." -> 1.8 GB under decimal units; if binary units are assumed, state assumption and compute consistently
WA-09-02: "Arrival rate is 100 requests/s and mean service time is 0.2 s. Under Little's Law, estimate mean concurrency." -> 20
WA-09-03: "Three identical replicas each sustain 50 requests/s. Ignoring coordination overhead, maximum aggregate throughput?" -> 150 requests/s

WA-10-01: "Claim: d(n)=min(2*2^n,60) reaches 128 seconds at n=6. Verify." -> false; d(6)=60
WA-10-02: "Claim: matching SHA-256 digests mathematically proves two arbitrary files are identical with absolute certainty. Assess." -> false as an absolute mathematical claim; collisions theoretically exist even though accidental collision probability is negligible
WA-10-03: "Claim: enumerating every assignment of 40 independent booleans requires only 40^2=1600 assignments. Verify." -> false; 2^40=1099511627776
```

`coding_task=true` for WA-04 and WA-05 only. Ground truth for WA-04-01 is explicitly clean, so it is excluded from root-cause denominator.

- [ ] **Step 4: Implement score-only persistence**

`append_score()` writes one JSON object per line containing only the `QualificationScore` fields. Validate fixture hash and task ID before append. Create parent directory. Use an in-process lock and flush/fsync after append. No raw Wolfram response may be accepted by the function or CLI.

- [ ] **Step 5: Implement exact CLI parsing**

Use `argparse` subcommands with the arguments shown in the interface block. Parse tri-state booleans from literal `true`/`false`; absent means `None`. `list` prints campaign hash and task IDs/prompts/ground-truth for operator review. `record` echoes only task ID + stored score metadata. `summary` prints `QualificationSummary` JSON.

- [ ] **Step 6: Write RED campaign/call-budget tests**

Assert 30 primary task records are required for a final profile; duplicate primary record rejected; follow-up requires an existing primary task; sixth follow-up rejected; profile remains `INCOMPLETE` until all 30 primary records exist. Add `INCOMPLETE` as a summary-only profile value before completion; final completed profile is exactly A/B/C/D.

- [ ] **Step 7: Run GREEN**

```bash
python -m pytest tests/wolfram/test_qualification.py -v
python scripts/wolfram_qualification.py list --campaign qualification/wolfram/llm-api-v1.json
```

- [ ] **Step 8: Include qualification script in compile gates and commit**

Update `scripts/Check.ps1` compile command and CI compile command to include `scripts/wolfram_qualification.py`. Do not run real qualification calls in CI.

```bash
git add qualification/wolfram/llm-api-v1.json src/byte_mcp/wolfram/qualification.py tests/wolfram/test_qualification.py scripts/wolfram_qualification.py scripts/Check.ps1 .github/workflows/ci.yml
git commit -m "test: add Wolfram LLM qualification campaign"
```

---

### Task 10: Documentation, deterministic full gate, live canary, and qualification campaign

**Files:**
- Modify: `README.md`
- Modify: `docs/SECURITY.md`
- Modify: `CHANGELOG.md`
- Create after evidence exists: `docs/WOLFRAM-LLM-QUALIFICATION.md`

**Interfaces:** Produces operator documentation and the evidence-based Phase 1 capability profile. No broader Wolfram MCP tools are created here.

- [ ] **Step 1: Document exact operator setup and state paths**

README must show:

```powershell
.\scripts\Setup-Wolfram.ps1
.\scripts\Start-ByteMCP.ps1
```

Document:

```text
%USERPROFILE%\.byte-mcp\credentials\wolfram-appid.dpapi
%USERPROFILE%\.byte-mcp\wolfram\usage.json
```

State explicitly: `Setup-Wolfram.ps1` is optional; without it Byte-MCP core starts normally and `wolfram_query` reports unavailable.

- [ ] **Step 2: Update security/changelog without overstating acceptance**

Document fixed endpoint, bearer injection, open-world annotation, secret/path policy, metadata-only audit, conservative quota ledger, no retries, no result cache, no direct OX-Wolfram communication, and one-tool Phase 1 boundary. Changelog state before live qualification: `implementation_in_validation`; broad co-engineer authority not yet granted.

- [ ] **Step 3: Run deterministic exact-head gate**

```powershell
.\scripts\Check.ps1
```

Record actual pip-check, compile, Ruff, pytest, and Pester results from the implementation head. Verify Windows and Ubuntu GitHub Actions on the same SHA.

- [ ] **Step 4: Confirm current Wolfram documentation/terms immediately before live calls**

Verify current LLM API endpoint/auth mechanism, current plan quota, no-caching restriction, and attribution requirement. If a material change conflicts with the approved design, stop live execution and amend the design; do not improvise around it.

- [ ] **Step 5: Configure the real AppID locally**

```powershell
.\scripts\Setup-Wolfram.ps1
```

Paste the existing LLM API AppID only into the secure prompt. Do not put it in commands, source, fixtures, GitHub, or chat.

- [ ] **Step 6: Start stack and verify tool discovery**

```powershell
.\scripts\Start-ByteMCP.ps1
.\scripts\Run-Smoke-Test.ps1 -Root projects
```

Tool catalog must contain four existing filesystem tools plus `wolfram_query`, and no broader Wolfram tools.

- [ ] **Step 7: Run one non-sensitive real canary**

Invoke through MCP:

```text
input: "2^100"
purpose: COENGINEERING
route_reason: DIRECT_COMPUTATION
max_chars: 1000
```

Expected semantic result includes `1267650600228229401496703205376`. Verify result link when supplied, quota increments exactly once, and audit contains metadata/fingerprint only.

- [ ] **Step 8: Exercise one controlled interpretation-failure probe without retry**

Send exactly once:

```text
"zxqvplm qqq 19 banana tensor sideways"
```

If Wolfram returns 501, verify `WolframUninterpretableError` and one quota increment. If it interprets the input, record that success and rely on mocked 501 tests for deterministic error proof; do not spend repeated calls forcing a 501.

- [ ] **Step 9: Freeze campaign hash**

```bash
python scripts/wolfram_qualification.py list --campaign qualification/wolfram/llm-api-v1.json
```

Record SHA-256 before first benchmark call. Any later prompt/ground-truth change requires a new campaign file/version and restart; never mutate the active campaign midway.

- [ ] **Step 10: Record Byte baselines before seeing Wolfram on selected tasks**

Pre-solve these eight tasks and record only `byte_baseline_correct=true|false` during their eventual score record:

```text
WA-03-02
WA-04-02
WA-04-03
WA-05-01
WA-05-02
WA-08-02
WA-10-01
WA-10-02
```

Do not view Wolfram outputs for those task IDs before the Byte baseline judgment is fixed.

- [ ] **Step 11: Run 30 primary qualification calls exactly once each**

For every task in fixture order:

1. invoke `wolfram_query` exactly once with fixture prompt;
2. choose route reason by family: WA-01/03/07/09=`DIRECT_COMPUTATION`; WA-02/08=`VERIFY_BYTE_HYPOTHESIS`; WA-06=`GENERATE_TEST_ORACLE`; WA-04/05=`CODE_COMPREHENSION`; WA-10=`SEARCH_COUNTEREXAMPLE`;
3. inspect current response in active session only;
4. score against frozen ground truth;
5. record using the exact `record` CLI;
6. do not retry weak/incorrect answers to improve primary score.

- [ ] **Step 12: Use at most five deliberate follow-ups**

A follow-up asks whether clarification changes an initially partial result. Record with `--follow-up`; never replace the primary score. Stop before five if additional evidence is not useful.

- [ ] **Step 13: Record Byte+Wolfram improvement families**

A family qualifies for `--improved-family` only when at least one pre-baselined task shows either:

```text
A. Byte baseline was incorrect and Byte+Wolfram reaches the frozen ground truth; OR
B. Byte baseline was already correct but Wolfram contributes a concrete ground-truth-relevant counterexample/test/oracle that materially strengthens the engineering action Byte would take.
```

Record the rationale in the qualification document, not as raw provider text.

- [ ] **Step 14: Generate final qualification summary**

Example:

```bash
python scripts/wolfram_qualification.py summary \
  --campaign qualification/wolfram/llm-api-v1.json \
  --improved-family WA-05
```

Use all actual improved families. Summary must contain a completed A/B/C/D profile only after all 30 primary scores exist.

- [ ] **Step 15: Write `docs/WOLFRAM-LLM-QUALIFICATION.md` from evidence**

Include implementation commit, campaign hash, real call count, local quota count, overall/per-family scores, coding root-cause rate, unsupported/invented-claim rate, Byte baseline comparison, improved-family rationale, final profile, observed API limitations, and recommended next architectural gate. Do not include AppID or bulk/raw Wolfram response text.

- [ ] **Step 16: Re-run full regression after evidence documentation**

```powershell
.\scripts\Check.ps1
```

No live Wolfram calls are part of `Check.ps1`.

- [ ] **Step 17: Commit documentation/evidence**

```bash
git add README.md docs/SECURITY.md docs/WOLFRAM-LLM-QUALIFICATION.md CHANGELOG.md
git commit -m "docs: record Wolfram LLM Phase 1 qualification"
```

---

## Phase 1 Gate Mapping

**Gate A — Contracts/config:** Task 1 proves exact settings/domain types, optional availability, errors, fixed dependency scope, and no tracked local usage file.

**Gate B — Outbound authority:** Tasks 2 and 8 prove secret denial, path sanitization, no arbitrary endpoint/method/header choice, and no automatic OX-to-Wolfram forwarding.

**Gate C — Usage discipline:** Task 3 proves atomic conservative local accounting and 1,800-reservation soft ceiling without storing provider content.

**Gate D — Provider transport:** Task 4 proves fixed LLM API GET, bearer-only AppID placement, bounded timeouts, typed errors, result-link parsing, and zero retries.

**Gate E — Orchestration/provenance:** Task 5 proves Byte-owned routing, metadata-only audit, fallback provenance, policy/quota/audit-before-network ordering, and fail-isolated runtime.

**Gate F — MCP surface:** Task 6 proves exactly one new Phase 1 Wolfram tool, correct open-world annotations, exact caller argument surface, and unchanged core startup.

**Gate G — Credential security:** Task 7 proves Windows user-bound DPAPI storage, child-only secret injection, exact parent restoration, optional configuration, and no secret command-line/state/log exposure.

**Gate H — Adversarial regression:** Task 8 proves leakage resistance, forbidden routing, no-retry, OX separation, and existing filesystem behavior under Wolfram failures.

**Gate I — Qualification integrity:** Task 9 fixes prompts/ground truth/scoring and deterministic A/B/C/D profile rules before live evaluation; persists score metadata only.

**Gate J — Live acceptance:** Task 10 proves a real canary, bounded error probe, 30-call campaign, evidence-based capability profile, full regression, and exact-head CI.

---

## Self-Review Checklist and Result

### Spec coverage

- Organizational roles/no OX-Wolfram direct communication: Tasks 5, 8, 10.
- Existing V1.1 filesystem boundary preserved: Tasks 6, 8, 10.
- Phase 1 LLM API only: Tasks 1–10; no local Engine or Full Results implementation.
- AppID secrecy/DPAPI: Tasks 1, 4, 7, 8.
- Fixed endpoint/bearer/no arbitrary HTTP: Tasks 1, 4, 8.
- `wolfram_query` only: Task 6.
- 6,800 response and 8,000 input ceilings: Tasks 1, 2, 4, 5.
- 1,800 local soft ceiling/zero retry: Tasks 3–5, 8.
- Tier A/B allowed; Tier C denied pre-network: Tasks 2, 5, 8.
- Machine path sanitization: Tasks 2, 8.
- Metadata-only audit/no cache: Tasks 5, 8, 9, 10.
- Qualification before broader review tooling: Tasks 9–10.
- 30 primary + <=5 follow-up budget: Tasks 9–10.
- Straightforward and subtle coding defects: Task 9 WA-04/WA-05 fixtures.
- Broad threshold and deterministic narrower profiles: Task 9.
- Full regression and Windows/Ubuntu CI: Tasks 6, 8, 10.

### Placeholder scan

No `TBD`, `TODO`, `implement later`, unnamed production interface, generic error-handling instruction, or unnamed test requirement remains. Evidence-dependent values are limited to the existing secret AppID and live qualification scores; neither belongs in source before execution.

### Type/interface consistency

- `WolframSettings`, enums, `WolframQueryRequest`, `WolframClientResult`, errors, and fixture are defined in Task 1 before use.
- `PreparedWolframInput` exact fields are defined in Task 2 before service use.
- `QuotaReservation`/`QuotaSnapshot` exact fields are defined in Task 3 before service use.
- `WolframLLMClient.query()` exact signature exists before Task 5.
- `WolframService`/`WolframRuntime` exact signatures exist before FastMCP registration.
- Launcher additions explicitly reuse existing DPAPI/snapshot/restore functions.
- Qualification dataclasses/functions/CLI/profile rules are fully defined in Task 9 before live use.
- `source_finding_id` remains an opaque local identifier; no production task depends on `byte_mcp.ox` implementation internals.

## Execution Handoff

At implementation start, create an isolated worktree using `superpowers:using-git-worktrees`. Execute with `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`, preserving the RED -> GREEN cycles and commit checkpoints above.

Do not implement the broader Wolfram review lifecycle, local Wolfram Engine, Full Results API, or provider-to-provider automation in this plan. Those require evidence from the qualification gate and a separate approved design/implementation cycle.