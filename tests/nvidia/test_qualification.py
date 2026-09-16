def _module(name: str):
    import importlib
    import importlib.util

    spec = importlib.util.find_spec(name)
    assert spec is not None, f"{name} must exist"
    return importlib.import_module(name)


def test_readiness_is_provider_free_and_secret_free(monkeypatch) -> None:
    qualification = _module("byte_mcp.nvidia.qualification")
    settings = _module("byte_mcp.nvidia.settings")
    secret = "NVIDIA-READINESS-SECRET"

    def forbidden_load(cls):
        raise AssertionError("readiness must not load hosted settings")

    monkeypatch.setattr(
        settings.NvidiaHostedSettings,
        "load",
        classmethod(forbidden_load),
    )

    report = qualification.inspect_nvidia_readiness()
    payload = report.to_dict()

    assert payload["endpoint"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert payload["default_query_alias"] == "deepseek-v4-pro"
    assert payload["enabled_query_aliases"] == ("deepseek-v4-pro", "lightning")
    assert payload["enabled_review_aliases"] == ("deepseek-v4-pro", "lightning")
    assert payload["credential_status"] == "DEFERRED_TO_TRANSMIT"
    assert payload["request_builder_status"] == "READY"
    assert payload["response_bounds_status"] == "READY"
    assert payload["review_evidence_status"] == "READY"
    assert payload["expected_mcp_surface_names"] == (
        "nvidia_get_review",
        "nvidia_query",
        "nvidia_review",
    )
    assert secret not in repr(payload)


def test_both_query_models_are_offline_qualified() -> None:
    models = _module("byte_mcp.nvidia.models")

    assert (
        models.NVIDIA_MODELS["lightning"].query_qualification
        is models.NvidiaQualificationState.OFFLINE_QUALIFIED
    )
    assert (
        models.NVIDIA_MODELS["deepseek-v4-pro"].query_qualification
        is models.NvidiaQualificationState.OFFLINE_QUALIFIED
    )
    assert (
        models.NVIDIA_MODELS["lightning"].review_qualification
        is models.NvidiaQualificationState.REVIEW_LIVE_QUALIFIED
    )
    assert (
        models.NVIDIA_MODELS["deepseek-v4-pro"].review_qualification
        is models.NvidiaQualificationState.OFFLINE_QUALIFIED
    )


def test_offline_qualification_is_deterministic_and_provider_free(monkeypatch) -> None:
    qualification = _module("byte_mcp.nvidia.qualification")
    settings = _module("byte_mcp.nvidia.settings")

    def forbidden_load(cls):
        raise AssertionError("offline qualification must not load credentials")

    monkeypatch.setattr(
        settings.NvidiaHostedSettings,
        "load",
        classmethod(forbidden_load),
    )

    receipt = qualification.qualify_nvidia_offline()

    assert receipt == {
        "status": "PASS",
        "provider_calls": 0,
        "default_query_alias": "deepseek-v4-pro",
        "models": {
            "deepseek-v4-pro": "PASS",
            "lightning": "PASS",
        },
    }
