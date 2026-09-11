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
