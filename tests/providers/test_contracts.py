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
