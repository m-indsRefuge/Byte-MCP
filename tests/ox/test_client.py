import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from byte_mcp.errors import (
    OXAuthenticationError,
    OXContextLimitError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRequestError,
    OXTransportError,
    OXTransportFailureKind,
)
from byte_mcp.ox import client as client_module
from byte_mcp.ox.client import OXClient
from byte_mcp.ox.models import ProviderUsage
from byte_mcp.ox.settings import OXSettings

SECRET = "SENTINEL-SECRET"
ATTEMPT_ID = "OX-000001-A001"
MESSAGES = [
    {"role": "system", "content": "You are an independent validator."},
    {"role": "user", "content": "Review this bounded packet."},
]
SUCCESS_BODY = {
    "id": "chatcmpl-123",
    "model": "zai/glm-5.3-flash",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "The packet is reviewable."},
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 1},
    },
}


def make_settings() -> OXSettings:
    return OXSettings(SECRET, Path("repositories.json"), Path("evidence"))


def make_client(handler):
    return OXClient(make_settings(), transport=httpx.MockTransport(handler))


_APPROVED_TRANSPORT_ERROR_FIELDS = frozenset(
    {
        "attempt_outcome",
        "transport_failure_kind",
        "provider_started_at",
        "provider_finished_at",
        "elapsed_ms",
    }
)


def assert_safe_transport_error_state(
    error: OXTransportError,
    *,
    sentinel: str,
    original_exception: BaseException,
) -> None:
    assert set(error.__dict__) == _APPROVED_TRANSPORT_ERROR_FIELDS
    _assert_state_does_not_retain_transport_failure(
        error.__dict__, sentinel=sentinel, original_exception=original_exception
    )
    assert isinstance(error.attempt_outcome, str)
    assert isinstance(error.transport_failure_kind, OXTransportFailureKind)
    assert isinstance(error.provider_started_at, str)
    assert isinstance(error.provider_finished_at, str)
    assert isinstance(error.elapsed_ms, int)
    assert not isinstance(error.elapsed_ms, bool)


def _assert_state_does_not_retain_transport_failure(
    value: object,
    *,
    sentinel: str,
    original_exception: BaseException,
) -> None:
    assert value is not original_exception
    assert not isinstance(value, BaseException)
    if isinstance(value, str):
        assert sentinel not in value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_state_does_not_retain_transport_failure(
                key, sentinel=sentinel, original_exception=original_exception
            )
            _assert_state_does_not_retain_transport_failure(
                item, sentinel=sentinel, original_exception=original_exception
            )
    elif isinstance(value, tuple | list | set | frozenset):
        for item in value:
            _assert_state_does_not_retain_transport_failure(
                item, sentinel=sentinel, original_exception=original_exception
            )


def test_complete_posts_one_fixed_request_and_preserves_safe_response_evidence():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCESS_BODY)

    client = make_client(handler)
    result = client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://ai-gateway.vercel.sh/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    body = json.loads(request.content)
    assert body == {
        "messages": MESSAGES,
        "model": "zai/glm-5.3-flash",
        "stream": False,
        "max_tokens": 65_536,
        "reasoning": {"effort": "medium"},
        "providerOptions": {"gateway": {"only": ["zai"]}},
    }
    assert result.content == "The packet is reviewable."
    assert result.response_id == "chatcmpl-123"
    assert result.model == "zai/glm-5.3-flash"
    assert result.usage == ProviderUsage(
        input_tokens=7,
        output_tokens=3,
        total_tokens=10,
        cached_input_tokens=1,
    )
    assert result.raw_response == SUCCESS_BODY
    assert SECRET not in repr(client)
    assert SECRET not in repr(result)
    assert SECRET not in json.dumps(asdict(result))


