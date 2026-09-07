import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from byte_mcp.errors import (
    OXAuthenticationError,
    OXContextLimitError,
    OXFindingValidationError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRequestError,
    OXTransportError,
    OXTransportFailureKind,
)
from byte_mcp.ox.client import OXClient
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import (
    AttemptOutcome,
    ProviderResult,
    ProviderTransportObservation,
    ProviderUsage,
)

SENTINEL = "Q03JA-SENSITIVE-CONTENT"
MANIFEST_SHA256 = "a" * 64
RUNTIME_SESSION_ID = "b" * 32
ATTEMPT_ID = "OX-000001-A001"
MESSAGES = [{"role": "user", "content": "q03ja diagnostic"}]
Q03JA_FIELDS = (
    "response_headers_received",
    "response_headers_at",
    "response_headers_elapsed_ms",
    "http_status_code",
    "response_body_started",
    "first_body_at",
    "first_body_elapsed_ms",
    "last_body_at",
    "last_body_elapsed_ms",
    "decoded_body_bytes_received",
    "trust_env_enabled",
    "proxy_environment_present",
)


def observation(
    *,
    kind: OXTransportFailureKind | None = None,
    status_code: int = 200,
) -> ProviderTransportObservation:
    return ProviderTransportObservation(
        response_headers_received=True,
        response_headers_at="2026-09-05T08:00:01+00:00",
        response_headers_elapsed_ms=1000,
        http_status_code=status_code,
        response_body_started=True,
        first_body_at="2026-09-05T08:00:02+00:00",
        first_body_elapsed_ms=2000,
        last_body_at="2026-09-05T08:00:03+00:00",
        last_body_elapsed_ms=3000,
        decoded_body_bytes_received=128,
        provider_finished_at="2026-09-05T08:00:04+00:00",
        elapsed_ms=4000,
        transport_failure_kind=kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def _assert_bounded_diagnostic_state(value: object) -> None:
    assert not isinstance(value, BaseException)
    if isinstance(value, str):
        assert SENTINEL not in value
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _assert_bounded_diagnostic_state(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_bounded_diagnostic_state(key)
            _assert_bounded_diagnostic_state(item)
    elif isinstance(value, tuple | list | set | frozenset):
        for item in value:
            _assert_bounded_diagnostic_state(item)


def test_q03ja_observation_has_exact_bounded_schema() -> None:
    value = observation()

    assert {field.name: field.type for field in fields(value)} == {
        "response_headers_received": bool,
        "response_headers_at": str | None,
        "response_headers_elapsed_ms": int | None,
        "http_status_code": int | None,
        "response_body_started": bool,
        "first_body_at": str | None,
        "first_body_elapsed_ms": int | None,
        "last_body_at": str | None,
        "last_body_elapsed_ms": int | None,
        "decoded_body_bytes_received": int,
        "provider_finished_at": str,
        "elapsed_ms": int,
        "transport_failure_kind": OXTransportFailureKind | None,
        "trust_env_enabled": bool,
        "proxy_environment_present": bool,
    }
    assert asdict(value) == {
        "response_headers_received": True,
        "response_headers_at": "2026-09-05T08:00:01+00:00",
        "response_headers_elapsed_ms": 1000,
        "http_status_code": 200,
        "response_body_started": True,
        "first_body_at": "2026-09-05T08:00:02+00:00",
        "first_body_elapsed_ms": 2000,
        "last_body_at": "2026-09-05T08:00:03+00:00",
        "last_body_elapsed_ms": 3000,
        "decoded_body_bytes_received": 128,
        "provider_finished_at": "2026-09-05T08:00:04+00:00",
        "elapsed_ms": 4000,
        "transport_failure_kind": None,
        "trust_env_enabled": True,
        "proxy_environment_present": False,
    }
    assert not hasattr(value, "__dict__")
    _assert_bounded_diagnostic_state(value)


def test_q03ja_observation_is_immutable_and_provider_result_can_carry_it() -> None:
    value = observation()
    result = ProviderResult("ok", transport_observation=value)

    assert result.transport_observation is value
    with pytest.raises(FrozenInstanceError):
        value.elapsed_ms = 5  # type: ignore[misc]


def test_q03ja_provider_result_preserves_all_legacy_positional_arguments() -> None:
    usage = ProviderUsage(7, 3, 10, 1)
    raw_response = {"id": "resp-123", "choices": []}
    result = ProviderResult("answer", usage, "resp-123", "zai/glm-5.3-flash", raw_response)

    assert result.content == "answer"
    assert result.usage is usage
    assert result.response_id == "resp-123"
    assert result.model == "zai/glm-5.3-flash"
    assert result.raw_response is raw_response
    assert result.transport_observation is None
    assert ProviderResult("answer").transport_observation is None


@pytest.mark.parametrize(
    ("error_type", "status_code", "outcome"),
    [
        (OXAuthenticationError, 401, "REJECTED"),
        (OXPermissionError, 403, "REJECTED"),
        (OXRequestError, 400, "REJECTED"),
        (OXContextLimitError, 400, "REJECTED"),
        (OXRateLimitError, 429, "REJECTED"),
        (OXQuotaError, 429, "REJECTED"),
        (OXProviderUnavailableError, 503, "REJECTED"),
        (OXProtocolError, 200, "COMPLETED"),
        (OXFindingValidationError, 200, "COMPLETED"),
    ],
)
def test_q03ja_provider_errors_carry_optional_observation(error_type, status_code, outcome) -> None:
    value = observation(status_code=status_code)
    error = error_type(attempt_outcome=outcome, transport_observation=value)
    legacy = error_type(attempt_outcome=outcome)

    assert error.transport_observation is value
    assert error.__dict__ == {"attempt_outcome": outcome, "transport_observation": value}
    assert error.args == ()
    assert legacy.__dict__ == {"attempt_outcome": outcome}
    assert legacy.args == ()
    _assert_bounded_diagnostic_state(error.__dict__)


def test_q03ja_transport_error_preserves_bounded_legacy_diagnostics() -> None:
    value = observation(kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR)
    error = OXTransportError(
        attempt_outcome="OUTCOME_UNKNOWN",
        transport_failure_kind=OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        provider_started_at="2026-09-05T08:00:00+00:00",
        provider_finished_at=value.provider_finished_at,
        elapsed_ms=value.elapsed_ms,
        transport_observation=value,
    )

    assert error.transport_observation is value
    assert error.transport_failure_kind is OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
    assert error.__dict__ == {
        "attempt_outcome": "OUTCOME_UNKNOWN",
        "transport_failure_kind": OXTransportFailureKind.REMOTE_PROTOCOL_ERROR,
        "provider_started_at": "2026-09-05T08:00:00+00:00",
        "provider_finished_at": "2026-09-05T08:00:04+00:00",
        "elapsed_ms": 4000,
        "transport_observation": value,
    }
    assert error.args == ()
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_bounded_diagnostic_state(error.__dict__)


@pytest.mark.parametrize("error_type", [OXProtocolError, OXTransportError])
@pytest.mark.parametrize("forbidden_field", ["headers", "body", "exception", "proxy_url"])
def test_q03ja_provider_errors_reject_unbounded_keywords(error_type, forbidden_field) -> None:
    with pytest.raises(TypeError):
        error_type(transport_observation=observation(), **{forbidden_field: SENTINEL})


@pytest.mark.parametrize("unsafe_value", [SENTINEL, RuntimeError(SENTINEL)])
def test_q03ja_privacy_walker_inspects_dataclass_slots(unsafe_value) -> None:
    # Deliberately invalid data proves the test walker reaches fields without __dict__.
    value = replace(observation(), response_headers_at=unsafe_value)

    with pytest.raises(AssertionError):
        _assert_bounded_diagnostic_state({"transport_observation": value})


class _FailingStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes, message: str) -> None:
        self._payload = payload
        self._message = message

    async def __aiter__(self):
        yield self._payload
        raise httpx.ReadError(self._message)


def _success_payload() -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-q03ja",
            "model": "zai/glm-5.3-flash",
            "choices": [
                {"message": {"role": "assistant", "content": "diagnostic success"}}
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        },
        separators=(",", ":"),
    ).encode()


