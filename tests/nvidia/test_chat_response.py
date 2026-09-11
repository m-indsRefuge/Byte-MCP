from __future__ import annotations

import json

import pytest

from byte_mcp.nvidia import (
    NvidiaChatError,
    NvidiaChatFailureKind,
    NvidiaChatResult,
    NvidiaChatUsage,
    classify_nvidia_chat_rejection,
    parse_nvidia_chat_response,
    prepare_nvidia_chat_request,
)
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransportObservation,
    ProviderTransportResponse,
)

MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"


def _prepared():
    return prepare_nvidia_chat_request(
        model_id=MODEL_ID,
        messages=[{"role": "user", "content": "hello"}],
    )


def _observation(status_code: int) -> ProviderTransportObservation:
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at="2026-09-09T08:00:00+00:00",
        response_headers_elapsed_ms=10,
        http_status_code=status_code,
        response_body_started=True,
        first_body_at="2026-09-09T08:00:00.010000+00:00",
        first_body_elapsed_ms=10,
        last_body_at="2026-09-09T08:00:00.020000+00:00",
        last_body_elapsed_ms=20,
        decoded_body_bytes_received=20,
        provider_started_at="2026-09-09T08:00:00+00:00",
        provider_finished_at="2026-09-09T08:00:00.020000+00:00",
        elapsed_ms=20,
        transport_failure_kind=None,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def _response(
    *,
    status_code: int = 200,
    outcome: ProviderAttemptOutcome = ProviderAttemptOutcome.COMPLETED,
    body: bytes,
) -> ProviderTransportResponse:
    return ProviderTransportResponse(
        outcome=outcome,
        status_code=status_code,
        body=body,
        observation=_observation(status_code),
    )


@pytest.mark.parametrize(
    ("status_code", "kind"),
    [
        (301, NvidiaChatFailureKind.REDIRECT_REJECTED),
        (399, NvidiaChatFailureKind.REDIRECT_REJECTED),
        (400, NvidiaChatFailureKind.REQUEST),
        (401, NvidiaChatFailureKind.AUTHENTICATION),
        (403, NvidiaChatFailureKind.PERMISSION),
        (404, NvidiaChatFailureKind.MODEL_OR_ENDPOINT_UNAVAILABLE),
        (409, NvidiaChatFailureKind.REQUEST),
        (413, NvidiaChatFailureKind.REQUEST_TOO_LARGE),
        (422, NvidiaChatFailureKind.REQUEST),
        (429, NvidiaChatFailureKind.RATE_LIMIT),
        (500, NvidiaChatFailureKind.PROVIDER_UNAVAILABLE),
        (599, NvidiaChatFailureKind.PROVIDER_UNAVAILABLE),
    ],
)
def test_complete_rejections_map_by_status_only(
    status_code: int,
    kind: NvidiaChatFailureKind,
) -> None:
    prepared = _prepared()
    response = _response(
        status_code=status_code,
        outcome=ProviderAttemptOutcome.REJECTED,
        body=b'{"error":{"message":"PROVIDER SECRET PROSE"}}',
    )

    error = classify_nvidia_chat_rejection(prepared, response)

    assert error.kind is kind
    assert error.attempt_outcome is ProviderAttemptOutcome.REJECTED
    assert error.request_sha256 == prepared.request_sha256
    assert error.transport_observation is response.observation
    assert "PROVIDER SECRET PROSE" not in str(error)
    assert "PROVIDER SECRET PROSE" not in repr(error)


def test_rejection_classifier_requires_rejected_transport_outcome() -> None:
    with pytest.raises(ValueError, match="REJECTED"):
        classify_nvidia_chat_rejection(
            _prepared(),
            _response(status_code=200, body=b"{}"),
        )


