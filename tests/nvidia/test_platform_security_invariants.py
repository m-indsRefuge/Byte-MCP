import ast
import asyncio
import inspect
from pathlib import Path

import pytest

from byte_mcp import server


def _import_targets(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.append(node.module or "")
    return tuple(targets)


def test_server_preserves_no_static_nvidia_import_invariant() -> None:
    path = Path(server.__file__).resolve()
    assert not any("nvidia" in target.lower() for target in _import_targets(path))


def test_query_tool_has_no_provider_control_escape_hatches() -> None:
    parameters = set(inspect.signature(server.nvidia_query).parameters)
    assert parameters == {"prompt", "model", "system_prompt"}
    for forbidden in (
        "model_id",
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "endpoint",
        "api_key",
        "retry",
        "fallback",
    ):
        assert forbidden not in parameters


def test_server_query_source_uses_only_lazy_query_service_boundary() -> None:
    source = inspect.getsource(server.nvidia_query)
    assert "_nvidia_query_executor" in source
    assert "execute_prepared_nvidia_chat" not in source
    assert "NVIDIA_API_KEY" not in source
    assert "/v1/models" not in source


def test_review_approval_still_rejects_model_selector(monkeypatch) -> None:
    class Service:
        async def transmit_review(self, *args, **kwargs):
            raise AssertionError("invalid approval must fail before service")

    monkeypatch.setattr(server, "_nvidia_review_service", lambda: Service())

    with pytest.raises(ValueError, match="invalid NVIDIA review mode"):
        asyncio.run(
            server.nvidia_review(
                review_id="NVR-TEST",
                expected_request_sha256="a" * 64,
                approve=True,
                model="lightning",
            )
        )
