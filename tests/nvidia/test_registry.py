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
LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_nvidia_provider_identity_distinguishes_gateway_from_model_publisher():
    assert NVIDIA_PROVIDER.provider_id == "nvidia-api-catalog"
    assert NVIDIA_PROVIDER.provider_family == "nvidia"
    assert NVIDIA_PROVIDER.endpoint_family == "openai-chat"


def test_lightning_is_qualified_but_other_candidates_remain_discovered():
    candidates = initial_qualification_candidates()
    by_id = {candidate.profile.model_id: candidate for candidate in candidates}

    assert set(by_id) == EXPECTED_MODELS
    assert by_id[LIGHTNING].profile.qualification_state is ModelLifecycleState.QUALIFIED
    assert all(
        candidate.profile.qualification_state is ModelLifecycleState.DISCOVERED
        for model_id, candidate in by_id.items()
        if model_id != LIGHTNING
    )
    assert all(candidate.profile.provider_id == "nvidia-api-catalog" for candidate in candidates)


def test_initial_registry_contains_one_qualified_and_no_enabled_model():
    registry = initial_model_registry()
    assert {profile.model_id for profile in registry.all()} == EXPECTED_MODELS
    qualified = registry.by_state(ModelLifecycleState.QUALIFIED)
    assert tuple(profile.model_id for profile in qualified) == (LIGHTNING,)
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
