from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from byte_mcp.nvidia.review_service import NvidiaReviewService

LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEEPSEEK = "deepseek-ai/deepseek-v4-pro-0813"
UNKNOWN = "nvidia/not-allowlisted-for-review"


def _load_test_helper(
    filename: str,
    module_name: str,
) -> ModuleType:
    helper_path = Path(__file__).with_name(filename)

    spec = importlib.util.spec_from_file_location(
        module_name,
        helper_path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test helper: {filename}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


_PROTOCOL_HELPER = _load_test_helper(
    "test_review_protocol.py",
    "_n04_protocol_helper",
)

_PREPARE_HELPER = _load_test_helper(
    "test_review_service_prepare.py",
    "_n04_prepare_helper",
)


def test_n04_same_packet_models_have_distinct_exact_request_identities() -> None:
    module = _PROTOCOL_HELPER.review_protocol_module()
    review_packet = _PROTOCOL_HELPER.packet()

    lightning = module.prepare_nvidia_review_request(
        review_packet,
        model_id=LIGHTNING,
    )

    deepseek = module.prepare_nvidia_review_request(
        review_packet,
        model_id=DEEPSEEK,
    )

    assert lightning.provider_id == deepseek.provider_id
    assert lightning.method == deepseek.method
    assert lightning.target_origin == deepseek.target_origin
    assert lightning.endpoint_path == deepseek.endpoint_path

    assert lightning.model_id == LIGHTNING
    assert deepseek.model_id == DEEPSEEK

    assert lightning.body_bytes != deepseek.body_bytes
    assert lightning.payload_sha256 != deepseek.payload_sha256
    assert lightning.request_sha256 != deepseek.request_sha256


def test_n04_exact_model_profiles_are_bound_into_canonical_request_bytes() -> None:
    module = _PROTOCOL_HELPER.review_protocol_module()
    review_packet = _PROTOCOL_HELPER.packet()

    lightning = module.prepare_nvidia_review_request(
        review_packet,
        model_id=LIGHTNING,
    )

    deepseek = module.prepare_nvidia_review_request(
        review_packet,
        model_id=DEEPSEEK,
    )

    lightning_body = json.loads(lightning.body_bytes)

    deepseek_body = json.loads(deepseek.body_bytes)

    assert lightning_body["model"] == LIGHTNING
    assert lightning_body["temperature"] == 0.2
    assert lightning_body["top_p"] == 0.95
    assert lightning_body["max_tokens"] == 4096
    assert lightning_body["chat_template_kwargs"] == {
        "enable_thinking": False,
    }
    assert "seed" not in lightning_body

    assert deepseek_body["model"] == DEEPSEEK
    assert deepseek_body["temperature"] == 1.0
    assert deepseek_body["top_p"] == 0.95
    assert deepseek_body["max_tokens"] == 16384
    assert deepseek_body["seed"] == 42
    assert deepseek_body["chat_template_kwargs"] == {
        "thinking": False,
    }


def test_n04_unknown_review_model_is_rejected_locally() -> None:
    module = _PROTOCOL_HELPER.review_protocol_module()
    review_packet = _PROTOCOL_HELPER.packet()

    with pytest.raises(
        ValueError,
        match="review model is not allowed",
    ):
        module.prepare_nvidia_review_request(
            review_packet,
            model_id=UNKNOWN,
        )


def test_n04_same_review_packet_is_model_neutral_but_manifest_is_model_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _store, base, target = _PREPARE_HELPER.service_fixture(
        tmp_path,
        monkeypatch,
    )

    verification = _PREPARE_HELPER.verification()

    common = {
        "repository": "fixture",
        "subsystem": "validation",
        "target_commit": target,
        "base_commit": base,
        "objective": ("Review correctness and regression risk"),
        "verification": verification,
    }

    lightning = service.prepare_review(
        **common,
        model_id=LIGHTNING,
    )

    deepseek = service.prepare_review(
        **common,
        model_id=DEEPSEEK,
    )

    # Model selection does not contaminate repository evidence.
    assert lightning["packet_sha256"] == deepseek["packet_sha256"]

    # Provider identity is nevertheless immutable and model-specific.
    assert lightning["payload_sha256"] != deepseek["payload_sha256"]

    assert lightning["request_sha256"] != deepseek["request_sha256"]

    assert lightning["model_id"] == LIGHTNING
    assert deepseek["model_id"] == DEEPSEEK

    lightning_manifest = service.get_review(
        lightning["review_id"],
        view="manifest",
    )

    deepseek_manifest = service.get_review(
        deepseek["review_id"],
        view="manifest",
    )

    assert lightning_manifest["model_id"] == LIGHTNING

    assert deepseek_manifest["model_id"] == DEEPSEEK

    assert lightning_manifest["request_sha256"] == lightning["request_sha256"]

    assert deepseek_manifest["request_sha256"] == deepseek["request_sha256"]


def test_n04_transmission_surface_cannot_substitute_model_after_prepare() -> None:
    signature = inspect.signature(NvidiaReviewService.transmit_review)

    assert "model_id" not in signature.parameters
    assert "model" not in signature.parameters
    assert "endpoint" not in signature.parameters
    assert "fallback" not in signature.parameters
    assert "retry" not in signature.parameters
