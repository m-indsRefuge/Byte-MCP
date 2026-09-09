from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from byte_mcp.nvidia import (
    NvidiaChatError,
    NvidiaChatFailureKind,
    NvidiaChatMessage,
    NvidiaHostedSettings,
    execute_prepared_nvidia_chat,
    prepare_nvidia_chat_request,
)
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransmissionContext,
    ProviderTransportError,
    ProviderTransportFailureKind,
)

_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
_KEY = "NVIDIA-SENTINEL-SECRET"


def _prepared():
    return prepare_nvidia_chat_request(
        model_id=_MODEL,
        messages=(NvidiaChatMessage(role="user", content="Return exactly: OK"),),
        max_tokens=8,
    )


def _context(prepared, *, expected_request_sha256: str | None = None):
    return ProviderTransmissionContext(
        provider_started_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC).isoformat(),
        expected_request_sha256=expected_request_sha256 or prepared.request_sha256,
    )


def _success_body() -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-test",
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 1,
                "total_tokens": 5,
            },
        }
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_missing_key_fails_configuration_without_network_call():
    prepared = _prepared()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_success_body(), request=request)

    with pytest.raises(NvidiaChatError) as caught:
        await execute_prepared_nvidia_chat(
            prepared,
            _context(prepared),
            NvidiaHostedSettings(api_key=None),
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0
    assert caught.value.kind is NvidiaChatFailureKind.CONFIGURATION
    assert caught.value.attempt_outcome is ProviderAttemptOutcome.NOT_SENT


@pytest.mark.asyncio
async def test_success_transmits_exact_prepared_bytes_once_with_bearer_key():
    prepared = _prepared()
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert request.content == prepared.body_bytes
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, content=_success_body(), request=request)

    result = await execute_prepared_nvidia_chat(
        prepared,
        _context(prepared),
        NvidiaHostedSettings(api_key=_KEY),
        transport=httpx.MockTransport(handler),
    )

    assert len(calls) == 1
    assert result.model_id == _MODEL
    assert result.content == "OK"
    assert result.request_sha256 == prepared.request_sha256
    assert result.payload_sha256 == prepared.payload_sha256
    for rendered in (repr(prepared), repr(result), repr(result.transport_observation)):
        assert _KEY not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_kind"),
    [
        (302, NvidiaChatFailureKind.REDIRECT_REJECTED),
        (400, NvidiaChatFailureKind.REQUEST),
        (401, NvidiaChatFailureKind.AUTHENTICATION),
        (403, NvidiaChatFailureKind.PERMISSION),
        (404, NvidiaChatFailureKind.MODEL_OR_ENDPOINT_UNAVAILABLE),
        (413, NvidiaChatFailureKind.REQUEST_TOO_LARGE),
        (422, NvidiaChatFailureKind.REQUEST),
        (429, NvidiaChatFailureKind.RATE_LIMIT),
        (503, NvidiaChatFailureKind.PROVIDER_UNAVAILABLE),
    ],
)
async def test_complete_rejections_are_classified_once_without_secret_or_body_prose(
    status_code,
    expected_kind,
):
    prepared = _prepared()
    calls = 0
    provider_prose = "SENTINEL provider detail that must not escape"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text=provider_prose, request=request)

    with pytest.raises(NvidiaChatError) as caught:
        await execute_prepared_nvidia_chat(
            prepared,
            _context(prepared),
            NvidiaHostedSettings(api_key=_KEY),
            transport=httpx.MockTransport(handler),
        )

    assert calls == 1
    assert caught.value.kind is expected_kind
    assert caught.value.attempt_outcome is ProviderAttemptOutcome.REJECTED
    assert provider_prose not in str(caught.value)
    assert provider_prose not in repr(caught.value)
    assert _KEY not in str(caught.value)
    assert _KEY not in repr(caught.value)


@pytest.mark.asyncio
async def test_request_hash_mismatch_fails_locally_with_zero_calls():
    prepared = _prepared()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_success_body(), request=request)

    with pytest.raises(ValueError, match="request_sha256"):
        await execute_prepared_nvidia_chat(
            prepared,
            _context(prepared, expected_request_sha256="0" * 64),
            NvidiaHostedSettings(api_key=_KEY),
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


@pytest.mark.asyncio
async def test_provider_transport_error_propagates_without_reclassification_or_retry():
    prepared = _prepared()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("SENTINEL raw transport detail", request=request)

    with pytest.raises(ProviderTransportError) as caught:
        await execute_prepared_nvidia_chat(
            prepared,
            _context(prepared),
            NvidiaHostedSettings(api_key=_KEY),
            transport=httpx.MockTransport(handler),
        )

    assert calls == 1
    assert caught.value.attempt_outcome is ProviderAttemptOutcome.OUTCOME_UNKNOWN
    assert caught.value.transport_failure_kind is ProviderTransportFailureKind.READ_ERROR
    assert "SENTINEL raw transport detail" not in str(caught.value)
    assert "SENTINEL raw transport detail" not in repr(caught.value)
