import asyncio
import importlib
import inspect

import pytest

from byte_mcp import server
from byte_mcp.nvidia.review_service import NvidiaReviewService


PREPARE_FIELDS = {
    "repository",
    "subsystem",
    "target_commit",
    "base_commit",
    "objective",
    "verification",
}
APPROVAL_FIELDS = {"review_id", "expected_request_sha256", "approve"}


def review_runtime_module():
    return importlib.import_module("byte_mcp.nvidia.review_runtime")


def test_nvidia_review_tool_signature_has_only_frozen_modes() -> None:
    signature = inspect.signature(server.nvidia_review)
    assert set(signature.parameters) == PREPARE_FIELDS | APPROVAL_FIELDS
    forbidden = {"retry", "model", "model_id", "endpoint", "prompt", "api_key", "key"}
    assert forbidden.isdisjoint(signature.parameters)


def test_nvidia_get_review_signature_is_narrow() -> None:
    signature = inspect.signature(server.nvidia_get_review)
    assert list(signature.parameters) == ["review_id", "view"]
    assert signature.parameters["view"].default == "summary"


def test_nvidia_external_annotations_match_open_world_non_idempotent_contract() -> None:
    annotations = server.NVIDIA_EXTERNAL
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def test_nvidia_review_prepare_mode_calls_only_prepare_service(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeService:
        def prepare_review(self, **kwargs):
            calls.append(("prepare", kwargs))
            return {"review_id": "NVR-000001", "request_sha256": "a" * 64}

        async def transmit_review(self, *args, **kwargs):
            calls.append(("transmit", (args, kwargs)))
            raise AssertionError("transmit must not run in prepare mode")

    monkeypatch.setattr(server, "_nvidia_review_service", lambda: FakeService())
    result = asyncio.run(
        server.nvidia_review(
            repository="byte-mcp",
            subsystem="nvidia",
            target_commit="b" * 40,
            base_commit="a" * 40,
            objective="Review regression risk",
            verification=[],
        )
    )
    assert result["review_id"] == "NVR-000001"
    assert len(calls) == 1
    assert calls[0][0] == "prepare"


@pytest.mark.parametrize(
    "extra",
    [
        {"approve": True},
        {"expected_request_sha256": "a" * 64},
        {"review_id": "NVR-000001"},
    ],
)
def test_nvidia_review_prepare_mode_rejects_approval_fields(monkeypatch, extra) -> None:
    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: (_ for _ in ()).throw(AssertionError("service must not load")),
    )
    kwargs = {
        "repository": "byte-mcp",
        "subsystem": "nvidia",
        "target_commit": "b" * 40,
        "base_commit": "a" * 40,
        "objective": "Review",
        "verification": [],
        **extra,
    }
    with pytest.raises(ValueError, match="NVIDIA review mode"):
        asyncio.run(server.nvidia_review(**kwargs))


def test_nvidia_review_approval_mode_requires_exact_three_fields(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeService:
        async def transmit_review(self, review_id, *, expected_request_sha256, approve):
            calls.append((review_id, expected_request_sha256, approve))
            return {"review_id": review_id, "review_result_status": "VALID"}

    monkeypatch.setattr(server, "_nvidia_review_service", lambda: FakeService())
    result = asyncio.run(
        server.nvidia_review(
            review_id="NVR-000001",
            expected_request_sha256="a" * 64,
            approve=True,
        )
    )
    assert result["review_result_status"] == "VALID"
    assert calls == [("NVR-000001", "a" * 64, True)]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"review_id": "NVR-000001", "expected_request_sha256": "a" * 64},
        {"review_id": "NVR-000001", "approve": True},
        {
            "review_id": "NVR-000001",
            "expected_request_sha256": "a" * 64,
            "approve": True,
            "objective": "not allowed",
        },
    ],
)
def test_nvidia_review_approval_mode_rejects_incomplete_or_mixed_fields(
    monkeypatch,
    kwargs,
) -> None:
    monkeypatch.setattr(
        server,
        "_nvidia_review_service",
        lambda: (_ for _ in ()).throw(AssertionError("service must not load")),
    )
    with pytest.raises(ValueError, match="NVIDIA review mode"):
        asyncio.run(server.nvidia_review(**kwargs))


def test_nvidia_get_review_is_read_only_and_rejects_unknown_view(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeService:
        def get_review(self, review_id, *, view):
            calls.append((review_id, view))
            return {"review_id": review_id, "state": "PREPARED"}

    monkeypatch.setattr(server, "_nvidia_review_service", lambda: FakeService())
    result = server.nvidia_get_review("NVR-000001", view="summary")
    assert result == {"review_id": "NVR-000001", "state": "PREPARED"}
    assert calls == [("NVR-000001", "summary")]

    with pytest.raises(ValueError, match="NVIDIA review view"):
        server.nvidia_get_review("NVR-000001", view="raw")
    assert calls == [("NVR-000001", "summary")]


def test_nvidia_review_runtime_load_fail_isolates_local_configuration(
    monkeypatch,
    tmp_path,
) -> None:
    runtime_module = review_runtime_module()

    def fail_initialize(cls, repo_root, *, evidence_store=None):
        raise ValueError("synthetic local review configuration failure")

    monkeypatch.setattr(NvidiaReviewService, "initialize", classmethod(fail_initialize))
    runtime = runtime_module.NvidiaReviewRuntime.load(tmp_path)
    assert runtime.service is None
    assert runtime.error_type == "ValueError"
    with pytest.raises(ValueError, match="NVIDIA review runtime is unavailable"):
        runtime.require_service()


def test_nvidia_review_runtime_load_wraps_available_service(monkeypatch, tmp_path) -> None:
    runtime_module = review_runtime_module()
    fake_service = object()
    monkeypatch.setattr(
        NvidiaReviewService,
        "initialize",
        classmethod(lambda cls, repo_root, *, evidence_store=None: fake_service),
    )
    runtime = runtime_module.NvidiaReviewRuntime.load(tmp_path)
    assert runtime.service is fake_service
    assert runtime.error_type is None
    assert runtime.require_service() is fake_service
