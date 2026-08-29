# Byte-MCP Wolfram LLM Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure, quota-aware `wolfram_query` capability to Byte-MCP using the Wolfram|Alpha LLM API, preserve the existing filesystem and OX trust boundaries, and run a fixed evidence-based qualification campaign before granting Wolfram any broader engineering tool surface.

**Architecture:** Preserve the accepted `FileService` and existing launcher/tunnel model. Add an isolated `byte_mcp.wolfram` package containing settings/domain contracts, outbound data policy, local quota accounting, a fixed Wolfram|Alpha LLM API client, and a service/runtime boundary. The launcher stores the Wolfram AppID with the same Windows user-bound DPAPI mechanism already used for the tunnel credential and injects it only into the Byte-MCP server child process. Phase 1 exposes only `wolfram_query`; `wolfram_review`, `wolfram_continue`, `wolfram_revalidate`, `wolfram_get_review`, the Full Results API, and the local Wolfram Engine remain outside this implementation until qualification evidence justifies a new gate.

**Tech Stack:** Python `>=3.12,<3.14`; `mcp[cli]==1.28.1`; `httpx>=0.28.1,<1`; stdlib dataclasses/enums/JSON/SHA-256/threading/atomic file replacement; pytest; ruff; existing PowerShell/Pester launcher; existing Windows and Ubuntu CI.

**Spec:** `docs/superpowers/specs/2026-08-30-wolfram-coengineer-integration-design.md`

## Global Constraints

- One Byte-MCP server only; Wolfram is a separately governed capability inside the existing server, not a second MCP server or tunnel.
- The accepted filesystem tools remain `list_roots`, `list_directory`, `search`, and `fetch`; no repository write, shell, registry, process-control, computer-use, unrestricted-path, or generic HTTP authority is introduced.
- Phase 1 exposes exactly one new Wolfram MCP tool: `wolfram_query`.
- The fixed provider route is `https://www.wolframalpha.com/api/v1/llm-api` using HTTP GET.
- Authentication uses `Authorization: Bearer <AppID>` created only inside the Wolfram client; the AppID is never passed as an MCP argument or query-string parameter.
- `input` is required, non-blank, and bounded to 8,000 characters after normalization.
- `max_chars` defaults to 6,800 and is clamped to `250..6800`.
- Each MCP invocation makes at most one provider request; automatic retries are zero.
- Wolfram normal co-engineering calls do not use OX's two-phase human approval gate; Tier A and bounded Tier B calls are allowed by the approved outbound policy.
- Tier C secret-bearing payloads fail before network transmission.
- Machine-specific absolute Windows paths are sanitized before transmission; repository-relative paths may remain.
- OX and Wolfram never communicate directly. The Wolfram subsystem contains no OX client dependency and accepts no raw OX conversation field.
- Local operational audit stores fingerprints/metadata only, never raw Wolfram input, raw Wolfram result, AppID, authorization header, or secret-bearing payload.
- No permanent Wolfram result cache is created.
- Local quota accounting is conservative operational telemetry, not provider billing authority. It counts every outbound attempt before the request is sent, so a crash may over-count rather than under-count.
- Initial local soft ceiling is 1,800 outbound attempts per UTC calendar month; provider limits remain authoritative.
- Wolfram being disabled, misconfigured, rate-limited, or unavailable must not prevent Byte-MCP's existing filesystem service from starting or operating.
- Automated tests never use Nolan's AppID or real Wolfram quota.
- Phase 1 qualification uses at most 30 primary calls plus 5 deliberate follow-up calls.
- Broader Wolfram review tools are not implemented in this plan.

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

### Task 1: Wolfram domain contracts, settings, errors, and dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/byte_mcp/errors.py`
- Create: `src/byte_mcp/wolfram/__init__.py`
- Create: `src/byte_mcp/wolfram/domain.py`
- Create: `src/byte_mcp/wolfram/settings.py`
- Create: `tests/wolfram/__init__.py`
- Create: `tests/wolfram/conftest.py`
- Create: `tests/wolfram/test_domain.py`
- Create: `tests/wolfram/test_settings.py`

**Interfaces:**
- Produces `WolframAvailability`: `AVAILABLE`, `DISABLED`, `MISCONFIGURED`.
- Produces `WolframPurpose`: `COENGINEERING`, `FALLBACK_VALIDATION`.
- Produces `WolframRouteReason`: `DIRECT_COMPUTATION`, `KNOWLEDGE_LOOKUP`, `VERIFY_BYTE_HYPOTHESIS`, `GENERATE_TEST_ORACLE`, `SEARCH_COUNTEREXAMPLE`, `DEBUG_NUMERICAL_BEHAVIOR`, `CODE_COMPREHENSION`, `OX_FALLBACK`, `OTHER_BOUNDED_REASON`.
- Produces immutable `WolframQueryRequest`, `WolframClientResult`, and `WolframQueryResult`.
- Produces `WolframSettings.load(repo_root: Path) -> WolframSettings`.
- Produces shared pytest fixture `wolfram_settings`.

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
```

Add RED tests proving the endpoint cannot be overridden by environment, blank AppIDs normalize to `None`, the soft limit can be lowered for tests but never raised above 1,800 through environment, and `max_chars` bounds remain fixed.

- [ ] **Step 2: Write RED domain tests**

```python
from byte_mcp.wolfram.domain import WolframPurpose, WolframRouteReason


