from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from byte_mcp import server
from byte_mcp.nvidia import review_protocol, review_service
from byte_mcp.nvidia.registry import initial_qualification_candidates
from byte_mcp.providers.models import ModelLifecycleState

_REVIEW_MODULES = (
    "review_registry.py",
    "review_packet.py",
    "review_protocol.py",
    "review_evidence.py",
    "review_settings.py",
    "review_service.py",
    "review_runtime.py",
)
_FORBIDDEN_FLOW_TOKENS = ("retry", "backoff", "sleep", "fallback", "replay")
_REVIEW_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def _repo_root() -> Path:
    return Path(server.__file__).resolve().parents[2]


def _nvidia_dir() -> Path:
    return _repo_root() / "src" / "byte_mcp" / "nvidia"


def _import_targets(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.append("." * node.level + (node.module or ""))
    return tuple(targets)


def test_lightning_is_qualified_but_not_enabled() -> None:
    candidate = next(
        candidate
        for candidate in initial_qualification_candidates()
        if candidate.profile.model_id == _REVIEW_MODEL
    )
    assert candidate.profile.qualification_state is ModelLifecycleState.QUALIFIED
    assert candidate.profile.qualification_state is not ModelLifecycleState.ENABLED


def test_review_modules_do_not_import_ox_or_wolfram() -> None:
    for filename in _REVIEW_MODULES:
        targets = _import_targets(_nvidia_dir() / filename)
        assert not any(
            "ox" in target.lower().split(".") or "wolfram" in target.lower().split(".")
            for target in targets
        ), filename


def test_review_modules_have_no_retry_fallback_replay_or_catalog_execution() -> None:
    for filename in _REVIEW_MODULES:
        path = _nvidia_dir() / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        assert "/v1/models" not in source
        assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lowered = node.name.lower()
                assert not any(token in lowered for token in _FORBIDDEN_FLOW_TOKENS)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    name = ""
                lowered = name.lower()
                assert not any(token in lowered for token in _FORBIDDEN_FLOW_TOKENS)
                assert "catalog" not in lowered


def test_review_request_model_and_controls_are_fixed() -> None:
    assert review_protocol.NVIDIA_REVIEW_MODEL_ID == _REVIEW_MODEL
    signature = inspect.signature(review_protocol.prepare_nvidia_review_request)
    assert tuple(signature.parameters) == ("packet",)

    review_signature = inspect.signature(server.nvidia_review)
    for forbidden in ("model", "model_id", "endpoint", "prompt", "retry", "fallback"):
        assert forbidden not in review_signature.parameters


def test_prepare_and_read_paths_do_not_load_hosted_credentials() -> None:
    for function in (
        review_service.NvidiaReviewService.prepare_review,
        review_service.NvidiaReviewService.get_review,
    ):
        source = inspect.getsource(function)
        assert "NvidiaHostedSettings" not in source
        assert "settings_loader" not in source
        assert "NVIDIA_API_KEY" not in source

    transmit_source = inspect.getsource(review_service.NvidiaReviewService.transmit_review)
    assert "settings_loader" in transmit_source
    assert "NvidiaHostedSettings" in transmit_source


def test_server_exposes_only_the_two_governed_nvidia_review_tools() -> None:
    nvidia_tools = {name for name in server.mcp._tool_manager._tools if "nvidia" in name}
    assert nvidia_tools == {"nvidia_review", "nvidia_get_review"}


def test_ox_and_wolfram_packages_do_not_import_nvidia_review_modules() -> None:
    for package_name in ("byte_mcp.ox", "byte_mcp.wolfram"):
        package = importlib.import_module(package_name)
        package_dir = Path(package.__file__).resolve().parent
        for path in package_dir.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "byte_mcp.nvidia.review" not in source, str(path)
            assert ".nvidia.review" not in source, str(path)