def test_complete_requests_json_object_response_format_in_json_mode():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCESS_BODY)

    make_client(handler).complete(MESSAGES, json_mode=True, attempt_id=ATTEMPT_ID)

    body = json.loads(requests[0].content)
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("status", "payload", "error_type"),
    [
        (401, {"error": {"code": "invalid_api_key"}}, OXAuthenticationError),
        (403, {"error": {"code": "forbidden"}}, OXPermissionError),
        (400, {"error": {"code": "context_length_exceeded"}}, OXContextLimitError),
        (400, {"error": {"code": "invalid_request_error"}}, OXRequestError),
        (429, {"error": {"code": "rate_limit_exceeded"}}, OXRateLimitError),
        (429, {"error": {"code": "insufficient_quota"}}, OXQuotaError),
        (500, {"error": {"code": "internal_error"}}, OXProviderUnavailableError),
    ],
)
def test_complete_maps_provider_status_to_safe_domain_error(status, payload, error_type):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json=payload)

    with pytest.raises(error_type) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert calls == 1
    assert raised.value.attempt_outcome == "REJECTED"
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize(
    ("exception_type", "outcome"),
    [
        (httpx.ConnectError, "NOT_SENT"),
        (httpx.ConnectTimeout, "NOT_SENT"),
        (httpx.PoolTimeout, "NOT_SENT"),
        (httpx.WriteTimeout, "OUTCOME_UNKNOWN"),
        (httpx.ReadTimeout, "OUTCOME_UNKNOWN"),
        (httpx.ReadError, "OUTCOME_UNKNOWN"),
        (httpx.WriteError, "OUTCOME_UNKNOWN"),
        (httpx.RemoteProtocolError, "OUTCOME_UNKNOWN"),
    ],
)
def test_complete_maps_transport_failure_without_retry(exception_type, outcome):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception_type("transport failure", request=request)

    with pytest.raises(OXTransportError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert calls == 1
    assert raised.value.attempt_outcome == outcome
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


def test_q03h_ac08_ambiguous_transport_diagnostic_is_bounded_and_timed():
    sentinel = "Q03H-READ-ERROR-SENTINEL"
    calls = 0
    original_exception = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, original_exception
        calls += 1
        original_exception = httpx.ReadError(sentinel, request=request)
        raise original_exception

    earliest = datetime.now(UTC)
    with pytest.raises(OXTransportError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)
    latest = datetime.now(UTC)

    assert calls == 1
    assert raised.value.attempt_outcome == "OUTCOME_UNKNOWN"
    assert raised.value.transport_failure_kind is OXTransportFailureKind.READ_ERROR
    started_at = datetime.fromisoformat(raised.value.provider_started_at)
    finished_at = datetime.fromisoformat(raised.value.provider_finished_at)
    assert started_at.tzinfo == UTC
    assert finished_at.tzinfo == UTC
    assert earliest <= started_at <= finished_at <= latest
    assert raised.value.elapsed_ms >= 0
    assert original_exception is not None
    assert_safe_transport_error_state(
        raised.value, sentinel=sentinel, original_exception=original_exception
    )
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert sentinel not in repr(raised.value)


@pytest.mark.parametrize(
    ("exception_type", "outcome", "kind"),
    [
        (TimeoutError, "OUTCOME_UNKNOWN", OXTransportFailureKind.ABSOLUTE_DEADLINE),
        (httpx.ConnectTimeout, "NOT_SENT", OXTransportFailureKind.CONNECT_TIMEOUT),
        (httpx.ConnectError, "NOT_SENT", OXTransportFailureKind.CONNECT_ERROR),
        (httpx.PoolTimeout, "NOT_SENT", OXTransportFailureKind.POOL_TIMEOUT),
        (httpx.ReadTimeout, "OUTCOME_UNKNOWN", OXTransportFailureKind.READ_TIMEOUT),
        (httpx.ReadError, "OUTCOME_UNKNOWN", OXTransportFailureKind.READ_ERROR),
        (httpx.WriteTimeout, "OUTCOME_UNKNOWN", OXTransportFailureKind.WRITE_TIMEOUT),
        (httpx.WriteError, "OUTCOME_UNKNOWN", OXTransportFailureKind.WRITE_ERROR),
        (
            httpx.RemoteProtocolError,
            "OUTCOME_UNKNOWN",
            OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        ),
        (httpx.HTTPError, "OUTCOME_UNKNOWN", OXTransportFailureKind.HTTP_TRANSPORT_ERROR),
    ],
)
def test_q03h_ac09_transport_exception_matrix_preserves_outcome_and_kind(
    monkeypatch, exception_type, outcome, kind
):
    sentinel = f"Q03H-{exception_type.__name__}-SENTINEL"
    calls = 0
    original_exception = None

    if exception_type in (TimeoutError, httpx.HTTPError):

        async def raise_from_boundary(**kwargs):
            nonlocal calls, original_exception
            calls += 1
            original_exception = exception_type(sentinel)
            raise original_exception

        monkeypatch.setattr(client_module, "_post_with_total_deadline", raise_from_boundary)
        client = OXClient(make_settings())
    else:

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls, original_exception
            calls += 1
            original_exception = exception_type(sentinel, request=request)
            raise original_exception

        client = make_client(handler)

    with pytest.raises(OXTransportError) as raised:
        client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert calls == 1
    assert raised.value.attempt_outcome == outcome
    assert isinstance(raised.value.transport_failure_kind, OXTransportFailureKind)
    assert raised.value.transport_failure_kind is kind
    assert original_exception is not None
    assert_safe_transport_error_state(
        raised.value, sentinel=sentinel, original_exception=original_exception
    )
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert sentinel not in repr(raised.value)


@pytest.mark.parametrize(
    "malformed",
    [
        {"id": "resp", "model": "model", "choices": []},
        {"id": "resp", "model": "model", "choices": [{"message": {}}]},
        {
            "id": "resp",
            "model": "model",
            "choices": [{"message": {"role": "user", "content": "wrong"}}],
        },
        {
            "id": "resp",
            "model": "model",
            "choices": [{"message": {"role": "assistant", "content": None}}],
        },
        {
            "id": "resp",
            "model": "model",
            "choices": [
                {"message": {"role": "assistant", "content": "one"}},
                {"message": {"role": "assistant", "content": "two"}},
            ],
        },
        {"id": "resp", "model": "model", "choices": SUCCESS_BODY["choices"], "usage": []},
    ],
)
def test_complete_rejects_malformed_success_response(malformed):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=malformed)

    with pytest.raises(OXProtocolError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert calls == 1
    assert raised.value.attempt_outcome == "COMPLETED"
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


def test_complete_suppresses_response_json_failure_details():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=f'{{"content":"{SECRET}"'.encode(),
            headers={"content-type": "application/json"},
        )

    with pytest.raises(OXProtocolError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize("field", ["id", "model"])
def test_complete_rejects_unsafe_response_metadata_shape(field):
    malformed = {**SUCCESS_BODY, field: {"not": "a string"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=malformed)

    with pytest.raises(OXProtocolError):
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)


@pytest.mark.parametrize(
    "attempt_id",
    [
        "OX-000001",
        "OX-00001-A001",
        "OX-000001-A01",
        "OX-000001-A001-extra",
        "HEAD",
        None,
    ],
)
def test_complete_rejects_invalid_attempt_id_before_http_call(attempt_id):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=SUCCESS_BODY)

    with pytest.raises(OXRequestError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=attempt_id)

    assert calls == 0
    assert raised.value.attempt_outcome == "NOT_SENT"
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)


@pytest.mark.parametrize("attempt_id", ["OX-0000001-A001", "OX-000001-A0001"])
def test_complete_rejects_overlong_attempt_id_before_http_call(attempt_id):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=SUCCESS_BODY)

    with pytest.raises(OXRequestError) as raised:
        make_client(handler).complete(MESSAGES, json_mode=False, attempt_id=attempt_id)

    assert calls == 0
    assert raised.value.attempt_outcome == "NOT_SENT"
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    "messages",
    [
        "not a message sequence",
        ({"role": "user", "content": "x"} for _ in range(1)),
        ["not a mapping"],
        [{"role": "developer", "content": "x"}],
        [{"role": "user"}],
        [{"content": "x"}],
        [{"role": "user", "content": None}],
        [{"role": "user", "content": "x", "extra": object()}],
    ],
)
def test_complete_rejects_invalid_messages_before_http_call(messages):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=SUCCESS_BODY)

    with pytest.raises(OXRequestError) as raised:
        make_client(handler).complete(messages, json_mode=False, attempt_id=ATTEMPT_ID)

    assert calls == 0
    assert raised.value.attempt_outcome == "NOT_SENT"
    assert raised.value.args == ()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert SECRET not in repr(raised.value)