def test_ox_fallback_is_explicit_purpose_and_route() -> None:
    assert WolframPurpose.FALLBACK_VALIDATION.value == "FALLBACK_VALIDATION"
    assert WolframRouteReason.OX_FALLBACK.value == "OX_FALLBACK"
```

Also prove a `WolframQueryRequest` rejects blank input and rejects an `OX_FALLBACK` route unless `purpose=FALLBACK_VALIDATION`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/wolfram/test_settings.py tests/wolfram/test_domain.py -v
```

Expected: import failures because `byte_mcp.wolfram` does not exist.

- [ ] **Step 4: Add the only new Python dependency**

Add to `[project].dependencies`:

```toml
"httpx>=0.28.1,<1",
```

Do not add a Wolfram SDK, generic model SDK, retry library, ORM, vector store, or database server.

- [ ] **Step 5: Add the concrete error taxonomy**

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

- [ ] **Step 6: Implement exact settings**

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
```

`BYTE_MCP_WOLFRAM_USAGE_FILE` defaults to `data/wolfram-usage.json` for direct development. The accepted launcher profile overrides it to `%USERPROFILE%\.byte-mcp\wolfram\usage.json`. `BYTE_MCP_WOLFRAM_SOFT_LIMIT` may set `1..1800` for tests/operations. `repr()` includes only `app_id_configured`.

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
git add pyproject.toml src/byte_mcp/errors.py src/byte_mcp/wolfram tests/wolfram
git commit -m "feat: add Wolfram Phase 1 contracts"
```

---

### Task 2: Outbound data policy and path sanitization

**Files:**
- Create: `src/byte_mcp/wolfram/policy.py`
- Create: `tests/wolfram/test_policy.py`

**Interfaces:**
- Produces `WolframOutboundPolicy(user_profile: Path | None = None)`.
- Produces `prepare(input_text: str) -> PreparedWolframInput`.
- `PreparedWolframInput` contains only `text`, `sha256`, `original_chars`, `transmitted_chars`, `paths_sanitized`.
- Secret detection raises `WolframPolicyError` before any transport is reachable.

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
    ],
)
def test_secret_like_payload_is_denied(payload: str) -> None:
    with pytest.raises(WolframPolicyError, match="sensitive"):
        WolframOutboundPolicy().prepare(payload)
```

Add tests for common token forms and connection strings containing `password=` or `pwd=`. Tests must use fake sentinel values only.

- [ ] **Step 2: Write RED path-sanitization tests**

```python
from pathlib import Path

from byte_mcp.wolfram.policy import WolframOutboundPolicy


def test_windows_absolute_paths_are_replaced() -> None:
    prepared = WolframOutboundPolicy(Path(r"C:\Users\nolan")).prepare(
        r"Failure in C:\Users\nolan\AIProjects\tidy\src\tidy\core.py line 12"
    )

    assert r"C:\Users\nolan" not in prepared.text
    assert "<local-path>" in prepared.text
    assert prepared.paths_sanitized == 1
```

Also prove relative paths such as `src/tidy/core.py` remain intact.

- [ ] **Step 3: Write RED normalization/bound tests**

Input must be stripped, reject NUL, normalize CRLF to LF, preserve meaningful newlines, and reject post-normalization length above 8,000. Do not silently truncate engineering input.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/wolfram/test_policy.py -v
```

- [ ] **Step 5: Implement deny-first policy**

Compile explicit secret patterns once. Run secret detection before path replacement so a secret cannot be hidden by sanitization. Replace absolute Windows paths with `<local-path>` while preserving surrounding line/diagnostic text. Hash the final transmitted UTF-8 text with SHA-256.

Do not attempt to infer whether arbitrary source code is proprietary or personal. The implemented boundary is: Byte selects bounded context; the policy mechanically rejects secret-like data and machine-identifying paths.

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
- Produces `WolframQuotaLedger(path: Path, soft_limit: int)`.
- Produces `reserve_attempt(now: datetime | None = None) -> QuotaReservation`.
- Produces `snapshot(now: datetime | None = None) -> QuotaSnapshot`.
- Reservation increments before network transmission and is never decremented after provider failure.

- [ ] **Step 1: Write RED quota tests**

