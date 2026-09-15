from __future__ import annotations

import asyncio
import importlib
import inspect
from types import MappingProxyType

import pytest

from byte_mcp import server

LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEEPSEEK = "deepseek-ai/deepseek-v4-pro-0813"


def review_protocol_module():
    return importlib.import_module("byte_mcp.nvidia.review_protocol")


def review_service_class():
    module = importlib.import_module("byte_mcp.nvidia.review_service")
    return module.NvidiaReviewService


def test_n04_exposes_exact_two_model_review_allowlist() -> None:
    module = review_protocol_module()

    profiles = getattr(
        module,
        "NVIDIA_REVIEW_MODEL_PROFILES",
        None,
    )

    assert profiles is not None, "N04 requires an explicit immutable review-model allowlist"

    assert isinstance(profiles, MappingProxyType)

    assert set(profiles) == {
        LIGHTNING,
        DEEPSEEK,
    }


def test_n04_profiles_freeze_exact_provider_controls() -> None:
    module = review_protocol_module()

    profiles = getattr(
        module,
        "NVIDIA_REVIEW_MODEL_PROFILES",
        None,
    )

    assert profiles is not None

    lightning = profiles[LIGHTNING]

    assert lightning.model_id == LIGHTNING
    assert lightning.temperature == 0.2
    assert lightning.top_p == 0.95
    assert lightning.max_tokens == 4096
    assert lightning.seed is None
    assert dict(lightning.chat_template_kwargs) == {
        "enable_thinking": False,
    }

    deepseek = profiles[DEEPSEEK]

    assert deepseek.model_id == DEEPSEEK
    assert deepseek.temperature == 1.0
    assert deepseek.top_p == 0.95
    assert deepseek.max_tokens == 16384
    assert deepseek.seed == 42
    assert dict(deepseek.chat_template_kwargs) == {
        "thinking": False,
    }


def test_n04_review_request_requires_explicit_model_id() -> None:
    module = review_protocol_module()

    signature = inspect.signature(module.prepare_nvidia_review_request)

    assert tuple(signature.parameters) == (
        "packet",
        "model_id",
    )

    model_parameter = signature.parameters["model_id"]

    assert model_parameter.kind is inspect.Parameter.KEYWORD_ONLY

    assert model_parameter.default is inspect.Parameter.empty


def test_n04_service_prepare_requires_explicit_model_id() -> None:
    signature = inspect.signature(review_service_class().prepare_review)

    assert "model_id" in signature.parameters

    model_parameter = signature.parameters["model_id"]

    assert model_parameter.kind is inspect.Parameter.KEYWORD_ONLY

    assert model_parameter.default is inspect.Parameter.empty


def test_n04_mcp_prepare_passes_explicit_model_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeService:
        def prepare_review(self, **kwargs):
            calls.append(kwargs)

            return {
                "review_id": "NVR-TEST",
                "model_id": kwargs["model_id"],
            }

        async def transmit_review(self, *args, **kwargs):
            raise AssertionError("transmit must not run in prepare mode")

    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: FakeService(),
    )

    result = asyncio.run(
        server.nvidia_review(
            repository="byte-engineering-agent",
            subsystem="core",
            target_commit="b" * 40,
            base_commit="a" * 40,
            objective="Review correctness",
            verification=[],
            model_id=DEEPSEEK,
        )
    )

    assert result == {
        "review_id": "NVR-TEST",
        "model_id": DEEPSEEK,
    }

    assert len(calls) == 1
    assert calls[0]["model_id"] == DEEPSEEK


def test_n04_model_id_is_forbidden_in_approval_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: (_ for _ in ()).throw(
            AssertionError("service must not load for invalid mixed mode")
        ),
    )

    with pytest.raises(
        ValueError,
        match="NVIDIA review mode",
    ):
        asyncio.run(
            server.nvidia_review(
                review_id="NVR-000003",
                expected_request_sha256="a" * 64,
                approve=True,
                model_id=DEEPSEEK,
            )
        )


def test_n04_approval_contract_remains_three_fields_only() -> None:
    signature = inspect.signature(server.nvidia_review)

    parameters = set(signature.parameters)

    assert {
        "review_id",
        "expected_request_sha256",
        "approve",
    }.issubset(parameters)

    assert "retry" not in parameters
    assert "fallback" not in parameters
    assert "endpoint" not in parameters
    assert "api_key" not in parameters
