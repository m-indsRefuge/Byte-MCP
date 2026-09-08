# NVIDIA-00 Provider Runtime and Hosted NIM Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-neutral model/outcome contracts and a bounded, non-generative NVIDIA hosted-catalog discovery adapter required by NVIDIA-00, with zero live requests in tests and zero changes to OX or Wolfram provider behavior.

**Architecture:** Add a new `byte_mcp.providers` package for provider-neutral identities, lifecycle state, normalized attempt outcomes, transport-failure categories, and an immutable in-memory registry. Add a separate `byte_mcp.nvidia` package for hosted settings, safe catalog errors, bounded `/v1/models` parsing/client behavior, and the provisional qualification roster. NVIDIA-00 does not expose an MCP tool, does not implement inference, and does not modify the existing OX/Wolfram packages.

**Tech Stack:** Python 3.12+, stdlib dataclasses/enums/regex/datetime/mappingproxy, existing `httpx>=0.28.1,<1`, pytest, Ruff. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-nvidia-provider-runtime-design.md`

## Global Constraints

- Work on `feat/nvidia-provider-n00-discovery`; architectural predecessor is `94ff28810a06b7af2207196ac98c1152cc65b4b1`.
- NVIDIA-00 performs no `/v1/chat/completions`, `/v1/responses`, embedding, reranking, OCR, image, video, speech, or self-hosted NIM call.
- Tests perform zero real NVIDIA requests; every catalog client test uses `httpx.MockTransport` or static data.
- The first real `GET https://integrate.api.nvidia.com/v1/models` remains separately authorization-gated and is outside this plan.
- `NVIDIA_API_KEY` is the only hosted NVIDIA credential. `NGC_API_KEY` must never be treated as a hosted-inference fallback.
- Hosted base URL is exactly `https://integrate.api.nvidia.com/v1`; production settings do not accept an arbitrary override.
- Automatic retries, reconnects, model fallback, and provider fallback are forbidden.
- Catalog discovery is advisory only. It cannot create `QUALIFIED` or `ENABLED` state.
- Provider-neutral code must not import `byte_mcp.ox`, `byte_mcp.nvidia`, or provider-specific exceptions.
- `src/byte_mcp/ox/**` is frozen for NVIDIA-00 and NVIDIA-01 except for a separately approved compatibility repair proven strictly necessary. If execution discovers such a need, stop before mutation and report it.
- `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, and `pyproject.toml` are not modified by NVIDIA-00.
- Historical OX evidence is never modified.
- No API key, authorization header, arbitrary response header, raw exception string, or raw catalog payload may appear in ordinary returned domain objects.
- Full Python tests, `python -m ruff check .`, and `python -m ruff format --check .` must pass before NVIDIA-00 is claimed complete.

---

## File Structure

```text
src/byte_mcp/providers/
  __init__.py
  models.py
  outcomes.py
  registry.py

src/byte_mcp/nvidia/
  __init__.py
  errors.py
  settings.py
  catalog.py
  registry.py

tests/providers/
  __init__.py
  test_contracts.py
  test_registry.py

tests/nvidia/
  __init__.py
  test_settings.py
  test_catalog_parser.py
  test_catalog_client.py
  test_registry.py
  test_security_invariants.py
```

No NVIDIA-00 task edits a production file that existed before this plan.

---

### Task 1: Provider-neutral identity, capability, outcome, and failure contracts

**Files:**
- Create: `src/byte_mcp/providers/__init__.py`
- Create: `src/byte_mcp/providers/models.py`
- Create: `src/byte_mcp/providers/outcomes.py`
- Create: `tests/providers/__init__.py`
- Create: `tests/providers/test_contracts.py`

**Interfaces:**
- Produces: `ProviderIdentity`, `ModelLifecycleState`, `ModelCapabilityProfile`, `validate_model_id`, `ProviderAttemptOutcome`, `ProviderTransportFailureKind`.
- Consumes: stdlib only.

- [ ] **Step 1: Write the failing contract tests**

Create empty `tests/providers/__init__.py`, then create `tests/providers/test_contracts.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from byte_mcp.providers.models import (
    ModelCapabilityProfile,
    ModelLifecycleState,
    ProviderIdentity,
    validate_model_id,
)
from byte_mcp.providers.outcomes import (
    ProviderAttemptOutcome,
    ProviderTransportFailureKind,
)

OBSERVED_AT = "2026-09-08T00:00:00+00:00"


def make_profile(**overrides):
    values = {
        "model_id": "nvidia/example-model",
        "publisher": "nvidia",
        "provider_id": "nvidia-api-catalog",
        "endpoint_family": "openai-chat",
        "input_modalities": ("text",),
        "output_modalities": ("text",),
        "context_window": None,
        "supports_streaming": None,
        "supports_tool_calling": None,
        "supports_reasoning": None,
        "reasoning_dialect": None,
        "hosted_status": "unknown",
        "qualification_state": ModelLifecycleState.DISCOVERED,
        "observed_at": OBSERVED_AT,
    }
    values.update(overrides)
    return ModelCapabilityProfile(**values)


def test_provider_identity_is_immutable_and_validated():
    identity = ProviderIdentity(
        provider_id="nvidia-api-catalog",
        provider_family="nvidia",
        endpoint_family="openai-chat",
    )
    assert identity.provider_id == "nvidia-api-catalog"
    with pytest.raises(FrozenInstanceError):
        identity.provider_id = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "NVIDIA"),
        ("provider_family", "nvidia api"),
        ("endpoint_family", "openai/chat"),
    ],
)
def test_provider_identity_rejects_invalid_slugs(field, value):
    kwargs = {
        "provider_id": "nvidia-api-catalog",
        "provider_family": "nvidia",
        "endpoint_family": "openai-chat",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        ProviderIdentity(**kwargs)


def test_model_profile_preserves_explicit_unknown_capabilities():
    profile = make_profile()
    assert profile.context_window is None
    assert profile.supports_streaming is None
    assert profile.supports_tool_calling is None
    assert profile.supports_reasoning is None
    assert profile.reasoning_dialect is None


@pytest.mark.parametrize(
    "model_id",
    [
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "deepseek-ai/deepseek-v4-pro-0813",
        "moonshotai/kimi-k3",
    ],
)
def test_validate_model_id_accepts_hosted_catalog_shape(model_id):
    assert validate_model_id(model_id) == model_id


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "missing-namespace",
        "/missing-publisher",
        "publisher/",
        "publisher/model with space",
        "publisher/model/extra-segment",
    ],
)
def test_validate_model_id_rejects_invalid_shape(model_id):
    with pytest.raises(ValueError):
        validate_model_id(model_id)