```python
from datetime import UTC, datetime

import pytest

from byte_mcp.errors import WolframQuotaError
from byte_mcp.wolfram.quota import WolframQuotaLedger


def test_quota_reserves_before_outbound_attempt(tmp_path) -> None:
    ledger = WolframQuotaLedger(tmp_path / "usage.json", soft_limit=2)
    now = datetime(2026, 8, 30, tzinfo=UTC)

    first = ledger.reserve_attempt(now)
    second = ledger.reserve_attempt(now)

    assert first.period_count == 1
    assert second.period_count == 2
    with pytest.raises(WolframQuotaError):
        ledger.reserve_attempt(now)
```

Add tests for UTC month rollover, malformed ledger fail-closed, atomic temp-file replacement, and two threads reserving concurrently without duplicate counts.

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

Use an in-process lock, same-directory temporary file, `flush()`, `os.fsync()`, and `os.replace()`. Never store query text, response content, result URLs, AppID, or errors in this file.

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

**Interfaces:**
- Produces `WolframLLMClient(settings: WolframSettings, transport: httpx.BaseTransport | None = None)`.
- Produces `query(input_text: str, max_chars: int) -> WolframClientResult`.
- No other module may perform Wolfram HTTP requests.

- [ ] **Step 1: Write RED exact request-shape test using `httpx.MockTransport`**

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

    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(handler),
    )
    result = client.query("2+2", 6800)

    request = seen["request"]
    assert str(request.url).startswith("https://www.wolframalpha.com/api/v1/llm-api?")
    assert request.url.params["input"] == "2+2"
    assert request.url.params["maxchars"] == "6800"
    assert "appid" not in request.url.params
    assert request.headers["Authorization"] == "Bearer TEST-WOLFRAM-APPID"
    assert result.result_url.startswith("https://www.wolframalpha.com/input?")
```

- [ ] **Step 2: Write RED one-request/no-retry test**

Return `503` from the mock transport and assert the handler is invoked exactly once.

- [ ] **Step 3: Write RED error mapping tests**

Assert:

```text
400 -> WolframRequestError
403 -> WolframAuthenticationError
429 -> WolframRateLimitError
501 -> WolframUninterpretableError (safe suggested-input body may be included, bounded)
5xx -> WolframProviderError
ConnectError / ConnectTimeout / TLS or network error -> WolframTransportError
ReadTimeout -> WolframTimeoutError
```

Error strings must not contain the AppID or authorization header.

- [ ] **Step 4: Write RED response parsing tests**

A `200` response must be non-empty UTF-8 text. Extract the final `https://www.wolframalpha.com/input?...` line when present as `result_url`; otherwise return `result_url=None` without inventing one. Preserve raw current-call result text only in the returned in-memory object; do not write it to disk.

- [ ] **Step 5: Run RED**

```bash
python -m pytest tests/wolfram/test_client.py -v
```

- [ ] **Step 6: Implement bounded non-streaming GET**

Use:

```python
httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
```

The client owns the fixed endpoint and headers. `follow_redirects=False`. Do not create retry middleware. Do not expose generic request parameters such as host, URL, `assumption`, location, or arbitrary Full Results options in Phase 1.

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

**Interfaces:**
- Produces `WolframService(settings, audit, policy, quota, client)`.
- Produces `query(input: str, max_chars: int | None, purpose: str, route_reason: str, source_finding_id: str | None = None) -> dict[str, object]`.
- Produces `WolframRuntime.load(repo_root: Path, audit: AuditLog) -> WolframRuntime`.
- Runtime exposes `availability` without causing provider traffic.

- [ ] **Step 1: Write RED happy-path service test**

Use fake policy/quota/client. Assert order:

```text
validate purpose/route
prepare/sanitize payload
reserve quota
persist transmission-intent audit metadata
perform exactly one client call
persist success audit metadata
return bounded result
```

Expected public result shape:

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

Do not return `request_id` if it would encourage treating it as an authentication token; if returned for provenance, document it as a non-secret identifier.

- [ ] **Step 2: Write RED audit privacy test**

Use sentinels in the query/result/AppID. Read JSONL and prove all are absent. Audit fields are limited to:

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

- [ ] **Step 3: Write RED policy-before-network test**

A secret-bearing payload must raise `WolframPolicyError`; fake quota and fake client must both show zero calls if policy fails.

- [ ] **Step 4: Write RED quota-before-network test**

An exhausted local budget raises `WolframQuotaError`; fake client receives zero calls.

- [ ] **Step 5: Write RED fail-isolated runtime tests**

No `WOLFRAM_APP_ID` -> `DISABLED`; service construction remains possible only as a controlled unavailable object and never breaks `FileService`. Malformed Wolfram-only settings -> `MISCONFIGURED` without changing core `Settings` behavior.

- [ ] **Step 6: Run RED**

```bash
python -m pytest tests/wolfram/test_service.py tests/wolfram/test_runtime.py -v
```

- [ ] **Step 7: Implement explicit route validation**