def _prepare_started_attempt(store: EvidenceStore) -> tuple[str, str]:
    review_id = store.persist_prepared_review(
        identity={
            "repository": "fixture",
            "subsystem": "privacy",
            "objective": "bounded diagnostics",
        },
        manifest={"manifest_sha256": MANIFEST_SHA256},
        bundle={"packet": "prepared"},
    )
    attempt = store.claim_initial_transmission(
        review_id,
        MANIFEST_SHA256,
        runtime_session_id=RUNTIME_SESSION_ID,
    )
    attempt_id = str(attempt["attempt_id"])
    store.record_provider_request_started(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        phase="initial",
    )
    return review_id, attempt_id


def test_q03ja_request_body_and_q03i_attribution_are_unchanged(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, content=_success_payload())

    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    client = OXClient(
        SimpleNamespace(api_key="test-key", max_output_tokens=128),
        transport=httpx.MockTransport(handler),
    )
    client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    body = captured["body"]
    headers = captured["headers"]
    assert isinstance(body, dict)
    assert isinstance(headers, dict)
    assert body["stream"] is False
    assert body["model"] == "zai/glm-5.3-flash"
    assert body["providerOptions"] == {"gateway": {"only": ["zai"]}}
    assert headers["ai-reporting-tags"] == (
        "component:byte-mcp-ox,review:OX-000001,attempt:OX-000001-A001"
    )
    assert "ai-reporting-user" not in headers


