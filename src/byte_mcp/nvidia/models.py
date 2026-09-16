from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class NvidiaQualificationState(StrEnum):
    REGISTERED = "REGISTERED"
    OFFLINE_QUALIFIED = "OFFLINE_QUALIFIED"
    QUERY_LIVE_QUALIFIED = "QUERY_LIVE_QUALIFIED"
    REVIEW_LIVE_QUALIFIED = "REVIEW_LIVE_QUALIFIED"


@dataclass(frozen=True, slots=True)
class NvidiaExecutionProfile:
    temperature: float
    top_p: float
    max_tokens: int
    seed: int | None
    chat_template_kwargs: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class NvidiaModelDefinition:
    alias: str
    provider_model_id: str
    query_enabled: bool
    review_enabled: bool
    query_profile: NvidiaExecutionProfile | None
    review_profile: NvidiaExecutionProfile | None
    query_qualification: NvidiaQualificationState
    review_qualification: NvidiaQualificationState


NVIDIA_DEFAULT_QUERY_MODEL = "deepseek-v4-pro"


def _profile(
    *,
    temperature: float,
    top_p: float,
    max_tokens: int,
    seed: int | None,
    chat_template_kwargs: Mapping[str, object],
) -> NvidiaExecutionProfile:
    return NvidiaExecutionProfile(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        chat_template_kwargs=MappingProxyType(dict(chat_template_kwargs)),
    )


_LIGHTNING_QUERY_PROFILE = _profile(
    temperature=0.2,
    top_p=0.95,
    max_tokens=4_096,
    seed=None,
    chat_template_kwargs={
        "enable_thinking": False,
    },
)

_LIGHTNING_REVIEW_PROFILE = _profile(
    temperature=0.2,
    top_p=0.95,
    max_tokens=4_096,
    seed=None,
    chat_template_kwargs={
        "enable_thinking": False,
    },
)

_DEEPSEEK_QUERY_PROFILE = _profile(
    temperature=1.0,
    top_p=0.95,
    max_tokens=16_384,
    seed=42,
    chat_template_kwargs={
        "thinking": False,
    },
)

_DEEPSEEK_REVIEW_PROFILE = _profile(
    temperature=1.0,
    top_p=0.95,
    max_tokens=16_384,
    seed=42,
    chat_template_kwargs={
        "thinking": False,
    },
)


NVIDIA_MODELS: Mapping[str, NvidiaModelDefinition] = MappingProxyType(
    {
        "lightning": NvidiaModelDefinition(
            alias="lightning",
            provider_model_id=("nvidia/nemotron-3.5-lightning-30b-a3b"),
            query_enabled=True,
            review_enabled=True,
            query_profile=_LIGHTNING_QUERY_PROFILE,
            review_profile=_LIGHTNING_REVIEW_PROFILE,
            query_qualification=(NvidiaQualificationState.OFFLINE_QUALIFIED),
            review_qualification=(NvidiaQualificationState.REVIEW_LIVE_QUALIFIED),
        ),
        "deepseek-v4-pro": NvidiaModelDefinition(
            alias="deepseek-v4-pro",
            provider_model_id=("deepseek-ai/deepseek-v4-pro-0813"),
            query_enabled=True,
            review_enabled=True,
            query_profile=_DEEPSEEK_QUERY_PROFILE,
            review_profile=_DEEPSEEK_REVIEW_PROFILE,
            query_qualification=(NvidiaQualificationState.OFFLINE_QUALIFIED),
            review_qualification=(NvidiaQualificationState.OFFLINE_QUALIFIED),
        ),
    }
)


def validate_model_registry(
    registry: Mapping[str, NvidiaModelDefinition],
    *,
    default_query_model: str | None = None,
) -> None:
    provider_model_ids: set[str] = set()

    for alias, model in registry.items():
        if alias != model.alias:
            raise ValueError("registry alias does not match model alias")

        if model.provider_model_id in provider_model_ids:
            raise ValueError("duplicate provider model id")

        provider_model_ids.add(model.provider_model_id)

        if model.query_enabled and model.query_profile is None:
            raise ValueError("query-enabled model requires query profile")

        if model.review_enabled and model.review_profile is None:
            raise ValueError("review-enabled model requires review profile")

    if default_query_model is None:
        return

    try:
        default = registry[default_query_model]
    except KeyError as exc:
        raise ValueError("default query model is not allowed") from exc

    if not default.query_enabled:
        raise ValueError("default query model is not enabled for query")

    if default.query_profile is None:
        raise ValueError("query-enabled model requires query profile")


validate_model_registry(
    NVIDIA_MODELS,
    default_query_model=NVIDIA_DEFAULT_QUERY_MODEL,
)


def resolve_model(alias: str) -> NvidiaModelDefinition:
    try:
        return NVIDIA_MODELS[alias]
    except (KeyError, TypeError) as exc:
        raise ValueError("model is not allowed") from exc


def resolve_query_model(
    alias: str | None,
) -> NvidiaModelDefinition:
    selected = alias or NVIDIA_DEFAULT_QUERY_MODEL
    model = resolve_model(selected)

    if not model.query_enabled or model.query_profile is None:
        raise ValueError("model is not enabled for query")

    return model


def resolve_review_model(
    alias: str,
) -> NvidiaModelDefinition:
    model = resolve_model(alias)

    if not model.review_enabled or model.review_profile is None:
        raise ValueError("model is not enabled for review")

    return model


def model_for_provider_id(
    provider_model_id: str,
) -> NvidiaModelDefinition:
    if not isinstance(provider_model_id, str):
        raise ValueError("model is not allowed")

    for model in NVIDIA_MODELS.values():
        if model.provider_model_id == provider_model_id:
            return model

    raise ValueError("model is not allowed")