If `route_reason=OX_FALLBACK`, require `purpose=FALLBACK_VALIDATION` and non-blank `source_finding_id`. For all other routes, reject `source_finding_id`; this prevents silent OX transcript coupling while permitting local provenance linkage.

- [ ] **Step 8: Implement fail-closed audit intent before HTTP**

Persist a metadata-only `outcome="transmitting"` event before the client call. If that audit write fails, abort before network. After the provider attempt, record success or typed failure metadata. If the provider returns successfully but final audit persistence fails, raise `AuditError` rather than reporting an unaudited successful operation; do not retry the provider call.

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

**Interfaces:**
- Adds lazy `wolfram_runtime()` / `wolfram_service()` separate from existing `service()`.
- Adds one MCP tool:

```python
wolfram_query(
    input: str,
    max_chars: int | None = None,
    purpose: str = "COENGINEERING",
    route_reason: str = "OTHER_BOUNDED_REASON",
    source_finding_id: str | None = None,
) -> dict[str, object]
```

- [ ] **Step 1: Write RED MCP catalog/annotation test**

Assert the new tool exists and the following do not:

```text
wolfram_review
wolfram_continue
wolfram_revalidate
wolfram_get_review
wolfram_compute
http_request
fetch_url
```

Use a distinct annotation object:

```python
WOLFRAM_EXTERNAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
```

It is not idempotent operationally because a repeat call consumes another external API attempt.

- [ ] **Step 2: Write RED startup-isolation test**

Extend `test_main_initializes_service_before_binding_server` only as needed to prove core `service()` is still validated before binding, while Wolfram runtime is lazy and missing AppID does not prevent `main()` from running.

- [ ] **Step 3: Write RED argument-surface test**

Inspect the FastMCP tool schema and prove caller cannot supply `appid`, `url`, `endpoint`, `headers`, `method`, `assumption`, or arbitrary HTTP parameters.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/test_server.py tests/wolfram/test_mcp_surface.py -v
```

- [ ] **Step 5: Implement lazy Wolfram runtime using the existing audit file**

Construct Wolfram runtime only on first `wolfram_query` call. Use `AuditLog(SETTINGS.audit_file)` independently; do not require `FileService` internals or copy its roots into Wolfram.

- [ ] **Step 6: Update protocol smoke discovery**

Change `EXPECTED_TOOLS` to include `wolfram_query` only after this task. Do not make the ordinary filesystem smoke test call Wolfram or require an AppID; discovery alone proves the tool is registered.

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
- Server child receives `WOLFRAM_APP_ID` only when the encrypted credential file exists.
- Parent PowerShell process environment is restored after child creation.

- [ ] **Step 1: Write RED path/config tests**

Add:

```powershell
$paths.WolframCredentialFile | Should -Be 'C:\Users\test\.byte-mcp\credentials\wolfram-appid.dpapi'
$paths.WolframUsageFile | Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
```

`Get-ByteMcpServerEnvironment` includes only the non-secret usage path:

```powershell
$map.BYTE_MCP_WOLFRAM_USAGE_FILE | Should -Be 'C:\Users\test\.byte-mcp\wolfram\usage.json'
```

- [ ] **Step 2: Write RED setup-script contract test**

`Setup-Wolfram.ps1` must:

```text
load Launcher.Platform.ps1 before Launcher.Common.ps1
accept ReplaceCredential
accept no AppId/ApiKey/Credential plaintext parameter
use Read-Host 'Paste the Wolfram|Alpha LLM API AppID' -AsSecureString
write only to WolframCredentialFile
round-trip with Unprotect-ByteMcpCredential
```

- [ ] **Step 3: Write RED optional injection/restoration tests**

With no Wolfram credential file, `Start-LauncherServerProcess` must not create `WOLFRAM_APP_ID` in the child environment. With a mocked DPAPI credential, the child observes `child-wolfram-secret` while the parent retains its previous value or absence after `Start-Process` returns.

Use the same test for `Start-LauncherForegroundServer`.

- [ ] **Step 4: Run RED Pester**

```powershell
.\scripts\Check-Launcher.ps1
```

Expected: new Wolfram launcher assertions fail.

- [ ] **Step 5: Add Wolfram paths and setup script**

`Setup-Wolfram.ps1`:

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

For both background and foreground server starts:

1. Build existing non-secret server environment map.
2. Snapshot all map keys plus `WOLFRAM_APP_ID`.
3. If `WolframCredentialFile` exists, decrypt it to a `SecureString`, convert to plaintext only immediately before `Start-Process`, set `WOLFRAM_APP_ID` in process scope, and set the plaintext local variable to `$null` in `finally`.
4. If the file does not exist, remove any inherited process-level `WOLFRAM_APP_ID` for child creation so an unrelated parent secret cannot silently configure Byte-MCP.
5. Restore the parent snapshot in `finally`.

Do not add the secret to launcher state, command-line arguments, log paths, or status output.

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

### Task 8: Security invariant and failure-injection gate

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

Inspect returned errors, audit JSONL, quota JSON, settings repr, runtime repr, logs generated by tests, and public metadata. The AppID/query/result sentinels must never appear in persistent operational files.

- [ ] **Step 2: Add forbidden-transport matrix**

Prove callers cannot redirect traffic to localhost, another Wolfram endpoint, Full Results API, or an arbitrary domain. There is no supported field or setter for endpoint/method/header injection.

- [ ] **Step 3: Add no-auto-retry matrix**

For timeout, 429, 500, malformed 200, and transport failure, assert exactly one `httpx.MockTransport` handler invocation and exactly one quota reservation.

- [ ] **Step 4: Add core isolation matrix**

With Wolfram `DISABLED`, `MISCONFIGURED`, quota-exhausted, and provider-failing states, instantiate and exercise ordinary `FileService` test operations. They must behave exactly as before.

- [ ] **Step 5: Add OX isolation characterization**

The Wolfram public/query data model may contain only `source_finding_id` as optional local provenance for `OX_FALLBACK`; there is no field named `ox_prompt`, `ox_response`, `ox_thread`, `ox_messages`, or `provider_context`. A string containing raw OX-like text is treated as ordinary caller-selected input and still passes through the same secret/path policy; no OX subsystem automatically calls Wolfram.

- [ ] **Step 6: Run focused security gate and repair from evidence only**

```bash
python -m pytest tests/wolfram/test_security_invariants.py -v
```

Do not weaken assertions to accommodate an implementation defect.

- [ ] **Step 7: Run full repository gate and commit**

```powershell
.\scripts\Check.ps1
```

Only after a clean result:

```bash
git add src tests scripts
git commit -m "test: harden Wolfram Phase 1 boundary"
```

---

### Task 9: Deterministic LLM API qualification fixture and score model

**Files:**
- Create: `qualification/wolfram/llm-api-v1.json`
- Create: `src/byte_mcp/wolfram/qualification.py`
- Create: `tests/wolfram/test_qualification.py`
- Create: `scripts/wolfram_qualification.py`
- Modify: `scripts/Check.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces `QualificationTask`, `QualificationScore`, `QualificationSummary`.
- Produces `load_campaign(path: Path) -> tuple[QualificationTask, ...]`.
- Produces `score_total(score: QualificationScore) -> int` and `classify_total(total: int) -> str`.
- Produces `summarize(scores: Sequence[QualificationScore]) -> QualificationSummary`.
- CLI supports `list`, `record`, and `summary`; it stores scores/Byte-authored notes only, never raw Wolfram responses.