def test_context_window_must_be_positive_when_known():
    with pytest.raises(ValueError):
        make_profile(context_window=0)


def test_observed_at_must_be_timezone_aware_iso8601():
    with pytest.raises(ValueError):
        make_profile(observed_at="2026-09-08T00:00:00")


def test_attempt_outcome_values_are_frozen_contract():
    assert [item.value for item in ProviderAttemptOutcome] == [
        "NOT_SENT",
        "REJECTED",
        "COMPLETED",
        "OUTCOME_UNKNOWN",
    ]


def test_transport_failure_values_match_frozen_contract():
    assert [item.value for item in ProviderTransportFailureKind] == [
        "ABSOLUTE_DEADLINE",
        "READ_TIMEOUT",
        "READ_ERROR",
        "WRITE_TIMEOUT",
        "WRITE_ERROR",
        "REMOTE_PROTOCOL_ERROR",
        "HTTP_TRANSPORT_ERROR",
        "CONNECT_TIMEOUT",
        "CONNECT_ERROR",
        "POOL_TIMEOUT",
    ]
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
python -m pytest tests/providers/test_contracts.py -q
```

Expected: collection fails because `byte_mcp.providers` does not exist.

- [ ] **Step 3: Implement the provider-neutral contracts**

Create `src/byte_mcp/providers/outcomes.py`:

```python
"""Provider-neutral attempt outcomes and transport-failure categories."""

from enum import StrEnum


class ProviderAttemptOutcome(StrEnum):
    NOT_SENT = "NOT_SENT"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class ProviderTransportFailureKind(StrEnum):
    ABSOLUTE_DEADLINE = "ABSOLUTE_DEADLINE"
    READ_TIMEOUT = "READ_TIMEOUT"
    READ_ERROR = "READ_ERROR"
    WRITE_TIMEOUT = "WRITE_TIMEOUT"
    WRITE_ERROR = "WRITE_ERROR"
    REMOTE_PROTOCOL_ERROR = "REMOTE_PROTOCOL_ERROR"
    HTTP_TRANSPORT_ERROR = "HTTP_TRANSPORT_ERROR"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    CONNECT_ERROR = "CONNECT_ERROR"
    POOL_TIMEOUT = "POOL_TIMEOUT"
