import importlib
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest


def _models():
    return importlib.import_module("byte_mcp.nvidia.models")


def test_registry_has_exact_initial_aliases() -> None:
    models = _models()

    assert set(models.NVIDIA_MODELS) == {
        "lightning",
        "deepseek-v4-pro",
    }


def test_default_query_model_is_deepseek_v4_pro() -> None:
    models = _models()

    assert models.NVIDIA_DEFAULT_QUERY_MODEL == "deepseek-v4-pro"

    model = models.resolve_query_model(None)

    assert model.alias == "deepseek-v4-pro"
    assert model.provider_model_id == "deepseek-ai/deepseek-v4-pro-0813"


def test_lightning_has_exact_provider_identity() -> None:
    models = _models()

    model = models.resolve_model("lightning")

    assert model.alias == "lightning"
    assert model.provider_model_id == ("nvidia/nemotron-3.5-lightning-30b-a3b")
    assert model.query_enabled is True
    assert model.review_enabled is True


def test_deepseek_has_exact_provider_identity() -> None:
    models = _models()

    model = models.resolve_model("deepseek-v4-pro")

    assert model.alias == "deepseek-v4-pro"
    assert model.provider_model_id == "deepseek-ai/deepseek-v4-pro-0813"
    assert model.query_enabled is True
    assert model.review_enabled is True


def test_unknown_alias_is_rejected_locally() -> None:
    models = _models()

    with pytest.raises(ValueError, match="model is not allowed"):
        models.resolve_model("not-a-governed-model")


def test_unknown_query_alias_is_rejected_locally() -> None:
    models = _models()

    with pytest.raises(ValueError, match="model is not allowed"):
        models.resolve_query_model("not-a-governed-model")


def test_unknown_review_alias_is_rejected_locally() -> None:
    models = _models()

    with pytest.raises(ValueError, match="model is not allowed"):
        models.resolve_review_model("not-a-governed-model")


def test_provider_id_reverse_lookup_returns_exact_models() -> None:
    models = _models()

    lightning = models.model_for_provider_id("nvidia/nemotron-3.5-lightning-30b-a3b")
    deepseek = models.model_for_provider_id("deepseek-ai/deepseek-v4-pro-0813")

    assert lightning.alias == "lightning"
    assert deepseek.alias == "deepseek-v4-pro"


def test_unknown_provider_id_is_rejected_locally() -> None:
    models = _models()

    with pytest.raises(ValueError, match="model is not allowed"):
        models.model_for_provider_id("provider/not-governed")


def test_lightning_review_profile_preserves_n04_request_controls() -> None:
    models = _models()

    profile = models.resolve_review_model("lightning").review_profile

    assert profile.temperature == 0.2
    assert profile.top_p == 0.95
    assert profile.max_tokens == 4_096
    assert profile.seed is None
    assert dict(profile.chat_template_kwargs) == {
        "enable_thinking": False,
    }


def test_deepseek_review_profile_preserves_n04_request_controls() -> None:
    models = _models()

    profile = models.resolve_review_model("deepseek-v4-pro").review_profile

    assert profile.temperature == 1.0
    assert profile.top_p == 0.95
    assert profile.max_tokens == 16_384
    assert profile.seed == 42
    assert dict(profile.chat_template_kwargs) == {
        "thinking": False,
    }


def test_lightning_query_profile_is_deterministic() -> None:
    models = _models()

    profile = models.resolve_query_model("lightning").query_profile

    assert profile.temperature == 0.2
    assert profile.top_p == 0.95
    assert profile.max_tokens == 4_096
    assert profile.seed is None
    assert dict(profile.chat_template_kwargs) == {
        "enable_thinking": False,
    }


def test_deepseek_query_profile_is_deterministic() -> None:
    models = _models()

    profile = models.resolve_query_model("deepseek-v4-pro").query_profile

    assert profile.temperature == 1.0
    assert profile.top_p == 0.95
    assert profile.max_tokens == 16_384
    assert profile.seed == 42
    assert dict(profile.chat_template_kwargs) == {
        "thinking": False,
    }


def test_qualification_state_vocabulary_is_exact() -> None:
    models = _models()

    state = models.NvidiaQualificationState

    assert {member.value for member in state} == {
        "REGISTERED",
        "OFFLINE_QUALIFIED",
        "QUERY_LIVE_QUALIFIED",
        "REVIEW_LIVE_QUALIFIED",
    }