- [ ] **Step 1: Write RED fixture-integrity tests**

Require exactly 30 tasks: three each for `WA-01` through `WA-10`; unique task IDs; all prompts non-blank and <=8,000 chars; ground truth declared before live calls; no task contains a real repository secret/path; fixture SHA-256 is printed by the CLI.

- [ ] **Step 2: Write RED scoring tests**

Each dimension is integer `0..4`:

```text
correctness
specificity
evidence_quality
engineering_usefulness
unsupported_claim_discipline
```

Classifications:

```text
18-20 EXCELLENT
14-17 USEFUL
10-13 PARTIAL
5-9 WEAK
0-4 NOT_USEFUL
```

Hard labels are optional values from:

```text
UNINTERPRETABLE
API_ERROR
TIMEOUT
UNSUPPORTED_CLAIM
FACTUALLY_WRONG
```

Coding tasks additionally support nullable booleans:

```text
defect_found
root_cause_correct
location_correct
fix_correct
tests_useful
invented_facts
```

- [ ] **Step 3: Create the fixed 30-task campaign**

Use these exact task IDs and ground-truth conditions. Prompts must be serialized as single JSON strings; code examples may use `\n` inside the string.

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
WA-04-02: "Review Python function def unique(xs): return list(set(xs)) against requirement: return first occurrence of each item while preserving input order." -> defect: set loses order/first-occurrence semantics; propose order-preserving approach
WA-04-03: "Review Python function def mean(xs): return sum(xs)/len(xs) with requirement that empty input returns None." -> defect: division by zero; fix empty case

WA-05-01: "Debug Python def last(xs): return xs[len(xs)] for non-empty xs. Identify root cause and correction." -> IndexError; use xs[len(xs)-1] or xs[-1]
WA-05-02: "Debug Python def append_item(x, xs=[]): xs.append(x); return xs when calls must not share state." -> mutable default; use None/new list
WA-05-03: "Debug Python def average(total, count): return total // count when expected result may be fractional and count>0." -> floor division; use /