```

Create `src/byte_mcp/providers/models.py`:

```python
"""Provider-neutral model identity and lifecycle contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODEL_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,191}$"
)
_PUBLISHER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODALITY = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_STATUS = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _require_slug(value: object, field: str) -> str:
    if not isinstance(value, str) or _SLUG.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def validate_model_id(value: object) -> str:
    if not isinstance(value, str) or _MODEL_ID.fullmatch(value) is None:
        raise ValueError("model_id is invalid")
    return value


def _require_publisher(value: object) -> str:
    if not isinstance(value, str) or _PUBLISHER.fullmatch(value) is None:
        raise ValueError("publisher is invalid")
    return value


def _require_modalities(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field} must be a tuple")
    if not all(isinstance(item, str) and _MODALITY.fullmatch(item) for item in value):
        raise ValueError(f"{field} contains an invalid modality")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} contains duplicates")
    return value


def _require_optional_bool(value: object, field: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field} must be bool or None")
    return value


def _require_observed_at(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("observed_at is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("observed_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value


class ModelLifecycleState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CHARACTERIZED = "CHARACTERIZED"
    QUALIFIED = "QUALIFIED"
    ENABLED = "ENABLED"
    UNAVAILABLE = "UNAVAILABLE"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider_id: str
    provider_family: str
    endpoint_family: str

    def __post_init__(self) -> None:
        _require_slug(self.provider_id, "provider_id")
        _require_slug(self.provider_family, "provider_family")
        _require_slug(self.endpoint_family, "endpoint_family")


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
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
    qualification_state: ModelLifecycleState
    observed_at: str

    def __post_init__(self) -> None:
        validate_model_id(self.model_id)
        _require_publisher(self.publisher)
        _require_slug(self.provider_id, "provider_id")
        _require_slug(self.endpoint_family, "endpoint_family")
        _require_modalities(self.input_modalities, "input_modalities")
        _require_modalities(self.output_modalities, "output_modalities")
        if self.context_window is not None and (
            not isinstance(self.context_window, int)
            or isinstance(self.context_window, bool)
            or self.context_window <= 0
        ):
            raise ValueError("context_window must be a positive integer or None")
        _require_optional_bool(self.supports_streaming, "supports_streaming")
        _require_optional_bool(self.supports_tool_calling, "supports_tool_calling")
        _require_optional_bool(self.supports_reasoning, "supports_reasoning")
        if self.reasoning_dialect is not None:
            _require_slug(self.reasoning_dialect, "reasoning_dialect")
        if not isinstance(self.hosted_status, str) or _STATUS.fullmatch(self.hosted_status) is None:
            raise ValueError("hosted_status is invalid")
        if not isinstance(self.qualification_state, ModelLifecycleState):
            raise ValueError("qualification_state is invalid")
        _require_observed_at(self.observed_at)
```

Create `src/byte_mcp/providers/__init__.py`:

```python
"""Provider-neutral Byte-MCP contracts."""

from .models import (
    ModelCapabilityProfile,
    ModelLifecycleState,
    ProviderIdentity,
    validate_model_id,
)
from .outcomes import ProviderAttemptOutcome, ProviderTransportFailureKind

__all__ = [
    "ModelCapabilityProfile",
    "ModelLifecycleState",
    "ProviderAttemptOutcome",
    "ProviderIdentity",
    "ProviderTransportFailureKind",
    "validate_model_id",
]
```

- [ ] **Step 4: Run focused tests and Ruff**

```powershell
python -m pytest tests/providers/test_contracts.py -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

Expected: all pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/byte_mcp/providers tests/providers
git commit -m "feat: add provider-neutral model contracts"
```

---

### Task 2: Immutable model registry and explicit lifecycle transitions

**Files:**
- Create: `src/byte_mcp/providers/registry.py`
- Create: `tests/providers/test_registry.py`
- Modify: `src/byte_mcp/providers/__init__.py`

**Interfaces:**
- Consumes: `ModelCapabilityProfile`, `ModelLifecycleState`.
- Produces: `ModelRegistry`, `transition_model_profile`.

- [ ] **Step 1: Write failing registry tests**

Create `tests/providers/test_registry.py`:

```python
import pytest

from byte_mcp.providers.models import ModelCapabilityProfile, ModelLifecycleState
from byte_mcp.providers.registry import ModelRegistry, transition_model_profile

OBSERVED_AT = "2026-09-08T00:00:00+00:00"
LATER = "2026-09-08T01:00:00+00:00"


def profile(state=ModelLifecycleState.DISCOVERED):
    return ModelCapabilityProfile(
        model_id="nvidia/example-model",
        publisher="nvidia",
        provider_id="nvidia-api-catalog",
        endpoint_family="openai-chat",
        input_modalities=("text",),
        output_modalities=("text",),
        context_window=None,
        supports_streaming=None,
        supports_tool_calling=None,
        supports_reasoning=None,
        reasoning_dialect=None,
        hosted_status="unknown",
        qualification_state=state,
        observed_at=OBSERVED_AT,
    )


def test_registry_is_deterministic_and_read_only():
    registry = ModelRegistry([profile()])
    assert registry.get("nvidia/example-model") == profile()
    assert registry.all() == (profile(),)
    assert registry.by_state(ModelLifecycleState.DISCOVERED) == (profile(),)
    assert registry.by_state(ModelLifecycleState.QUALIFIED) == ()


def test_registry_rejects_duplicate_model_identity():
    with pytest.raises(ValueError):
        ModelRegistry([profile(), profile()])


def test_discovered_cannot_jump_directly_to_qualified():
    with pytest.raises(ValueError):
        transition_model_profile(
            profile(),
            ModelLifecycleState.QUALIFIED,
            observed_at=LATER,
        )


def test_forward_lifecycle_requires_explicit_steps():
    characterized = transition_model_profile(
        profile(), ModelLifecycleState.CHARACTERIZED, observed_at=LATER
    )
    qualified = transition_model_profile(
        characterized,
        ModelLifecycleState.QUALIFIED,
        observed_at="2026-09-08T02:00:00+00:00",
    )
    enabled = transition_model_profile(
        qualified,
        ModelLifecycleState.ENABLED,
        observed_at="2026-09-08T03:00:00+00:00",
    )
    assert enabled.qualification_state is ModelLifecycleState.ENABLED


def test_unavailable_reentry_forces_rediscovery():
    unavailable = transition_model_profile(
        profile(ModelLifecycleState.CHARACTERIZED),
        ModelLifecycleState.UNAVAILABLE,
        observed_at=LATER,
    )
    with pytest.raises(ValueError):
        transition_model_profile(
            unavailable,
            ModelLifecycleState.QUALIFIED,
            observed_at="2026-09-08T02:00:00+00:00",
        )
    rediscovered = transition_model_profile(
        unavailable,
        ModelLifecycleState.DISCOVERED,
        observed_at="2026-09-08T02:00:00+00:00",
    )
    assert rediscovered.qualification_state is ModelLifecycleState.DISCOVERED


def test_deprecated_cannot_be_reenabled_directly():
    deprecated = transition_model_profile(
        profile(ModelLifecycleState.QUALIFIED),
        ModelLifecycleState.DEPRECATED,
        observed_at=LATER,
    )
    with pytest.raises(ValueError):
        transition_model_profile(
            deprecated,
            ModelLifecycleState.ENABLED,
            observed_at="2026-09-08T02:00:00+00:00",
        )
```

- [ ] **Step 2: Run registry tests and verify RED**

```powershell
python -m pytest tests/providers/test_registry.py -q
```

Expected: import fails because `byte_mcp.providers.registry` does not exist.

- [ ] **Step 3: Implement registry and transition policy**

Create `src/byte_mcp/providers/registry.py`:

```python
"""Immutable model registry and explicit lifecycle transitions."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Iterable

from .models import ModelCapabilityProfile, ModelLifecycleState

_ALLOWED_TRANSITIONS = {
    ModelLifecycleState.DISCOVERED: frozenset(
        {
            ModelLifecycleState.CHARACTERIZED,
            ModelLifecycleState.UNAVAILABLE,
            ModelLifecycleState.DEPRECATED,
            ModelLifecycleState.DISABLED,
        }
    ),
    ModelLifecycleState.CHARACTERIZED: frozenset(
        {
            ModelLifecycleState.QUALIFIED,
            ModelLifecycleState.UNAVAILABLE,
            ModelLifecycleState.DEPRECATED,
            ModelLifecycleState.DISABLED,
        }
    ),
    ModelLifecycleState.QUALIFIED: frozenset(
        {
            ModelLifecycleState.ENABLED,
            ModelLifecycleState.UNAVAILABLE,
            ModelLifecycleState.DEPRECATED,
            ModelLifecycleState.DISABLED,
        }
    ),
    ModelLifecycleState.ENABLED: frozenset(
        {
            ModelLifecycleState.UNAVAILABLE,
            ModelLifecycleState.DEPRECATED,
            ModelLifecycleState.DISABLED,
        }
    ),
    ModelLifecycleState.UNAVAILABLE: frozenset(
        {
            ModelLifecycleState.DISCOVERED,
            ModelLifecycleState.DEPRECATED,
            ModelLifecycleState.DISABLED,
        }
    ),
    ModelLifecycleState.DEPRECATED: frozenset({ModelLifecycleState.DISABLED}),
    ModelLifecycleState.DISABLED: frozenset({ModelLifecycleState.DISCOVERED}),
}


