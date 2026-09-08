"""Immutable model registry and explicit lifecycle transitions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from types import MappingProxyType

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
        return tuple(item for item in self._profiles.values() if item.qualification_state is state)


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