WA-06-01: "Generate a minimal boundary-focused test set for inclusive clamp(x,lo,hi) with lo=0,hi=10." -> must cover below, at low, interior, at high, above
WA-06-02: "Generate tests for parser accepting only decimal integers 1 through 999 inclusive." -> must cover 1,999,0,1000, nonnumeric; leading-zero behavior may be explicitly stated
WA-06-03: "Generate tests for retry delay min(2*2^n,60) for nonnegative integer n." -> must include pre-cap, first cap, post-cap cases

WA-07-01: "For Python expression [x*x for x in range(5) if x%2==0], give exact output." -> [0,4,16]
WA-07-02: "For mapping {'a':1,'b':2}, transform values v to 2*v and list key-value results in key order a,b." -> a=2,b=4
WA-07-03: "State machine starts CLOSED. Event open -> OPEN, event close -> CLOSED; duplicate close while CLOSED leaves CLOSED. Apply open, close, close." -> CLOSED

WA-08-01: "States DRAFT,SUBMITTED,APPROVED,REJECTED. Allowed DRAFT->SUBMITTED; SUBMITTED->APPROVED or REJECTED; APPROVED and REJECTED terminal. Is APPROVED->DRAFT reachable?" -> no
WA-08-02: "Transaction states CLEAN,WRITING,COMMITTED,ROLLED_BACK. Allowed CLEAN->WRITING; WRITING->COMMITTED or ROLLED_BACK; terminal after COMMITTED/ROLLED_BACK. Can COMMITTED and ROLLED_BACK both be reached in one execution?" -> no under model
WA-08-03: "Login state has failure count 0..3; each failed login increments to max 3; count 3 is LOCKED; success before 3 resets to 0. From 0 after fail,fail,success,fail,fail,fail what is state?" -> LOCKED/count 3

WA-09-01: "Service base memory is 1 GB. At most 4 concurrent workers each add 200 MB. Give bounded peak memory ignoring other overhead." -> 1.8 GB decimal interpretation or 1824 MiB if explicitly binary; must explain units
WA-09-02: "Arrival rate is 100 requests/s and mean service time is 0.2 s. Under Little's Law, estimate mean concurrency." -> 20
WA-09-03: "Three identical replicas each sustain 50 requests/s. Ignoring coordination overhead, maximum aggregate throughput?" -> 150 requests/s

WA-10-01: "Claim: d(n)=min(2*2^n,60) reaches 128 seconds at n=6. Verify." -> false; 60
WA-10-02: "Claim: matching SHA-256 digests mathematically proves two arbitrary files are identical with absolute certainty. Assess." -> false as absolute mathematical claim; collisions theoretically exist
WA-10-03: "Claim: enumerating every assignment of 40 independent booleans requires only 40^2=1600 assignments. Verify." -> false; 2^40 = 1099511627776
```

- [ ] **Step 4: Implement score-only persistence**

The CLI writes a local score JSONL beneath `%USERPROFILE%\.byte-mcp\wolfram\qualification\llm-api-v1-scores.jsonl` by default. Each record contains task ID, fixture SHA-256, five dimension scores, hard label, coding booleans, and a Byte-authored note capped at 500 characters. It contains no raw provider response.

- [ ] **Step 5: Implement summary thresholds**

Summary reports overall average, per-family average, coding/debugging root-cause correctness for `WA-04`/`WA-05`, invented/unsupported claim rate, and classification counts. It must not automatically claim Byte+Wolfram improvement; that comparison is a human/Byte adjudication field recorded separately after the campaign.

Broad Co-Engineer threshold is met only if:

```text
overall average >= 14/20
coding/debugging root-cause correctness >= 70%
unsupported/invented technical claims <= 10%
byte_plus_wolfram_improved == true for >=1 meaningful family
```

Otherwise assign the narrowest evidence-supported profile A/B/C/D using the approved spec.

- [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/wolfram/test_qualification.py -v
python scripts/wolfram_qualification.py list --campaign qualification/wolfram/llm-api-v1.json
```

- [ ] **Step 7: Include new script in compile gates**

Update `scripts/Check.ps1` compile command and CI compile command to include `scripts/wolfram_qualification.py`. Do not make CI run real qualification calls.

- [ ] **Step 8: Commit**

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

**Interfaces:** Produces operator documentation and the evidence-based Phase 1 capability profile. No broader Wolfram MCP tools are created in this task.

- [ ] **Step 1: Document the exact operator setup**

README must show:

```powershell
.\scripts\Setup-Wolfram.ps1
.\scripts\Start-ByteMCP.ps1
```

Document machine-local locations:

```text
%USERPROFILE%\.byte-mcp\credentials\wolfram-appid.dpapi
%USERPROFILE%\.byte-mcp\wolfram\usage.json
```

State explicitly that `Setup-Wolfram.ps1` is optional; without it Byte-MCP core starts normally and `wolfram_query` reports unavailable.

- [ ] **Step 2: Update security documentation**