class ModelRegistry:
    """Read-only deterministic view of Byte-MCP-owned model profiles."""

    def __init__(self, profiles: Iterable[ModelCapabilityProfile]) -> None:
        items: dict[str, ModelCapabilityProfile] = {}
        for item in profiles:
            if not isinstance(item, ModelCapabilityProfile):
                raise ValueError("registry entry is invalid")
            if item.model_id in items:
                raise ValueError("duplicate model_id")
            items[item.model_id] = item
        self._profiles = MappingProxyType(dict(sorted(items.items())))

    def get(self, model_id: str) -> ModelCapabilityProfile | None:
        return self._profiles.get(model_id)

    def all(self) -> tuple[ModelCapabilityProfile, ...]:
        return tuple(self._profiles.values())

    def by_state(self, state: ModelLifecycleState) -> tuple[ModelCapabilityProfile, ...]:
        if not isinstance(state, ModelLifecycleState):
            raise ValueError("state is invalid")
        return tuple(
            item for item in self._profiles.values() if item.qualification_state is state
        )


def transition_model_profile(
    profile: ModelCapabilityProfile,
    target_state: ModelLifecycleState,
    *,
    observed_at: str,
) -> ModelCapabilityProfile:
    if not isinstance(profile, ModelCapabilityProfile):
        raise ValueError("profile is invalid")
    if not isinstance(target_state, ModelLifecycleState):
        raise ValueError("target_state is invalid")
    if target_state not in _ALLOWED_TRANSITIONS[profile.qualification_state]:
        raise ValueError(
            f"invalid lifecycle transition: {profile.qualification_state.value} -> "
            f"{target_state.value}"
        )
    return replace(profile, qualification_state=target_state, observed_at=observed_at)
```

Replace `src/byte_mcp/providers/__init__.py` with:

```python
"""Provider-neutral Byte-MCP contracts."""

from .models import (
    ModelCapabilityProfile,
    ModelLifecycleState,
    ProviderIdentity,
    validate_model_id,
)
from .outcomes import ProviderAttemptOutcome, ProviderTransportFailureKind
from .registry import ModelRegistry, transition_model_profile

__all__ = [
    "ModelCapabilityProfile",
    "ModelLifecycleState",
    "ModelRegistry",
    "ProviderAttemptOutcome",
    "ProviderIdentity",
    "ProviderTransportFailureKind",
    "transition_model_profile",
    "validate_model_id",
]
```

- [ ] **Step 4: Run provider tests and Ruff**

```powershell
python -m pytest tests/providers -q
python -m ruff check src/byte_mcp/providers tests/providers
python -m ruff format --check src/byte_mcp/providers tests/providers
```

Expected: all pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/byte_mcp/providers tests/providers/test_registry.py
git commit -m "feat: add provider model lifecycle registry"
```

---

### Task 3: NVIDIA hosted settings and bounded catalog error vocabulary

**Files:**
- Create: `src/byte_mcp/nvidia/__init__.py`
- Create: `src/byte_mcp/nvidia/errors.py`
- Create: `src/byte_mcp/nvidia/settings.py`
- Create: `tests/nvidia/__init__.py`
- Create: `tests/nvidia/test_settings.py`

**Interfaces:**
- Produces: `NvidiaHostedSettings`, `NvidiaCatalogError`, `NvidiaCatalogFailureKind`, `NVIDIA_HOSTED_BASE_URL`.
- Consumes: `ByteMCPError`; no OX/Wolfram imports.

- [ ] **Step 1: Write failing settings tests**

Create empty `tests/nvidia/__init__.py`, then create `tests/nvidia/test_settings.py`:

```python
import pytest

from byte_mcp.nvidia.settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings


def test_missing_hosted_key_is_allowed(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NGC_API_KEY", raising=False)
    assert NvidiaHostedSettings.load().api_key is None


def test_ngc_key_is_not_used_as_hosted_fallback(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NGC_API_KEY", "NGC-SENTINEL")
    settings = NvidiaHostedSettings.load()
    assert settings.api_key is None
    assert "NGC-SENTINEL" not in repr(settings)


def test_settings_repr_redacts_hosted_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "NVIDIA-SENTINEL-SECRET")
    settings = NvidiaHostedSettings.load()
    assert repr(settings) == "NvidiaHostedSettings(api_key_configured=True)"
    assert "NVIDIA-SENTINEL-SECRET" not in repr(settings)


def test_blank_direct_key_is_rejected():
    with pytest.raises(ValueError):
        NvidiaHostedSettings(api_key=" ")


def test_hosted_origin_is_exact_and_not_environment_overridable(monkeypatch):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_BASE_URL", "https://example.invalid/v1")
    settings = NvidiaHostedSettings.load()
    assert settings.base_url == NVIDIA_HOSTED_BASE_URL
    assert settings.base_url == "https://integrate.api.nvidia.com/v1"


def test_constructor_rejects_arbitrary_hosted_origin():
    with pytest.raises(ValueError):
        NvidiaHostedSettings(api_key=None, base_url="https://example.invalid/v1")


@pytest.mark.parametrize("value", ["0", "61", "not-an-int"])
def test_catalog_timeout_is_bounded(monkeypatch, value):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        NvidiaHostedSettings.load()


def test_catalog_timeout_default(monkeypatch):
    monkeypatch.delenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", raising=False)
    assert NvidiaHostedSettings.load().catalog_timeout_seconds == 10
```

- [ ] **Step 2: Run settings tests and verify RED**

```powershell
python -m pytest tests/nvidia/test_settings.py -q
```

Expected: import fails because `byte_mcp.nvidia` does not exist.

- [ ] **Step 3: Implement safe NVIDIA errors**

Create `src/byte_mcp/nvidia/errors.py`:

```python
"""Bounded NVIDIA catalog error classification."""

from enum import StrEnum

from byte_mcp.errors import ByteMCPError


class NvidiaCatalogFailureKind(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    REQUEST = "REQUEST"
    RATE_LIMIT = "RATE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"
    TRANSPORT = "TRANSPORT"
    PROTOCOL = "PROTOCOL"


class NvidiaCatalogError(ByteMCPError):
    def __init__(self, kind: NvidiaCatalogFailureKind) -> None:
        if not isinstance(kind, NvidiaCatalogFailureKind):
            raise ValueError("kind is invalid")
        self.kind = kind
        super().__init__(kind.value)
```

- [ ] **Step 4: Implement hosted settings**

Create `src/byte_mcp/nvidia/settings.py`:

