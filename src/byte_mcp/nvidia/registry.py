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
    _candidate("nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia", "routine-review"),
    _candidate("nvidia/nemotron-3-ultra-550b-a55b", "nvidia", "deep-review"),
    _candidate(
        "deepseek-ai/deepseek-v4-pro-0813",
        "deepseek-ai",
        "independent-coding-review",
    ),
    _candidate("moonshotai/kimi-k3", "moonshotai", "long-horizon-challenger"),
)


def initial_qualification_candidates() -> tuple[NvidiaQualificationCandidate, ...]:
    return _INITIAL_CANDIDATES


def initial_model_registry() -> ModelRegistry:
    return ModelRegistry(candidate.profile for candidate in _INITIAL_CANDIDATES)