def test_initial_model_maturity_states_are_conservative() -> None:
    models = _models()

    lightning = models.resolve_model("lightning")
    deepseek = models.resolve_model("deepseek-v4-pro")

    assert lightning.query_qualification is models.NvidiaQualificationState.OFFLINE_QUALIFIED
    assert lightning.review_qualification is models.NvidiaQualificationState.REVIEW_LIVE_QUALIFIED

    assert deepseek.query_qualification is models.NvidiaQualificationState.OFFLINE_QUALIFIED
    assert deepseek.review_qualification is models.NvidiaQualificationState.OFFLINE_QUALIFIED


def test_model_definitions_are_immutable() -> None:
    models = _models()
    model = models.resolve_model("lightning")

    with pytest.raises(FrozenInstanceError):
        model.alias = "changed"


def test_execution_profiles_are_immutable() -> None:
    models = _models()
    profile = models.resolve_model("lightning").review_profile

    with pytest.raises(FrozenInstanceError):
        profile.temperature = 0.9


def test_chat_template_kwargs_are_immutable() -> None:
    models = _models()
    profile = models.resolve_model("lightning").review_profile

    with pytest.raises(TypeError):
        profile.chat_template_kwargs["enable_thinking"] = True


def test_registry_mapping_is_immutable() -> None:
    models = _models()

    with pytest.raises(TypeError):
        models.NVIDIA_MODELS["other"] = models.resolve_model("lightning")


def test_query_disabled_model_is_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _models()

    disabled = replace(
        models.resolve_model("lightning"),
        query_enabled=False,
    )

    registry = dict(models.NVIDIA_MODELS)
    registry["lightning"] = disabled

    monkeypatch.setattr(
        models,
        "NVIDIA_MODELS",
        MappingProxyType(registry),
    )

    with pytest.raises(
        ValueError,
        match="model is not enabled for query",
    ):
        models.resolve_query_model("lightning")


def test_review_disabled_model_is_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _models()

    disabled = replace(
        models.resolve_model("lightning"),
        review_enabled=False,
    )

    registry = dict(models.NVIDIA_MODELS)
    registry["lightning"] = disabled

    monkeypatch.setattr(
        models,
        "NVIDIA_MODELS",
        MappingProxyType(registry),
    )

    with pytest.raises(
        ValueError,
        match="model is not enabled for review",
    ):
        models.resolve_review_model("lightning")


def test_query_enabled_model_requires_query_profile() -> None:
    models = _models()

    invalid = replace(
        models.resolve_model("lightning"),
        query_profile=None,
    )

    registry = {
        "lightning": invalid,
        "deepseek-v4-pro": models.resolve_model("deepseek-v4-pro"),
    }

    with pytest.raises(
        ValueError,
        match="query-enabled model requires query profile",
    ):
        models.validate_model_registry(
            registry,
            default_query_model="deepseek-v4-pro",
        )


def test_review_enabled_model_requires_review_profile() -> None:
    models = _models()

    invalid = replace(
        models.resolve_model("lightning"),
        review_profile=None,
    )

    registry = {
        "lightning": invalid,
        "deepseek-v4-pro": models.resolve_model("deepseek-v4-pro"),
    }

    with pytest.raises(
        ValueError,
        match="review-enabled model requires review profile",
    ):
        models.validate_model_registry(
            registry,
            default_query_model="deepseek-v4-pro",
        )


def test_registry_rejects_alias_key_mismatch() -> None:
    models = _models()

    invalid = {
        "wrong-alias": models.resolve_model("lightning"),
    }

    with pytest.raises(
        ValueError,
        match="registry alias does not match model alias",
    ):
        models.validate_model_registry(invalid)


def test_registry_rejects_duplicate_provider_ids() -> None:
    models = _models()

    lightning = models.resolve_model("lightning")
    deepseek = replace(
        models.resolve_model("deepseek-v4-pro"),
        provider_model_id=lightning.provider_model_id,
    )

    registry = {
        "lightning": lightning,
        "deepseek-v4-pro": deepseek,
    }

    with pytest.raises(
        ValueError,
        match="duplicate provider model id",
    ):
        models.validate_model_registry(registry)


def test_registry_rejects_unknown_default_query_model() -> None:
    models = _models()

    with pytest.raises(
        ValueError,
        match="default query model is not allowed",
    ):
        models.validate_model_registry(
            models.NVIDIA_MODELS,
            default_query_model="not-governed",
        )


def test_registry_rejects_disabled_default_query_model() -> None:
    models = _models()

    disabled = replace(
        models.resolve_model("deepseek-v4-pro"),
        query_enabled=False,
    )

    registry = dict(models.NVIDIA_MODELS)
    registry["deepseek-v4-pro"] = disabled

    with pytest.raises(
        ValueError,
        match="default query model is not enabled for query",
    ):
        models.validate_model_registry(
            registry,
            default_query_model="deepseek-v4-pro",
        )
