from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from byte_mcp.nvidia.canary import prepare_lightning_canary, transmit_lightning_canary
from byte_mcp.nvidia.canary_evidence import NvidiaCanaryEvidenceError, NvidiaCanaryEvidenceStore
from byte_mcp.nvidia.chat import execute_prepared_nvidia_chat
from byte_mcp.nvidia.settings import NvidiaHostedSettings

AUTHORIZED_AT = "2026-09-09T18:40:00+00:00"
STARTED_AT = "2026-09-09T18:40:01+00:00"


def _clock(*values: str):
    moments = iter(values)

    def now():
        from datetime import datetime

        return datetime.fromisoformat(next(moments))

    return now


def _prepared_store(tmp_path: Path):
    store = NvidiaCanaryEvidenceStore(tmp_path / "evidence")
    receipt = prepare_lightning_canary(store)
    return store, receipt


def test_transmit_rejects_unterminated_lifecycle_record_without_mutation(tmp_path: Path) -> None:
    store, receipt = _prepared_store(tmp_path)
    store.append_authorized(
        receipt.canary_id,
        request_sha256=receipt.request_sha256,
        recorded_at=AUTHORIZED_AT,
    )
    events_path = store.root / "canaries" / receipt.canary_id / "events.jsonl"
    events_path.write_bytes(events_path.read_bytes().removesuffix(b"\n"))
    before = events_path.read_bytes()
    calls = {"settings": 0, "executor": 0}

    def settings_loader():
        calls["settings"] += 1
        return NvidiaHostedSettings(api_key="configured")

    async def executor(*args: object, **kwargs: object):
        calls["executor"] += 1
        raise AssertionError("executor must not be called for unterminated lifecycle evidence")

    with pytest.raises(NvidiaCanaryEvidenceError):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=settings_loader,
                executor=executor,
                now=_clock(STARTED_AT),
            )
        )

    assert calls == {"settings": 0, "executor": 0}
    assert events_path.read_bytes() == before


@pytest.mark.parametrize(
    "api_key",
    [
        "internal space",
        "internal\ncontrol",
        "caf\u00e9",
        "x" * 8186,
    ],
)
def test_transmit_rejects_malformed_bearer_before_lifecycle_mutation(
    tmp_path: Path,
    api_key: str,
) -> None:
    store, receipt = _prepared_store(tmp_path)
    executor_calls = 0

    async def executor(prepared_request, transmission_context, settings):
        nonlocal executor_calls
        executor_calls += 1
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": receipt.model_id,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "BYTE_NVIDIA_CANARY_OK"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        return await execute_prepared_nvidia_chat(
            prepared_request,
            transmission_context,
            settings,
            transport=transport,
        )

    with pytest.raises(ValueError):
        asyncio.run(
            transmit_lightning_canary(
                store,
                canary_id=receipt.canary_id,
                expected_request_sha256=receipt.request_sha256,
                approve=True,
                settings_loader=lambda: NvidiaHostedSettings(api_key=api_key),
                executor=executor,
                now=_clock(AUTHORIZED_AT, STARTED_AT),
            )
        )

    snapshot = store.load(receipt.canary_id)
    assert executor_calls == 0
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None