```python
"""Hosted NVIDIA API Catalog settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

NVIDIA_HOSTED_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaHostedSettings:
    api_key: str | None
    base_url: str = NVIDIA_HOSTED_BASE_URL
    catalog_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if self.api_key is not None and (
            not isinstance(self.api_key, str)
            or not self.api_key
            or self.api_key != self.api_key.strip()
        ):
            raise ValueError("api_key is invalid")
        if self.base_url != NVIDIA_HOSTED_BASE_URL:
            raise ValueError("NVIDIA hosted base_url is invalid")
        if not isinstance(self.catalog_timeout_seconds, int) or isinstance(
            self.catalog_timeout_seconds, bool
        ):
            raise ValueError("catalog_timeout_seconds is invalid")
        if not 1 <= self.catalog_timeout_seconds <= 60:
            raise ValueError("catalog_timeout_seconds must be between 1 and 60")

    def __repr__(self) -> str:
        return f"NvidiaHostedSettings(api_key_configured={self.api_key is not None})"

    @classmethod
    def load(cls) -> "NvidiaHostedSettings":
        key = os.getenv("NVIDIA_API_KEY", "").strip() or None
        return cls(
            api_key=key,
            catalog_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", 10, 1, 60
            ),
        )
```

Create `src/byte_mcp/nvidia/__init__.py`:

```python
"""NVIDIA API Catalog integration primitives."""

from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaHostedSettings",
]
```

- [ ] **Step 5: Run settings tests and Ruff**

```powershell
python -m pytest tests/nvidia/test_settings.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia/test_settings.py
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia/test_settings.py
```

Expected: all pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add src/byte_mcp/nvidia tests/nvidia
git commit -m "feat: add NVIDIA hosted settings"
```

---

### Task 4: Bounded NVIDIA catalog parser

**Files:**
- Create: `src/byte_mcp/nvidia/catalog.py`
- Create: `tests/nvidia/test_catalog_parser.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `validate_model_id`, NVIDIA catalog error types.
- Produces: `NvidiaCatalogSnapshot`, `parse_catalog_payload`.
- Adds no HTTP execution.

- [ ] **Step 1: Write failing parser tests**

Create `tests/nvidia/test_catalog_parser.py`:

```python
import pytest

from byte_mcp.nvidia.catalog import NvidiaCatalogSnapshot, parse_catalog_payload
from byte_mcp.nvidia.errors import NvidiaCatalogError, NvidiaCatalogFailureKind

OBSERVED_AT = "2026-09-08T00:00:00+00:00"


def test_parser_returns_only_bounded_model_ids():
    payload = {
        "object": "list",
        "data": [
            {
                "id": "nvidia/nemotron-3.5-lightning-30b-a3b",
                "object": "model",
                "owned_by": "ignored",
                "arbitrary": {"nested": "ignored"},
            },
            {"id": "deepseek-ai/deepseek-v4-pro-0813", "object": "model"},
        ],
        "secret-looking-field": "must-not-propagate",
    }
    snapshot = parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert snapshot == NvidiaCatalogSnapshot(
        model_ids=(
            "deepseek-ai/deepseek-v4-pro-0813",
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        ),
        observed_at=OBSERVED_AT,
    )
    assert "owned_by" not in repr(snapshot)
    assert "secret-looking-field" not in repr(snapshot)


def test_parser_deduplicates_model_ids_deterministically():
    payload = {
        "data": [
            {"id": "nvidia/example-model"},
            {"id": "nvidia/example-model"},
        ]
    }
    snapshot = parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert snapshot.model_ids == ("nvidia/example-model",)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"data": "not-a-list"},
        {"data": ["not-an-object"]},
        {"data": [{}]},
        {"data": [{"id": "bad model id"}]},
    ],
)
def test_parser_fails_closed_on_malformed_envelopes(payload):
    with pytest.raises(NvidiaCatalogError) as excinfo:
        parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL


def test_parser_rejects_more_than_1000_models():
    payload = {"data": [{"id": f"nvidia/model-{index}"} for index in range(1001)]}
    with pytest.raises(NvidiaCatalogError) as excinfo:
        parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL
```

- [ ] **Step 2: Run parser tests and verify RED**

```powershell
python -m pytest tests/nvidia/test_catalog_parser.py -q
```

Expected: import fails because `byte_mcp.nvidia.catalog` does not exist.

- [ ] **Step 3: Implement parser and snapshot**

Create `src/byte_mcp/nvidia/catalog.py` exactly with the parser-only imports used in this task:

```python
"""Bounded NVIDIA hosted model-catalog parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from byte_mcp.providers.models import validate_model_id

from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind

_MAX_CATALOG_BYTES = 1_000_000
_MAX_CATALOG_MODELS = 1_000


@dataclass(frozen=True, slots=True)
class NvidiaCatalogSnapshot:
    model_ids: tuple[str, ...]
    observed_at: str


def _protocol_error() -> NvidiaCatalogError:
    return NvidiaCatalogError(NvidiaCatalogFailureKind.PROTOCOL)


def parse_catalog_payload(
    payload: object,
    *,
    observed_at: str,
) -> NvidiaCatalogSnapshot:
    if not isinstance(payload, Mapping):
        raise _protocol_error()
    data = payload.get("data")
    if not isinstance(data, list) or len(data) > _MAX_CATALOG_MODELS:
        raise _protocol_error()

    model_ids: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            raise _protocol_error()
        try:
            model_id = validate_model_id(item.get("id"))
        except ValueError:
            raise _protocol_error() from None
        model_ids.add(model_id)

    try:
        parsed_time = datetime.fromisoformat(observed_at)
    except (TypeError, ValueError):
        raise _protocol_error() from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise _protocol_error()

    return NvidiaCatalogSnapshot(
        model_ids=tuple(sorted(model_ids)),
        observed_at=observed_at,
    )
```

Replace `src/byte_mcp/nvidia/__init__.py` with:

```python
"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogSnapshot, parse_catalog_payload
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaHostedSettings",
    "parse_catalog_payload",
]
```

- [ ] **Step 4: Run parser tests and Ruff**

```powershell
python -m pytest tests/nvidia/test_catalog_parser.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia/test_catalog_parser.py
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia/test_catalog_parser.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/byte_mcp/nvidia tests/nvidia/test_catalog_parser.py
git commit -m "feat: parse NVIDIA hosted model catalog"
```

---

### Task 5: One-GET NVIDIA catalog client with zero retries

