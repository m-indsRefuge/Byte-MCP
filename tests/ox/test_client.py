from __future__ import annotations

import asyncio
import json

import byte_mcp.ox.client as ox_client
import httpx
import pytest
from byte_mcp.ox.client import execute_ox_transport, extract_ox_review_text

from byte_mcp.errors import OXProtocolError
from byte_mcp.ox.packet import prepare_ox_request
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTimeoutPolicy,
    ProviderTransmissionContext,
    ProviderTransportError,
    ProviderTransportFailureKind,
)

STARTED_AT = "2026-09-17T18:00:00+00:00"
API_KEY = "test-only-ox-key"


def _prepared_request():
    return prepare_ox_request(b"OX REVIEW PACKET\nOBJECTIVE:\nReview the frozen code.\n")


def _transmission_context(prepared=None) -> ProviderTransmissionContext:
    request = _prepared_request() if prepared is None else prepared
    return ProviderTransmissionContext(
        provider_started_at=STARTED_AT,
        expected_request_sha256=request.request_sha256,
    )


def _execute(*, prepared=None, context=None, transport=None):
    request = _prepared_request() if prepared is None else prepared
    transmission_context = _transmission_context(request) if context is None else context
    return asyncio.run(
        execute_ox_transport(
            request,
            transmission_context,
            api_key=API_KEY,
            transport=transport,
        )
    )


def _response_body(content: str) -> bytes:
    return json.dumps(
        {
            "id": "provider-response-id",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 123},
        }
    ).encode("utf-8")


def test_execute_ox_transport_sends_exact_prepared_request_once_without_parsing() -> None:
    prepared = _prepared_request()
    calls = 0
    seen: dict[str, object] = {}
    raw_response = b"not-json-but-transport-complete"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = await request.aread()
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, content=raw_response)

    response = _execute(prepared=prepared, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert seen == {
        "method": "POST",
        "url": "https://ai-gateway.vercel.sh/v1/chat/completions",
        "body": prepared.body_bytes,
        "authorization": f"Bearer {API_KEY}",
    }
    assert response.outcome is ProviderAttemptOutcome.COMPLETED
    assert response.status_code == 200
    assert response.body == raw_response


@pytest.mark.parametrize("status_code", [302, 400, 429, 500])
def test_execute_ox_transport_returns_complete_rejection_without_redirect_or_retry(
    status_code: int,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        headers = {"Location": "https://example.invalid/fallback"} if status_code == 302 else {}
        return httpx.Response(status_code, headers=headers, content=b"complete-rejection")

    response = _execute(transport=httpx.MockTransport(handler))

    assert calls == 1
    assert response.outcome is ProviderAttemptOutcome.REJECTED
    assert response.status_code == status_code
    assert response.body == b"complete-rejection"


def test_execute_ox_transport_rejects_request_identity_mismatch_before_transport() -> None:
    prepared = _prepared_request()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"unexpected")

    mismatched = ProviderTransmissionContext(
        provider_started_at=STARTED_AT,
        expected_request_sha256="b" * 64,
    )

    with pytest.raises(ValueError, match="request_sha256"):
        _execute(
            prepared=prepared,
            context=mismatched,
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


class _RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, exception_type: type[httpx.TransportError]) -> None:
        self.exception_type = exception_type
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise self.exception_type("RAW SECRET TRANSPORT MESSAGE", request=request)


@pytest.mark.parametrize(
    ("exception_type", "expected_outcome", "expected_kind"),
    [
        (
            httpx.ConnectTimeout,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_TIMEOUT,
        ),
        (
            httpx.ConnectError,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.CONNECT_ERROR,
        ),
        (
            httpx.PoolTimeout,
            ProviderAttemptOutcome.NOT_SENT,
            ProviderTransportFailureKind.POOL_TIMEOUT,
        ),
        (
            httpx.WriteTimeout,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_TIMEOUT,
        ),
        (
            httpx.WriteError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.WRITE_ERROR,
        ),
        (
            httpx.ReadTimeout,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_TIMEOUT,
        ),
        (
            httpx.ReadError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.READ_ERROR,
        ),
        (
            httpx.RemoteProtocolError,
            ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            ProviderTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        ),
    ],
)
def test_execute_ox_transport_preserves_shared_failure_mapping_without_retry(
    exception_type: type[httpx.TransportError],
    expected_outcome: ProviderAttemptOutcome,
    expected_kind: ProviderTransportFailureKind,
) -> None:
    transport = _RaisingTransport(exception_type)

    with pytest.raises(ProviderTransportError) as captured:
        _execute(transport=transport)

    assert transport.calls == 1
    assert captured.value.attempt_outcome is expected_outcome
    assert captured.value.transport_failure_kind is expected_kind
    assert "RAW SECRET TRANSPORT MESSAGE" not in str(captured.value)


def test_execute_ox_transport_absolute_deadline_is_outcome_unknown_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(
        ox_client,
        "OX_TIMEOUT_POLICY",
        ProviderTimeoutPolicy(
            connect_seconds=1.0,
            write_seconds=1.0,
            read_seconds=1.0,
            pool_seconds=1.0,
            absolute_deadline_seconds=0.001,
        ),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, content=b"too-late")

    with pytest.raises(ProviderTransportError) as captured:
        _execute(transport=httpx.MockTransport(handler))

    assert calls == 1
    assert captured.value.attempt_outcome is ProviderAttemptOutcome.OUTCOME_UNKNOWN
    assert captured.value.transport_failure_kind is ProviderTransportFailureKind.ABSOLUTE_DEADLINE


def test_extract_ox_review_text_preserves_arbitrary_free_form_review_exactly() -> None:
    review = "## Review\n\nI found no material issues.\n\n- No forced schema here.\n"

    assert extract_ox_review_text(_response_body(review)) == review


@pytest.mark.parametrize(
    "response_body",
    [
        b"{",
        b"\xff",
        b"[]",
        b"{}",
        json.dumps({"choices": []}).encode(),
        json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "one"}},
                    {"message": {"role": "assistant", "content": "two"}},
                ]
            }
        ).encode(),
        json.dumps({"choices": [42]}).encode(),
        json.dumps({"choices": [{"message": []}]}).encode(),
        json.dumps({"choices": [{"message": {"content": "missing role"}}]}).encode(),
        json.dumps({"choices": [{"message": {"role": "user", "content": "wrong role"}}]}).encode(),
        json.dumps({"choices": [{"message": {"role": "assistant", "content": 42}}]}).encode(),
        json.dumps({"choices": [{"message": {"role": "assistant", "content": "  \n\t"}}]}).encode(),
    ],
)
def test_extract_ox_review_text_rejects_invalid_provider_envelopes(response_body: bytes) -> None:
    with pytest.raises(OXProtocolError):
        extract_ox_review_text(response_body)


def test_extract_ox_review_text_does_not_echo_raw_invalid_response() -> None:
    raw_secret = "TOP-SECRET-RAW-RESPONSE"
    response_body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": 7, "raw": raw_secret}}]}
    ).encode()

    with pytest.raises(OXProtocolError) as captured:
        extract_ox_review_text(response_body)

    assert raw_secret not in str(captured.value)
    assert raw_secret not in repr(captured.value)
