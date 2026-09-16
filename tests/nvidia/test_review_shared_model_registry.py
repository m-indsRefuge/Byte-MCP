import asyncio
import inspect

import pytest

from byte_mcp import server
from byte_mcp.nvidia import models, review_protocol

LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"
ULTRA = "nvidia/nemotron-3-ultra-550b-a55b"


def test_review_protocol_profiles_are_derived_from_shared_registry() -> None:
    source = inspect.getsource(review_protocol)

    assert "NVIDIA_MODELS" in source
    assert set(review_protocol.NVIDIA_REVIEW_MODEL_PROFILES) == {
        LIGHTNING,
        ULTRA,
    }

    for alias in ("lightning", "nemotron-ultra"):
        definition = models.resolve_review_model(alias)
        shared = definition.review_profile
        compatibility = review_protocol.NVIDIA_REVIEW_MODEL_PROFILES[definition.provider_model_id]

        assert shared is not None
        assert compatibility.model_id == definition.provider_model_id
        assert compatibility.temperature == shared.temperature
        assert compatibility.top_p == shared.top_p
        assert compatibility.max_tokens == shared.max_tokens
        assert compatibility.seed == shared.seed
        assert dict(compatibility.chat_template_kwargs) == dict(shared.chat_template_kwargs)


def test_internal_review_request_builder_keeps_provider_id_contract() -> None:
    signature = inspect.signature(review_protocol.prepare_nvidia_review_request)

    assert tuple(signature.parameters) == ("packet", "model_id")
    parameter = signature.parameters["model_id"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_public_review_surface_uses_alias_not_provider_id() -> None:
    signature = inspect.signature(server.nvidia_review)
    parameters = set(signature.parameters)

    assert "model" in parameters
    assert "model_id" not in parameters


def test_server_prepare_resolves_alias_to_exact_provider_id(
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
            repository="byte-mcp",
            subsystem="nvidia",
            target_commit="b" * 40,
            base_commit="a" * 40,
            objective="Review correctness",
            verification=[],
            model="nemotron-ultra",
        )
    )

    assert result == {
        "review_id": "NVR-TEST",
        "model_id": ULTRA,
    }
    assert len(calls) == 1
    assert calls[0]["model_id"] == ULTRA


def test_server_rejects_raw_provider_id_before_service_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: (_ for _ in ()).throw(
            AssertionError("service must not load for invalid model alias")
        ),
    )

    with pytest.raises(ValueError, match="model is not allowed"):
        asyncio.run(
            server.nvidia_review(
                repository="byte-mcp",
                subsystem="nvidia",
                target_commit="b" * 40,
                base_commit="a" * 40,
                objective="Review correctness",
                verification=[],
                model=ULTRA,
            )
        )


def test_approval_mode_rejects_model_alias_before_service_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: (_ for _ in ()).throw(
            AssertionError("service must not load for invalid mixed mode")
        ),
    )

    with pytest.raises(ValueError, match="invalid NVIDIA review mode"):
        asyncio.run(
            server.nvidia_review(
                review_id="NVR-000003",
                expected_request_sha256="a" * 64,
                approve=True,
                model="nemotron-ultra",
            )
        )