def test_q03ja_diagnostics_never_persist_secrets_or_partial_content(
    monkeypatch,
    tmp_path,
) -> None:
    sentinel = "Q03JA-SECRET-SENTINEL"
    monkeypatch.setenv("HTTP_PROXY", f"http://{sentinel}.invalid")
    monkeypatch.setenv("HTTPS_PROXY", f"http://{sentinel}.invalid")

    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _prepare_started_attempt(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_FailingStream(
                f'{{"partial":"{sentinel}"'.encode(),
                f"transport failure {sentinel}",
            ),
        )

    client = OXClient(
        SimpleNamespace(api_key=sentinel, max_output_tokens=128),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OXTransportError) as raised:
        client.complete(MESSAGES, json_mode=False, attempt_id=ATTEMPT_ID)

    error = raised.value
    value = error.transport_observation
    assert error.transport_failure_kind is OXTransportFailureKind.READ_ERROR
    assert value.proxy_environment_present is True
    assert sentinel not in repr(error.__dict__)
    assert sentinel not in repr(value)
    assert sentinel not in str(error)

    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.OUTCOME_UNKNOWN)
    store.record_provider_transport_metadata(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        observation=value,
    )
    events = (tmp_path / "reviews" / review_id / "events.jsonl").read_bytes()
    assert sentinel.encode() not in events
    reconstructed = store.get_review(review_id)["attempts"][-1]
    assert reconstructed["proxy_environment_present"] is True
    assert reconstructed["decoded_body_bytes_received"] > 0


def test_q03ja_legacy_event_bytes_are_unchanged_by_reconstruction(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    review_id, attempt_id = _prepare_started_attempt(store)
    store.record_attempt_outcome(review_id, attempt_id, AttemptOutcome.OUTCOME_UNKNOWN)
    store.record_provider_transport_metadata(
        review_id,
        attempt_id,
        runtime_session_id=RUNTIME_SESSION_ID,
        provider_finished_at=datetime.now(UTC).isoformat(),
        elapsed_ms=17,
        transport_failure_kind=OXTransportFailureKind.READ_ERROR,
    )
    events_path = tmp_path / "reviews" / review_id / "events.jsonl"
    before = events_path.read_bytes()

    attempt = store.get_review(review_id)["attempts"][-1]

    after = events_path.read_bytes()
    assert after == before
    for field in Q03JA_FIELDS:
        assert field not in attempt
