from __future__ import annotations

import ast
import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import byte_mcp
import scripts.nvidia_lightning_canary as canary_cli
from byte_mcp.nvidia.canary import (
    NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT,
    NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    inspect_lightning_canary,
    prepare_lightning_canary,
    transmit_lightning_canary,
)
from byte_mcp.nvidia.canary_evidence import (
    NvidiaCanaryEvidenceError,
    NvidiaCanaryEvidenceStore,
    NvidiaCanaryLockError,
)
from byte_mcp.nvidia.chat import NvidiaChatResult
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers import ProviderTransportObservation

_REPO_ROOT = Path(byte_mcp.__file__).resolve().parents[2]
_NVIDIA_DIR = _REPO_ROOT / "src" / "byte_mcp" / "nvidia"
_CANARY_PATH = _NVIDIA_DIR / "canary.py"
_CANARY_EVIDENCE_PATH = _NVIDIA_DIR / "canary_evidence.py"
_SETTINGS_PATH = _NVIDIA_DIR / "settings.py"
_SERVER_PATH = _REPO_ROOT / "src" / "byte_mcp" / "server.py"
_CLI_PATH = _REPO_ROOT / "scripts" / "nvidia_lightning_canary.py"

_PREPARED_AT = datetime(2026, 9, 10, 8, 0, 0, tzinfo=UTC)


def _import_targets(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            targets.append("." * node.level + (node.module or ""))
    return tuple(targets)


def _function_node(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} was not found in {path}")


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _prepare(store: NvidiaCanaryEvidenceStore):
    return prepare_lightning_canary(store, now=lambda: _PREPARED_AT)


def _transmit_clock():
    values = iter(
        (
            _PREPARED_AT + timedelta(seconds=1),
            _PREPARED_AT + timedelta(seconds=2),
        )
    )
    return lambda: next(values)


def _success_result(prepared, context, *, content: str = NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT):
    finished = datetime.fromisoformat(context.provider_started_at) + timedelta(milliseconds=5)
    finished_at = finished.isoformat()
    observation = ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at=finished_at,
        response_headers_elapsed_ms=1,
        http_status_code=200,
        response_body_started=True,
        first_body_at=finished_at,
        first_body_elapsed_ms=2,
        last_body_at=finished_at,
        last_body_elapsed_ms=4,
        decoded_body_bytes_received=len(content.encode("utf-8")),
        provider_started_at=context.provider_started_at,
        provider_finished_at=finished_at,
        elapsed_ms=5,
        transport_failure_kind=None,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )
    return NvidiaChatResult(
        model_id=NVIDIA_LIGHTNING_CANARY_MODEL_ID,
        content=content,
        finish_reason="stop",
        response_id="chatcmpl-n02-security",
        usage=None,
        request_sha256=prepared.request_sha256,
        payload_sha256=prepared.payload_sha256,
        transport_observation=observation,
    )


def test_canary_modules_do_not_import_ox_or_wolfram() -> None:
    for path in (_CANARY_PATH, _CANARY_EVIDENCE_PATH):
        targets = _import_targets(path)
        assert not any(
            "ox" in target.lower().split(".") or "wolfram" in target.lower().split(".")
            for target in targets
        )


def test_server_has_no_nvidia_canary_or_inference_registration() -> None:
    source = _SERVER_PATH.read_text(encoding="utf-8")
    imports = _import_targets(_SERVER_PATH)

    assert not any("nvidia" in target.lower() for target in imports)
    for forbidden in (
        "prepare_lightning_canary",
        "inspect_lightning_canary",
        "transmit_lightning_canary",
        "execute_prepared_nvidia_chat",
        "nvidia_lightning_canary",
    ):
        assert forbidden not in source


def test_transmit_has_no_catalog_or_registry_calls() -> None:
    function = _function_node(_CANARY_PATH, "transmit_lightning_canary")
    calls = {_call_name(node).lower() for node in ast.walk(function) if isinstance(node, ast.Call)}
    assert not any("catalog" in name or "registry" in name for name in calls)


def test_canary_source_has_no_retry_backoff_sleep_fallback_or_replay_machinery() -> None:
    tree = ast.parse(_CANARY_PATH.read_text(encoding="utf-8"), filename=str(_CANARY_PATH))
    forbidden = ("retry", "backoff", "sleep", "fallback", "replay")

    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lowered = node.name.lower()
            assert not any(token in lowered for token in forbidden)
        elif isinstance(node, ast.Call):
            lowered = _call_name(node).lower()
            assert not any(token in lowered for token in forbidden)


