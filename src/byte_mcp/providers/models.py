"""Provider-neutral model identity and lifecycle contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
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