Document fixed endpoint, bearer injection, open-world MCP annotation, outbound secret/path policy, metadata-only audit, quota ledger, no retries, no result cache, no direct OX-Wolfram communication, and Phase 1's single-tool boundary.

- [ ] **Step 3: Update changelog without claiming qualification results yet**

Before the live campaign state that Wolfram LLM API integration is `implementation_in_validation` and broad co-engineer authority is not yet granted.

- [ ] **Step 4: Run deterministic exact-head gate**

```powershell
.\scripts\Check.ps1
```

Record actual dependency, compile, Ruff, pytest, and Pester results from the implementation head. Then verify Windows and Ubuntu GitHub Actions on the same SHA.

- [ ] **Step 5: Confirm current Wolfram API terms immediately before live calls**

Review the current LLM API documentation and API Terms of Use. Confirm the fixed endpoint/auth mechanism, current plan quota, no-caching restriction, and attribution requirements have not materially changed. If a material term/API change conflicts with the spec, stop the live gate and amend the design rather than improvising around it.

- [ ] **Step 6: Configure the real AppID locally**

Run:

```powershell
.\scripts\Setup-Wolfram.ps1
```

Paste the existing LLM API AppID into the secure prompt. Do not paste it into source, terminal command arguments, test fixtures, GitHub, or chat.

- [ ] **Step 7: Start the managed stack and verify discovery**

```powershell
.\scripts\Start-ByteMCP.ps1
.\scripts\Run-Smoke-Test.ps1 -Root projects
```

Confirm the tool catalog contains the existing filesystem tools plus `wolfram_query` and no broader Wolfram tools.

- [ ] **Step 8: Run one non-sensitive real canary**

Call through the actual MCP tool:

```text
input: "2^100"
purpose: COENGINEERING
route_reason: DIRECT_COMPUTATION
max_chars: 1000
```

Expected semantic result includes `1267650600228229401496703205376`. Verify a Wolfram result link is preserved when supplied, quota count increases exactly once, and audit contains only metadata/fingerprint.

- [ ] **Step 9: Exercise one controlled real interpretation failure without retry**

Send one intentionally nonsensical non-sensitive input such as:

```text
"zxqvplm qqq 19 banana tensor sideways"
```

If Wolfram returns 501, verify `WolframUninterpretableError` and exactly one local quota increment. If Wolfram interprets it unexpectedly, record the observed success and use the mocked 501 test as the deterministic error proof; do not burn repeated calls trying to force 501.

- [ ] **Step 10: Freeze the campaign fixture hash before qualification**

```bash
python scripts/wolfram_qualification.py list --campaign qualification/wolfram/llm-api-v1.json
```

Record the campaign SHA-256. No task prompt or ground truth may change after the first live benchmark call without restarting the campaign under a new fixture version.

- [ ] **Step 11: Run the 30 primary qualification calls**

For each task ID in fixture order:

1. For the preselected Byte-baseline tasks `WA-03-02`, `WA-04-02`, `WA-04-03`, `WA-05-01`, `WA-05-02`, `WA-08-02`, `WA-10-01`, `WA-10-02`, solve/adjudicate the task before viewing Wolfram's answer and record `byte_baseline_correct`.
2. Invoke `wolfram_query` exactly once with the fixture prompt and appropriate route reason (`DIRECT_COMPUTATION`, `VERIFY_BYTE_HYPOTHESIS`, `GENERATE_TEST_ORACLE`, `CODE_COMPREHENSION`, or `SEARCH_COUNTEREXAMPLE`).
3. Inspect the returned result in the active session; do not persist raw Wolfram text into the qualification ledger.
4. Score against the predeclared ground truth.
5. Record the score with `scripts/wolfram_qualification.py record`.
6. Do not retry a weak/incorrect answer merely to improve its benchmark score.

- [ ] **Step 12: Use at most five deliberate follow-ups**

Follow-ups are allowed only to answer a separate question: whether clarification materially improves an initially partial result. Mark each as `follow_up=true`; never replace the primary score. Stop before five if no additional evidence is useful.

- [ ] **Step 13: Generate the qualification summary**

```bash
python scripts/wolfram_qualification.py summary
```

Byte then records the `byte_plus_wolfram_improved` judgment for meaningful task families using the baseline comparisons and repository-engineering usefulness, not model prestige.

- [ ] **Step 14: Assign exactly one capability profile**

Use:

```text
A — Broad Co-Engineer: threshold met; broader lifecycle may proceed to a new approved implementation gate.
B — Computational Co-Engineer: strong computation/algorithms, insufficient generic coding reliability.
C — Specialist Calculator: useful narrow computation only.
D — Not Worth Integrating Broadly: no material engineering benefit beyond occasional bounded query access.
```

Profile assignment is evidence, not a code path that unlocks tools automatically. Even Profile A requires the separately approved next-phase implementation work for `wolfram_review` lifecycle tools.