def test_cli_has_no_credential_model_endpoint_prompt_retry_or_fallback_override() -> None:
    source = _CLI_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "--api-key",
        "--token",
        "--credential",
        "--model",
        "--endpoint",
        "--prompt",
        "--retry",
        "--fallback",
        "--yes",
    ):
        assert forbidden not in source


def test_tracked_nvidia_files_contain_no_nvapi_sentinel() -> None:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "src/byte_mcp/nvidia",
            "tests/nvidia",
            "scripts/nvidia_lightning_canary.py",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line for line in completed.stdout.splitlines() if line]
    sentinel = b"nv" + b"api-"

    assert tracked
    for relative_path in tracked:
        assert sentinel not in (_REPO_ROOT / relative_path).read_bytes(), relative_path


def test_evidence_excludes_secret_authorization_and_response_content(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    secret = "nv" + "api-" + "N02-SECRET-SENTINEL"
    authorization = f"Bearer {secret}"
    settings = NvidiaHostedSettings(api_key=secret)

    async def executor(prepared, context, actual_settings):
        assert actual_settings is settings
        return _success_result(prepared, context, content=authorization)

    result = asyncio.run(
        transmit_lightning_canary(
            store,
            canary_id=receipt.canary_id,
            expected_request_sha256=receipt.request_sha256,
            approve=True,
            settings_loader=lambda: settings,
            executor=executor,
            now=_transmit_clock(),
        )
    )
    assert result.semantic_probe_match is False

    durable = b"".join(
        path.read_bytes() for path in sorted(store.root.rglob("*")) if path.is_file()
    )
    assert secret.encode("utf-8") not in durable
    assert authorization.encode("utf-8") not in durable


def test_prepare_and_inspect_never_call_settings_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")

    def forbidden_load(cls):
        raise AssertionError("prepare/inspect must not load NVIDIA settings")

    monkeypatch.setattr(NvidiaHostedSettings, "load", classmethod(forbidden_load))
    receipt = _prepare(store)
    inspection = inspect_lightning_canary(store, receipt.canary_id)

    assert inspection.request_sha256 == receipt.request_sha256


def test_executor_receives_exact_persisted_request_body(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    persisted = (store.root / "canaries" / receipt.canary_id / "request-body.bin").read_bytes()
    settings = NvidiaHostedSettings(api_key="N02-EXACT-BYTES-SENTINEL")
    calls = 0

    async def executor(prepared, context, actual_settings):
        nonlocal calls
        calls += 1
        assert actual_settings is settings
        assert prepared.body_bytes == persisted
        return _success_result(prepared, context)

    asyncio.run(
        transmit_lightning_canary(
            store,
            canary_id=receipt.canary_id,
            expected_request_sha256=receipt.request_sha256,
            approve=True,
            settings_loader=lambda: settings,
            executor=executor,
            now=_transmit_clock(),
        )
    )
    assert calls == 1


def test_wrong_request_hash_has_zero_executor_calls(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    calls = 0

    async def executor(prepared, context, settings):
        nonlocal calls
        calls += 1
        return _success_result(prepared, context)

    with pytest.raises(ValueError, match="request identity"):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256="0" * 64,
                approve=True,
                settings_loader=lambda: NvidiaHostedSettings(api_key="N02-HASH-SENTINEL"),
                executor=executor,
                now=_transmit_clock(),
            )
        )
    assert calls == 0


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("provider_id", "other-provider"),
        ("model_id", "other/model"),
        ("target_origin", "https://example.invalid"),
        ("endpoint_path", "/v1/other"),
    ],
)
def test_wrong_target_identity_has_zero_executor_calls(
    tmp_path: Path,
    field_name: str,
    replacement: str,
) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    manifest_path = store.root / "canaries" / receipt.canary_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field_name] = replacement
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    calls = 0

    async def executor(prepared, context, settings):
        nonlocal calls
        calls += 1
        return _success_result(prepared, context)

    with pytest.raises(NvidiaCanaryEvidenceError):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: NvidiaHostedSettings(api_key="N02-TARGET-SENTINEL"),
                executor=executor,
                now=_transmit_clock(),
            )
        )
    assert calls == 0