def test_parse_successful_chat_response_retains_only_bounded_result_fields() -> None:
    prepared = _prepared()
    payload = {
        "id": "chatcmpl-safe-id",
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "provider answer Ω",
                    "ignored_message_field": "discard",
                },
                "finish_reason": "stop",
                "ignored_choice_field": "discard",
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "total_tokens": 12,
            "ignored_usage_field": 999,
        },
        "ignored_top_level": "discard",
    }
    response = _response(body=json.dumps(payload).encode("utf-8"))

    result = parse_nvidia_chat_response(prepared, response)

    assert result == NvidiaChatResult(
        model_id=MODEL_ID,
        content="provider answer Ω",
        finish_reason="stop",
        response_id="chatcmpl-safe-id",
        usage=NvidiaChatUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
        request_sha256=prepared.request_sha256,
        payload_sha256=prepared.payload_sha256,
        transport_observation=response.observation,
    )
    assert "provider answer" not in repr(result)
    assert "content=" not in repr(result)


def test_parse_allows_optional_id_finish_reason_and_usage() -> None:
    payload = {
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    result = parse_nvidia_chat_response(
        _prepared(),
        _response(body=json.dumps(payload).encode("utf-8")),
    )
    assert result.response_id is None
    assert result.finish_reason is None
    assert result.usage is None
    assert result.content == ""


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        json.dumps({"model": "other/model", "choices": []}).encode(),
        json.dumps({"model": MODEL_ID, "choices": []}).encode(),
        json.dumps(
            {
                "model": MODEL_ID,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "a"}},
                    {"index": 1, "message": {"role": "assistant", "content": "b"}},
                ],
            }
        ).encode(),
        json.dumps(
            {
                "model": MODEL_ID,
                "choices": [{"index": 1, "message": {"role": "assistant", "content": "a"}}],
            }
        ).encode(),
        json.dumps(
            {
                "model": MODEL_ID,
                "choices": [{"index": 0, "message": {"role": "user", "content": "a"}}],
            }
        ).encode(),
        json.dumps(
            {
                "model": MODEL_ID,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": 1}}],
            }
        ).encode(),
    ],
)
def test_malformed_complete_2xx_is_protocol_failure_not_transport_unknown(body: bytes) -> None:
    prepared = _prepared()
    response = _response(body=body)

    with pytest.raises(NvidiaChatError) as captured:
        parse_nvidia_chat_response(prepared, response)

    error = captured.value
    assert error.kind is NvidiaChatFailureKind.PROTOCOL
    assert error.attempt_outcome is ProviderAttemptOutcome.COMPLETED
    assert error.transport_observation is response.observation
    assert error.request_sha256 == prepared.request_sha256


@pytest.mark.parametrize(
    "finish_reason",
    ["x" * 65, "has space", "slash/value", "Ω"],
)
def test_invalid_finish_reason_is_protocol_failure(finish_reason: str) -> None:
    payload = {
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": finish_reason,
            }
        ],
    }
    with pytest.raises(NvidiaChatError) as captured:
        parse_nvidia_chat_response(
            _prepared(),
            _response(body=json.dumps(payload).encode()),
        )
    assert captured.value.kind is NvidiaChatFailureKind.PROTOCOL


@pytest.mark.parametrize(
    "response_id",
    ["x" * 257, "bad\ncontrol", 123],
)
def test_invalid_response_id_is_protocol_failure(response_id: object) -> None:
    payload = {
        "id": response_id,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
    }
    with pytest.raises(NvidiaChatError) as captured:
        parse_nvidia_chat_response(
            _prepared(),
            _response(body=json.dumps(payload).encode()),
        )
    assert captured.value.kind is NvidiaChatFailureKind.PROTOCOL


@pytest.mark.parametrize(
    "usage",
    [
        [],
        {"prompt_tokens": -1},
        {"prompt_tokens": True},
        {"completion_tokens": 2_147_483_648},
        {"total_tokens": 1.5},
    ],
)
def test_invalid_usage_is_protocol_failure(usage: object) -> None:
    payload = {
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }
    with pytest.raises(NvidiaChatError) as captured:
        parse_nvidia_chat_response(
            _prepared(),
            _response(body=json.dumps(payload).encode()),
        )
    assert captured.value.kind is NvidiaChatFailureKind.PROTOCOL


def test_parser_requires_completed_2xx_transport_result() -> None:
    response = _response(
        status_code=400,
        outcome=ProviderAttemptOutcome.REJECTED,
        body=b"{}",
    )
    with pytest.raises(ValueError, match="COMPLETED"):
        parse_nvidia_chat_response(_prepared(), response)