**Files:**
- Modify: `src/byte_mcp/nvidia/catalog.py`
- Create: `tests/nvidia/test_catalog_client.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `NvidiaHostedSettings`, `NvidiaCatalogError`, `parse_catalog_payload`.
- Produces: `NvidiaCatalogClient.discover() -> NvidiaCatalogSnapshot`.
- Test seam: `transport: httpx.BaseTransport | None = None`.

- [ ] **Step 1: Write failing one-request client tests**

Create `tests/nvidia/test_catalog_client.py`:

```python
import json

import httpx
import pytest

from byte_mcp.nvidia.catalog import NvidiaCatalogClient
from byte_mcp.nvidia.errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from byte_mcp.nvidia.settings import NvidiaHostedSettings

KEY = "NVIDIA-SENTINEL-SECRET"


def settings(api_key=KEY):
    return NvidiaHostedSettings(api_key=api_key, catalog_timeout_seconds=10)


def test_discover_makes_exactly_one_get_to_models_with_internal_bearer_header():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "nvidia/example-model"}]})

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    snapshot = client.discover()
    assert snapshot.model_ids == ("nvidia/example-model",)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://integrate.api.nvidia.com/v1/models"
    assert requests[0].headers["Authorization"] == f"Bearer {KEY}"


def test_missing_key_fails_before_transport():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    client = NvidiaCatalogClient(settings(None), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.CONFIGURATION
    assert calls == 0


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (302, NvidiaCatalogFailureKind.REQUEST),
        (400, NvidiaCatalogFailureKind.REQUEST),
        (401, NvidiaCatalogFailureKind.AUTHENTICATION),
        (403, NvidiaCatalogFailureKind.PERMISSION),
        (404, NvidiaCatalogFailureKind.UNAVAILABLE),
        (429, NvidiaCatalogFailureKind.RATE_LIMIT),
        (500, NvidiaCatalogFailureKind.UNAVAILABLE),
        (503, NvidiaCatalogFailureKind.UNAVAILABLE),
    ],
)
def test_http_rejections_are_bounded_and_never_retried(status, kind):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            json={"error": {"message": "provider text must not propagate", "secret": KEY}},
        )

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is kind
    assert str(excinfo.value) == kind.value
    assert KEY not in str(excinfo.value)
    assert calls == 1


def test_malformed_json_is_protocol_failure_without_retry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"not-json")

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL
    assert calls == 1


def test_catalog_response_body_is_capped_at_one_megabyte():
    oversized = b"{" + (b"x" * 1_000_001) + b"}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized)

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL


def test_transport_exception_is_safe_and_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("SENTINEL-TRANSPORT-TEXT", request=request)

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NvidiaCatalogError) as excinfo:
        client.discover()
    assert excinfo.value.kind is NvidiaCatalogFailureKind.TRANSPORT
    assert "SENTINEL-TRANSPORT-TEXT" not in str(excinfo.value)
    assert calls == 1


def test_unknown_response_headers_are_not_returned():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-sentinel-secret": "SERVER-HEADER-SECRET"},
            content=json.dumps({"data": [{"id": "nvidia/example-model"}]}).encode(),
        )

    client = NvidiaCatalogClient(settings(), transport=httpx.MockTransport(handler))
    snapshot = client.discover()
    assert "SERVER-HEADER-SECRET" not in repr(snapshot)
```

- [ ] **Step 2: Run client tests and verify RED**

```powershell
python -m pytest tests/nvidia/test_catalog_client.py -q
```

Expected: import fails because `NvidiaCatalogClient` is not defined.

- [ ] **Step 3: Extend the catalog module with the one-GET client**

Add these imports to `src/byte_mcp/nvidia/catalog.py`:

```python
import json
from datetime import UTC, datetime

import httpx

from .settings import NvidiaHostedSettings
```

The resulting datetime import must be `from datetime import UTC, datetime`, replacing the Task 4 datetime-only import.

Add:

```python
def _http_failure(status_code: int) -> NvidiaCatalogError:
    if status_code == 401:
        kind = NvidiaCatalogFailureKind.AUTHENTICATION
    elif status_code == 403:
        kind = NvidiaCatalogFailureKind.PERMISSION
    elif status_code == 404:
        kind = NvidiaCatalogFailureKind.UNAVAILABLE
    elif status_code == 429:
        kind = NvidiaCatalogFailureKind.RATE_LIMIT
    elif status_code >= 500:
        kind = NvidiaCatalogFailureKind.UNAVAILABLE
    else:
        kind = NvidiaCatalogFailureKind.REQUEST
    return NvidiaCatalogError(kind)