def test_duplicate_transmit_has_at_most_one_start_and_one_executor_call(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    settings = NvidiaHostedSettings(api_key="N02-DUPLICATE-SENTINEL")
    calls = 0

    async def scenario() -> None:
        nonlocal calls
        entered = asyncio.Event()
        release = asyncio.Event()

        async def executor(prepared, context, actual_settings):
            nonlocal calls
            calls += 1
            assert actual_settings is settings
            entered.set()
            await release.wait()
            return _success_result(prepared, context)

        first = asyncio.create_task(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: settings,
                executor=executor,
                now=_transmit_clock(),
            )
        )
        await entered.wait()
        with pytest.raises(NvidiaCanaryLockError):
            await transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: settings,
                executor=executor,
                now=_transmit_clock(),
            )
        release.set()
        await first

    asyncio.run(scenario())
    snapshot = store.load(receipt.canary_id)
    starts = [event for event in snapshot.events if event["event_type"] == "PROVIDER_START"]
    assert calls == 1
    assert len(starts) == 1


def test_provider_start_without_terminal_blocks_retransmission(tmp_path: Path) -> None:
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = _prepare(store)
    settings = NvidiaHostedSettings(api_key="N02-AMBIGUOUS-SENTINEL")
    calls = 0

    async def crash_executor(prepared, context, actual_settings):
        nonlocal calls
        calls += 1
        assert actual_settings is settings
        raise RuntimeError("synthetic post-start crash")

    with pytest.raises(RuntimeError, match="post-start crash"):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: settings,
                executor=crash_executor,
                now=_transmit_clock(),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert snapshot.provider_started_at is not None
    assert snapshot.terminal_event is None

    with pytest.raises(ValueError, match="provider-start already exists"):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: settings,
                executor=crash_executor,
                now=_transmit_clock(),
            )
        )
    assert calls == 1


def test_no_a002_retry_path_or_models_catalog_operation_exists() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (_CANARY_PATH, _CANARY_EVIDENCE_PATH, _CLI_PATH)
    )
    assert "A002" not in sources
    assert "/v1/models" not in sources
    assert "--retry" not in _CLI_PATH.read_text(encoding="utf-8")


def test_nvidia_api_key_is_accessed_only_by_settings_load_for_transmit() -> None:
    key_literal = "NVIDIA" + "_API_KEY"
    occurrences: dict[str, int] = {}
    for path in sorted(_NVIDIA_DIR.glob("*.py")):
        count = path.read_text(encoding="utf-8").count(key_literal)
        if count:
            occurrences[path.name] = count
    assert occurrences == {"settings.py": 1}

    settings_tree = ast.parse(
        _SETTINGS_PATH.read_text(encoding="utf-8"),
        filename=str(_SETTINGS_PATH),
    )
    load_node = _function_node(_SETTINGS_PATH, "load")
    module_key_literals = [
        node
        for node in ast.walk(settings_tree)
        if isinstance(node, ast.Constant) and node.value == key_literal
    ]
    load_key_literals = [
        node
        for node in ast.walk(load_node)
        if isinstance(node, ast.Constant) and node.value == key_literal
    ]
    assert len(module_key_literals) == 1
    assert len(load_key_literals) == 1

    for function_name, expected_load_refs in (
        ("prepare_lightning_canary", 0),
        ("inspect_lightning_canary", 0),
        ("transmit_lightning_canary", 1),
    ):
        function = _function_node(_CANARY_PATH, function_name)
        refs = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Attribute)
            and node.attr == "load"
            and isinstance(node.value, ast.Name)
            and node.value.id == "NvidiaHostedSettings"
        ]
        assert len(refs) == expected_load_refs


def test_replay_protection_is_scoped_to_the_selected_evidence_root(tmp_path: Path) -> None:
    first_store = NvidiaCanaryEvidenceStore(tmp_path / "authority-a")
    second_store = NvidiaCanaryEvidenceStore(tmp_path / "authority-b")
    receipt = _prepare(first_store)

    assert first_store.root != second_store.root
    with pytest.raises(NvidiaCanaryEvidenceError, match="does not exist|unable to read"):
        second_store.load(receipt.canary_id)

    assert canary_cli.NvidiaCanaryEvidenceStore is NvidiaCanaryEvidenceStore