- [ ] **Step 15: Write `docs/WOLFRAM-LLM-QUALIFICATION.md` from evidence**

Include implementation commit, campaign hash, real call count, quota count, score summary, per-family averages, coding root-cause rate, unsupported/invented-claim rate, Byte baseline comparison, profile, observed API limitations, and recommended next architectural gate. Do not include the AppID or a bulk copy of raw Wolfram responses.

- [ ] **Step 16: Re-run the full regression gate after qualification documentation**

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

**Gate A — Contracts/config:** Task 1 proves bounded settings, domain types, optional availability, error taxonomy, and fixed dependency scope.

**Gate B — Outbound authority:** Tasks 2 and 8 prove secret denial, path sanitization, no arbitrary HTTP/endpoint choice, and no automatic OX-to-Wolfram forwarding.

**Gate C — Usage discipline:** Task 3 proves atomic conservative local accounting and a 1,800-call soft ceiling without storing provider content.

**Gate D — Provider transport:** Task 4 proves fixed LLM API GET semantics, bearer-only AppID placement, bounded timeouts, typed errors, response/result-link parsing, and zero retries.

**Gate E — Orchestration/provenance:** Task 5 proves Byte-owned routing, metadata-only audit, fallback provenance, policy/quota-before-network ordering, and fail-isolated runtime behavior.

**Gate F — MCP surface:** Task 6 proves exactly one new Phase 1 Wolfram tool, correct open-world annotations, caller-visible argument bounds, and unchanged core startup.

**Gate G — Credential security:** Task 7 proves Windows user-bound DPAPI storage, child-only secret injection, parent restoration, optional configuration, and no secret command-line/state/log exposure.

**Gate H — Adversarial regression:** Task 8 proves leakage, forbidden routing, no-retry, OX separation, and existing filesystem behavior under Wolfram failures.

**Gate I — Qualification integrity:** Task 9 fixes prompts/ground truth/scoring before live evaluation and persists scores only, not raw provider content.

**Gate J — Live acceptance:** Task 10 proves one real canary, controlled error semantics, 30-call campaign, evidence-based capability profile, full regression, and exact-head CI.

---

## Self-Review Checklist and Result

### Spec coverage

- Organizational roles and no OX-Wolfram direct communication: Tasks 5, 8, 10.
- Existing V1.1 filesystem boundary preserved: Tasks 6, 8, 10.
- Phase 1 LLM API only: Tasks 1–10; no local Engine or Full Results implementation appears.
- AppID secrecy/DPAPI: Tasks 1, 4, 7, 8.
- Fixed endpoint/bearer auth/no arbitrary HTTP: Tasks 1, 4, 8.
- `wolfram_query` only: Task 6.
- 6,800 response ceiling and 8,000 input ceiling: Tasks 1, 2, 4, 5.
- 1,800 local soft ceiling and zero retry: Tasks 3–5, 8.
- Tier A/B allowed; Tier C denied before transmission: Tasks 2, 5, 8.
- Machine path sanitization: Tasks 2, 8.
- Metadata-only audit/provenance: Tasks 5, 8.
- No provider-result cache: Tasks 4, 5, 9, 10.
- Qualification before broader review tooling: Tasks 9–10.
- 30 primary + <=5 follow-up call budget: Tasks 9–10.
- Broad authority threshold and capability profiles: Tasks 9–10.
- Full regression and Windows/Ubuntu CI: Tasks 6, 8, 10.

### Placeholder scan

The plan contains no unresolved placeholder markers, no unnamed production interfaces, no generic "add tests" or "handle errors" steps, and no unbounded implementation instruction. Live values intentionally supplied at execution time are the already-existing secret AppID and observed benchmark scores; neither belongs in source control before execution.

### Type/interface consistency

- `WolframSettings`, enums, errors, and `wolfram_settings` fixture are defined in Task 1 before use.
- `PreparedWolframInput` is defined in Task 2 before service use.
- `WolframQuotaLedger` is defined in Task 3 before service use.
- `WolframLLMClient` and `WolframClientResult` exist before orchestration in Task 5.
- `WolframService`/`WolframRuntime` exist before FastMCP registration in Task 6.
- Launcher additions use existing `Protect-ByteMcpCredential`, `Unprotect-ByteMcpCredential`, snapshot, and restore functions rather than a parallel secret subsystem.
- Qualification fixture/scoring types are defined in Task 9 before live use in Task 10.
- No task depends on `byte_mcp.ox` implementation details; `source_finding_id` is an opaque local provenance reference only.

## Execution Handoff

At implementation start, create an isolated worktree using `superpowers:using-git-worktrees`. Execute with `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`, preserving the RED -> GREEN cycles and commit checkpoints above.

Do not start the broader Wolfram review lifecycle, local Wolfram Engine, Full Results API, or any provider-to-provider automation as part of this plan. Those require evidence from the qualification gate and a separate approved design/implementation cycle.