class NvidiaCatalogClient:
    """Perform one bounded hosted catalog GET with no retry or inference behavior."""

    def __init__(
        self,
        settings: NvidiaHostedSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(settings, NvidiaHostedSettings):
            raise ValueError("settings is invalid")
        self._settings = settings
        self._transport = transport

    def __repr__(self) -> str:
        return (
            "NvidiaCatalogClient("
            f"api_key_configured={self._settings.api_key is not None})"
        )

    def discover(self) -> NvidiaCatalogSnapshot:
        if self._settings.api_key is None:
            raise NvidiaCatalogError(NvidiaCatalogFailureKind.CONFIGURATION)

        url = f"{self._settings.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(float(self._settings.catalog_timeout_seconds))

        try:
            with httpx.Client(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code >= 300:
                        raise _http_failure(response.status_code)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > _MAX_CATALOG_BYTES:
                            raise _protocol_error()
                        body.extend(chunk)
        except NvidiaCatalogError:
            raise
        except (
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.PoolTimeout,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteTimeout,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.HTTPError,
        ):
            raise NvidiaCatalogError(NvidiaCatalogFailureKind.TRANSPORT) from None

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _protocol_error() from None

        return parse_catalog_payload(
            payload,
            observed_at=datetime.now(UTC).isoformat(),
        )
```

Replace `src/byte_mcp/nvidia/__init__.py` with:

```python
"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaHostedSettings",
    "parse_catalog_payload",
]
```

Do not add a retry loop, retry library, alternate URL, POST, reconnect/resume, or fallback path.

- [ ] **Step 4: Run parser/client tests and Ruff**

```powershell
python -m pytest tests/nvidia/test_catalog_parser.py tests/nvidia/test_catalog_client.py -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia
```

Expected: all pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src/byte_mcp/nvidia tests/nvidia/test_catalog_client.py
git commit -m "feat: add bounded NVIDIA catalog discovery client"
```

---

### Task 6: Provisional NVIDIA qualification roster without routing authority

**Files:**
- Create: `src/byte_mcp/nvidia/registry.py`
- Create: `tests/nvidia/test_registry.py`
- Modify: `src/byte_mcp/nvidia/__init__.py`

**Interfaces:**
- Consumes: `ProviderIdentity`, `ModelCapabilityProfile`, `ModelLifecycleState`, `ModelRegistry`.
- Produces: `NVIDIA_PROVIDER`, `NvidiaQualificationCandidate`, `initial_qualification_candidates`, `initial_model_registry`.
- No client/transport branch is keyed by model ID.

- [ ] **Step 1: Write failing roster tests**

Create `tests/nvidia/test_registry.py`:

```python
from byte_mcp.nvidia.registry import (
    NVIDIA_PROVIDER,
    initial_model_registry,
    initial_qualification_candidates,
)
from byte_mcp.providers.models import ModelLifecycleState

EXPECTED_MODELS = {
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "deepseek-ai/deepseek-v4-pro-0813",
    "moonshotai/kimi-k3",
}


def test_nvidia_provider_identity_distinguishes_gateway_from_model_publisher():
    assert NVIDIA_PROVIDER.provider_id == "nvidia-api-catalog"
    assert NVIDIA_PROVIDER.provider_family == "nvidia"
    assert NVIDIA_PROVIDER.endpoint_family == "openai-chat"


def test_initial_candidates_are_only_discovered_candidates():
    candidates = initial_qualification_candidates()
    assert {candidate.profile.model_id for candidate in candidates} == EXPECTED_MODELS
    assert all(
        candidate.profile.qualification_state is ModelLifecycleState.DISCOVERED
        for candidate in candidates
    )
    assert all(candidate.profile.provider_id == "nvidia-api-catalog" for candidate in candidates)


def test_initial_registry_contains_no_qualified_or_enabled_model():
    registry = initial_model_registry()
    assert {profile.model_id for profile in registry.all()} == EXPECTED_MODELS
    assert registry.by_state(ModelLifecycleState.QUALIFIED) == ()
    assert registry.by_state(ModelLifecycleState.ENABLED) == ()


def test_candidate_roles_are_explicit_and_distinct():
    roles = {
        candidate.profile.model_id: candidate.intended_role
        for candidate in initial_qualification_candidates()
    }
    assert roles == {
        "nvidia/nemotron-3.5-lightning-30b-a3b": "routine-review",
        "nvidia/nemotron-3-ultra-550b-a55b": "deep-review",
        "deepseek-ai/deepseek-v4-pro-0813": "independent-coding-review",
        "moonshotai/kimi-k3": "long-horizon-challenger",
    }
```

- [ ] **Step 2: Run roster tests and verify RED**

```powershell
python -m pytest tests/nvidia/test_registry.py -q
```

Expected: import fails because `byte_mcp.nvidia.registry` does not exist.

- [ ] **Step 3: Implement provisional roster**

Create `src/byte_mcp/nvidia/registry.py`:

```python
"""Provisional NVIDIA model qualification roster."""

from __future__ import annotations

from dataclasses import dataclass

from byte_mcp.providers.models import (
    ModelCapabilityProfile,
    ModelLifecycleState,
    ProviderIdentity,
)
from byte_mcp.providers.registry import ModelRegistry

NVIDIA_PROVIDER = ProviderIdentity(
    provider_id="nvidia-api-catalog",
    provider_family="nvidia",
    endpoint_family="openai-chat",
)

_INITIAL_OBSERVED_AT = "2026-09-08T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class NvidiaQualificationCandidate:
    profile: ModelCapabilityProfile
    intended_role: str


def _candidate(model_id: str, publisher: str, intended_role: str) -> NvidiaQualificationCandidate:
    return NvidiaQualificationCandidate(
        profile=ModelCapabilityProfile(
            model_id=model_id,
            publisher=publisher,
            provider_id=NVIDIA_PROVIDER.provider_id,
            endpoint_family=NVIDIA_PROVIDER.endpoint_family,
            input_modalities=("text",),
            output_modalities=("text",),
            context_window=None,
            supports_streaming=None,
            supports_tool_calling=None,
            supports_reasoning=None,
            reasoning_dialect=None,
            hosted_status="candidate",
            qualification_state=ModelLifecycleState.DISCOVERED,
            observed_at=_INITIAL_OBSERVED_AT,
        ),
        intended_role=intended_role,
    )


_INITIAL_CANDIDATES = (
    _candidate(
        "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia", "routine-review"
    ),
    _candidate(
        "nvidia/nemotron-3-ultra-550b-a55b", "nvidia", "deep-review"
    ),
    _candidate(
        "deepseek-ai/deepseek-v4-pro-0813",
        "deepseek-ai",
        "independent-coding-review",
    ),
    _candidate(
        "moonshotai/kimi-k3", "moonshotai", "long-horizon-challenger"
    ),
)


def initial_qualification_candidates() -> tuple[NvidiaQualificationCandidate, ...]:
    return _INITIAL_CANDIDATES


def initial_model_registry() -> ModelRegistry:
    return ModelRegistry(candidate.profile for candidate in _INITIAL_CANDIDATES)
```

Replace `src/byte_mcp/nvidia/__init__.py` with:

```python
"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .registry import (
    NVIDIA_PROVIDER,
    NvidiaQualificationCandidate,
    initial_model_registry,
    initial_qualification_candidates,
)
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NVIDIA_PROVIDER",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaHostedSettings",
    "NvidiaQualificationCandidate",
    "initial_model_registry",
    "initial_qualification_candidates",
    "parse_catalog_payload",
]
```

- [ ] **Step 4: Run NVIDIA tests and Ruff**

```powershell
python -m pytest tests/nvidia -q
python -m ruff check src/byte_mcp/nvidia tests/nvidia
python -m ruff format --check src/byte_mcp/nvidia tests/nvidia
```

Expected: all pass with zero live network requests.

- [ ] **Step 5: Commit Task 6**

```powershell
git add src/byte_mcp/nvidia tests/nvidia/test_registry.py
git commit -m "feat: add NVIDIA qualification candidates"
```

---

### Task 7: Security/isolation regression gate and NVIDIA-00 completion verification

**Files:**
- Create: `tests/nvidia/test_security_invariants.py`
- No production modification expected.

**Interfaces:**
- Verifies: secret redaction, import isolation, no automatic qualification, no OX/Wolfram dependency, no accidental inference route.

- [ ] **Step 1: Write security/isolation tests**

Create `tests/nvidia/test_security_invariants.py`:

```python
import importlib
import inspect

import httpx

from byte_mcp.nvidia.catalog import NvidiaCatalogClient
from byte_mcp.nvidia.registry import initial_model_registry
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers.models import ModelLifecycleState

KEY = "NVIDIA-SECURITY-SENTINEL"


def test_invalid_nvidia_environment_does_not_break_existing_provider_modules(monkeypatch):
    monkeypatch.setenv("BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", "invalid")
    for module_name in (
        "byte_mcp.service",
        "byte_mcp.ox.runtime",
        "byte_mcp.wolfram.runtime",
    ):
        module = importlib.import_module(module_name)
        importlib.reload(module)


def test_nvidia_client_repr_never_contains_key():
    client = NvidiaCatalogClient(NvidiaHostedSettings(api_key=KEY))
    assert KEY not in repr(client)


def test_catalog_snapshot_contains_no_request_or_header_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            headers={"x-secret": "HEADER-SENTINEL"},
            json={"data": [{"id": "nvidia/example-model"}]},
        )

    client = NvidiaCatalogClient(
        NvidiaHostedSettings(api_key=KEY),
        transport=httpx.MockTransport(handler),
    )
    rendered = repr(client.discover())
    assert KEY not in rendered
    assert "HEADER-SENTINEL" not in rendered
    assert "Authorization" not in rendered


def test_discovery_roster_has_no_qualified_or_enabled_state():
    registry = initial_model_registry()
    assert registry.by_state(ModelLifecycleState.QUALIFIED) == ()
    assert registry.by_state(ModelLifecycleState.ENABLED) == ()


def test_new_provider_modules_do_not_import_ox_or_wolfram_packages():
    for module_name in (
        "byte_mcp.providers.models",
        "byte_mcp.providers.outcomes",
        "byte_mcp.providers.registry",
        "byte_mcp.nvidia.errors",
        "byte_mcp.nvidia.settings",
        "byte_mcp.nvidia.catalog",
        "byte_mcp.nvidia.registry",
    ):
        source = inspect.getsource(importlib.import_module(module_name))
        assert "byte_mcp.ox" not in source
        assert "byte_mcp.wolfram" not in source
```

- [ ] **Step 2: Run security tests**

```powershell
python -m pytest tests/nvidia/test_security_invariants.py -q
```

Expected: all pass. Any secret leak or provider coupling must be fixed only inside new provider/NVIDIA files; do not edit OX/Wolfram.

- [ ] **Step 3: Run complete NVIDIA-00 focused suite**

```powershell
python -m pytest tests/providers tests/nvidia -q
```

Expected: all pass.

- [ ] **Step 4: Run full Byte-MCP Python regression suite**

```powershell
python -m pytest -q
```

Expected: full suite passes with no live provider request.

- [ ] **Step 5: Run final lint/format gates**

```powershell
python -m ruff check .
python -m ruff format --check .
```

Expected: both pass.

- [ ] **Step 6: Prove frozen OX/Wolfram/runtime boundary in Git**

```powershell
git diff --name-only 94ff28810a06b7af2207196ac98c1152cc65b4b1...HEAD
```

Allowed production paths:

```text
src/byte_mcp/providers/**
src/byte_mcp/nvidia/**
```

Allowed non-production paths:

```text
tests/providers/**
tests/nvidia/**
docs/superpowers/specs/2026-09-08-nvidia-provider-runtime-design.md
docs/superpowers/plans/2026-09-08-nvidia-provider-runtime-implementation-plan.md
```

If `src/byte_mcp/ox/**`, `src/byte_mcp/wolfram/**`, `src/byte_mcp/server.py`, `pyproject.toml`, or historical evidence appears, stop and investigate before completion.

- [ ] **Step 7: Commit security gate**

```powershell
git add tests/nvidia/test_security_invariants.py
git commit -m "test: freeze NVIDIA-00 security invariants"
```

- [ ] **Step 8: Record final candidate identity**

```powershell
git status --short
git rev-parse HEAD
git log --oneline --decorate -8
```

Expected:

- working tree clean;
- HEAD identifies the NVIDIA-00 implementation candidate;
- commits separate design, plan, provider contracts, lifecycle registry, NVIDIA settings, catalog parser/client, roster, and security gate.

Do not promote the runtime, call NVIDIA, call OX, or start NVIDIA-01 until the implementation candidate is reviewed and explicitly accepted.

---

## Plan Self-Review Checklist

1. Provider-neutral identity/model contracts: Task 1.
2. Frozen attempt outcomes and transport-failure vocabulary: Task 1.
3. Explicit lifecycle transitions and no `DISCOVERED -> QUALIFIED` shortcut: Task 2.
4. `NVIDIA_API_KEY` only, exact hosted origin, bounded timeout, secret-safe repr: Task 3.
5. Advisory/bounded catalog parser: Task 4.
6. Exactly one catalog GET, redirects rejected, zero retry, no inference, bounded body/error handling: Task 5.
7. Four provisional candidates represented without transport branching: Task 6.
8. No candidate is `QUALIFIED` or `ENABLED`: Tasks 2, 6, 7.
9. No server/MCP inference surface: no task touches `server.py`.
10. OX/Wolfram behavior frozen: Global Constraints + Task 7 Git path gate.
11. No live NVIDIA request in tests: every HTTP test injects `httpx.MockTransport`.
12. Secret/response-header isolation: Tasks 3, 5, 7.
13. Full Python/Ruff regression gates: Task 7.
14. NVIDIA-01 remains separate: Task 7 explicitly stops before runtime promotion or live calls.

## Execution Boundary

This plan authorizes no implementation by itself. Execution begins only after Nolan approves this plan and selects an execution mode. Recommended mode: subagent-driven development with a fresh implementation context per task and review between tasks. Inline execution is also acceptable if every task preserves the same RED -> GREEN -> Ruff -> commit gates.
