"""Fixed, single-attempt HTTP client for the OX validation provider."""

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic_ns

import httpx

from byte_mcp.errors import (
    OXAuthenticationError,
    OXConfigurationError,
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

from .models import ProviderResult, ProviderTransportObservation, ProviderUsage
from .settings import OXSettings

_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
_MODEL = "zai/glm-5.3-flash"
_PROVIDER_OPTIONS = {"gateway": {"only": ["zai"]}}
_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)
_TOTAL_DEADLINE_SECONDS = 900.0
_ATTEMPT_ID_PATTERN = re.compile(r"^OX-\d{6}-A\d{3}$")
_SAFE_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
_TRUST_ENV = True
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

_CONTEXT_ERROR_CODES = frozenset(
    {
        "context_length_exceeded",
        "context_limit_exceeded",
        "prompt_too_long",
        "request_too_large",
    }
)
_QUOTA_ERROR_CODES = frozenset(
    {
        "billing_hard_limit_reached",
        "insufficient_quota",
        "quota_exceeded",
    }
)


@dataclass(slots=True)
class _TransportTracker:
    """Bounded in-memory receive tracker; never stores body/header content."""

    started_monotonic_ns: int
    response_headers_at: str | None = None
    response_headers_elapsed_ms: int | None = None
    http_status_code: int | None = None
    first_body_at: str | None = None
    first_body_elapsed_ms: int | None = None
    last_body_at: str | None = None
    last_body_elapsed_ms: int | None = None
    decoded_body_bytes_received: int = 0

    def _elapsed_ms(self) -> int:
        return max(0, (monotonic_ns() - self.started_monotonic_ns) // 1_000_000)

    def mark_headers(self, status_code: int) -> None:
        self.response_headers_at = datetime.now(UTC).isoformat()
        self.response_headers_elapsed_ms = self._elapsed_ms()
        self.http_status_code = status_code

    def mark_body(self, byte_count: int) -> None:
        now = datetime.now(UTC).isoformat()
        elapsed_ms = self._elapsed_ms()
        if self.decoded_body_bytes_received == 0:
            self.first_body_at = now
            self.first_body_elapsed_ms = elapsed_ms
        self.decoded_body_bytes_received += byte_count
        self.last_body_at = now
        self.last_body_elapsed_ms = elapsed_ms

    def snapshot(
        self,
        transport_failure_kind: OXTransportFailureKind | None,
    ) -> ProviderTransportObservation:
        return ProviderTransportObservation(
            response_headers_received=self.response_headers_at is not None,
            response_headers_at=self.response_headers_at,
            response_headers_elapsed_ms=self.response_headers_elapsed_ms,
            http_status_code=self.http_status_code,
            response_body_started=self.decoded_body_bytes_received > 0,
            first_body_at=self.first_body_at,
            first_body_elapsed_ms=self.first_body_elapsed_ms,
            last_body_at=self.last_body_at,
            last_body_elapsed_ms=self.last_body_elapsed_ms,
            decoded_body_bytes_received=self.decoded_body_bytes_received,
            provider_finished_at=datetime.now(UTC).isoformat(),
            elapsed_ms=self._elapsed_ms(),
            transport_failure_kind=transport_failure_kind,
            trust_env_enabled=_TRUST_ENV,
            proxy_environment_present=_proxy_environment_present(),
        )


@dataclass(frozen=True, slots=True)
class _ReceivedResponse:
    """Complete locally buffered response plus bounded receive observation."""

    status_code: int
    body: bytes
    observation: ProviderTransportObservation


async def _post_with_total_deadline(
    *,
    transport: httpx.AsyncBaseTransport | None,
    headers: Mapping[str, str],
    body: Mapping[str, object],
) -> _ReceivedResponse:
    """Issue exactly one POST and observe its non-streaming HTTP receive path."""

    provider_started_at = datetime.now(UTC).isoformat()
    tracker = _TransportTracker(monotonic_ns())
    request_error = None
    transport_outcome = None
    transport_failure_kind = None
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=_TRUST_ENV,
        ) as client:
            async with asyncio.timeout(_TOTAL_DEADLINE_SECONDS):
                chunks = bytearray()
                async with client.stream(
                    "POST",
                    _GATEWAY_URL,
                    headers=headers,
                    json=body,
                ) as response:
                    tracker.mark_headers(response.status_code)
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            tracker.mark_body(len(chunk))
                            chunks.extend(chunk)
                return _ReceivedResponse(
                    status_code=response.status_code,
                    body=bytes(chunks),
                    observation=tracker.snapshot(None),
                )
    except TimeoutError:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.ABSOLUTE_DEADLINE
    except httpx.ConnectTimeout:
        transport_outcome = "NOT_SENT"
        transport_failure_kind = OXTransportFailureKind.CONNECT_TIMEOUT
    except httpx.ConnectError:
        transport_outcome = "NOT_SENT"
        transport_failure_kind = OXTransportFailureKind.CONNECT_ERROR
    except httpx.PoolTimeout:
        transport_outcome = "NOT_SENT"
        transport_failure_kind = OXTransportFailureKind.POOL_TIMEOUT
    except httpx.ReadTimeout:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.READ_TIMEOUT
    except httpx.ReadError:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.READ_ERROR
    except httpx.WriteTimeout:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.WRITE_TIMEOUT
    except httpx.WriteError:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.WRITE_ERROR
    except httpx.RemoteProtocolError:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
    except httpx.HTTPError:
        transport_outcome = "OUTCOME_UNKNOWN"
        transport_failure_kind = OXTransportFailureKind.HTTP_TRANSPORT_ERROR

    if transport_failure_kind is not None and transport_outcome is not None:
        observation = tracker.snapshot(transport_failure_kind)
        request_error = OXTransportError(
            attempt_outcome=transport_outcome,
            transport_failure_kind=transport_failure_kind,
            provider_started_at=provider_started_at,
            provider_finished_at=observation.provider_finished_at,
            elapsed_ms=observation.elapsed_ms,
            transport_observation=observation,
        )
    if request_error is not None:
        raise request_error
    raise RuntimeError("unreachable OX transport state")


class OXClient:
    """Make one fixed, non-streaming OX provider request at a time."""

    def __init__(
        self, settings: OXSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._api_key = settings.api_key
        self._max_output_tokens = settings.max_output_tokens
        self._transport = transport

    def __repr__(self) -> str:
        return f"OXClient(api_key_configured={self._api_key is not None})"

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        json_mode: bool,
        attempt_id: str,
    ) -> ProviderResult:
        _validate_attempt_id(attempt_id)
        validated_messages = _validate_messages(messages)
        if not self._api_key:
            raise OXConfigurationError()

        body: dict[str, object] = {
            "messages": validated_messages,
            "model": _MODEL,
            "stream": False,
            "max_tokens": self._max_output_tokens,
            "reasoning": {"effort": "medium"},
            "providerOptions": _PROVIDER_OPTIONS,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        _validate_json(body)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "ai-reporting-tags": _reporting_tags(attempt_id),
        }
        request_error = None
        transport_outcome = None
        transport_failure_kind = None
        provider_started_at = datetime.now(UTC).isoformat()
        started_monotonic_ns = monotonic_ns()
        try:
            response = asyncio.run(
                _post_with_total_deadline(
                    transport=self._transport,
                    headers=headers,
                    body=body,
                )
            )
        except OXTransportError as error:
            request_error = error
        except TimeoutError:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.ABSOLUTE_DEADLINE
        except httpx.ConnectTimeout:
            transport_outcome = "NOT_SENT"
            transport_failure_kind = OXTransportFailureKind.CONNECT_TIMEOUT
        except httpx.ConnectError:
            transport_outcome = "NOT_SENT"
            transport_failure_kind = OXTransportFailureKind.CONNECT_ERROR
        except httpx.PoolTimeout:
            transport_outcome = "NOT_SENT"
            transport_failure_kind = OXTransportFailureKind.POOL_TIMEOUT
        except httpx.ReadTimeout:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.READ_TIMEOUT
        except httpx.ReadError:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.READ_ERROR
        except httpx.WriteTimeout:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.WRITE_TIMEOUT
        except httpx.WriteError:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.WRITE_ERROR
        except httpx.RemoteProtocolError:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.REMOTE_PROTOCOL_ERROR
        except httpx.HTTPError:
            transport_outcome = "OUTCOME_UNKNOWN"
            transport_failure_kind = OXTransportFailureKind.HTTP_TRANSPORT_ERROR
        except (TypeError, ValueError, OverflowError, RecursionError):
            request_error = OXRequestError(attempt_outcome="NOT_SENT")
        if transport_failure_kind is not None:
            request_error = _transport_error(
                attempt_outcome=transport_outcome,
                transport_failure_kind=transport_failure_kind,
                provider_started_at=provider_started_at,
                started_monotonic_ns=started_monotonic_ns,
            )
        if request_error is not None:
            raise request_error

        if isinstance(response, _ReceivedResponse):
            return self._complete_received_response(response)
        return self._complete_legacy_response(response)

    def _complete_received_response(self, response: _ReceivedResponse) -> ProviderResult:
        observation = response.observation
        if response.status_code >= 400:
            raise _provider_http_error(
                response.status_code,
                _safe_error_code_bytes(response.body),
                observation,
            )

        protocol_error = None
        try:
            raw_response = json.loads(response.body)
        except Exception:
            protocol_error = OXProtocolError(
                attempt_outcome="COMPLETED",
                transport_observation=observation,
            )
        if protocol_error is not None:
            raise protocol_error
        if not isinstance(raw_response, dict):
            raise OXProtocolError(
                attempt_outcome="COMPLETED",
                transport_observation=observation,
            )

        parse_error = None
        try:
            safe_response = _redact_secret(raw_response, self._api_key)
            if not isinstance(safe_response, dict):
                raise OXProtocolError(attempt_outcome="COMPLETED")
            parsed = _parse_response(safe_response)
        except OXProtocolError as error:
            parse_error = OXProtocolError(
                attempt_outcome=error.attempt_outcome,
                transport_observation=observation,
            )
        except Exception:
            parse_error = OXProtocolError(
                attempt_outcome="COMPLETED",
                transport_observation=observation,
            )
        if parse_error is not None:
            raise parse_error
        return ProviderResult(
            parsed.content,
            parsed.usage,
            response_id=parsed.response_id,
            model=parsed.model,
            raw_response=parsed.raw_response,
            transport_observation=observation,
        )

    def _complete_legacy_response(self, response: object) -> ProviderResult:
        """Compatibility path for bounded injected response doubles used by tests."""

        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            raise OXProtocolError(attempt_outcome="COMPLETED")
        if status_code >= 400:
            error_code = _safe_error_code_legacy(response)
            raise _provider_http_error(status_code, error_code, None)

        protocol_error = None
        try:
            raw_response = response.json()
        except Exception:
            protocol_error = OXProtocolError(attempt_outcome="COMPLETED")
        if protocol_error is not None:
            raise protocol_error
        if not isinstance(raw_response, dict):
            raise OXProtocolError(attempt_outcome="COMPLETED")

        parse_error = None
        try:
            safe_response = _redact_secret(raw_response, self._api_key)
            if not isinstance(safe_response, dict):
                raise OXProtocolError(attempt_outcome="COMPLETED")
            result = _parse_response(safe_response)
        except OXProtocolError as error:
            parse_error = error
        except Exception:
            parse_error = OXProtocolError(attempt_outcome="COMPLETED")
        if parse_error is not None:
            raise parse_error
        return result


def _transport_error(
    *,
    attempt_outcome: str,
    transport_failure_kind: OXTransportFailureKind,
    provider_started_at: str,
    started_monotonic_ns: int,
) -> OXTransportError:
    finished_monotonic_ns = monotonic_ns()
    return OXTransportError(
        attempt_outcome=attempt_outcome,
        transport_failure_kind=transport_failure_kind,
        provider_started_at=provider_started_at,
        provider_finished_at=datetime.now(UTC).isoformat(),
        elapsed_ms=max(0, (finished_monotonic_ns - started_monotonic_ns) // 1_000_000),
    )


def _provider_http_error(
    status: int,
    error_code: str | None,
    observation: ProviderTransportObservation | None,
):
    kwargs = {
        "attempt_outcome": "REJECTED",
        "transport_observation": observation,
    }
    if status == 401:
        return OXAuthenticationError(**kwargs)
    if status == 403:
        return OXPermissionError(**kwargs)
    if status == 429:
        error_type = OXQuotaError if error_code in _QUOTA_ERROR_CODES else OXRateLimitError
        return error_type(**kwargs)
    if 400 <= status < 500:
        error_type = OXContextLimitError if error_code in _CONTEXT_ERROR_CODES else OXRequestError
        return error_type(**kwargs)
    if status >= 500:
        return OXProviderUnavailableError(**kwargs)
    return OXRequestError(**kwargs)


def _safe_error_code_bytes(response_body: bytes) -> str | None:
    try:
        payload = json.loads(response_body)
    except Exception:
        return None
    return _error_code_from_payload(payload)


def _safe_error_code_legacy(response: object) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    return _error_code_from_payload(payload)


def _error_code_from_payload(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def _proxy_environment_present() -> bool:
    return any(bool(os.environ.get(name)) for name in _PROXY_ENV_KEYS)


def _parse_response(raw_response: dict[str, object]) -> ProviderResult:
    response_id = raw_response.get("id")
    if response_id is not None and not isinstance(response_id, str):
        raise OXProtocolError(attempt_outcome="COMPLETED")
    model = raw_response.get("model")
    if model is not None and not isinstance(model, str):
        raise OXProtocolError(attempt_outcome="COMPLETED")

    choices = raw_response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise OXProtocolError(attempt_outcome="COMPLETED")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise OXProtocolError(attempt_outcome="COMPLETED")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise OXProtocolError(attempt_outcome="COMPLETED")
    if message.get("role") != "assistant":
        raise OXProtocolError(attempt_outcome="COMPLETED")
    content = message.get("content")
    if not isinstance(content, str):
        raise OXProtocolError(attempt_outcome="COMPLETED")

    usage = _parse_usage(raw_response.get("usage"))
    return ProviderResult(
        content,
        usage,
        response_id=response_id,
        model=model,
        raw_response=raw_response,
    )


def _parse_usage(value: object) -> ProviderUsage | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise OXProtocolError(attempt_outcome="COMPLETED")
    prompt_tokens = _token_count(value, "prompt_tokens")
    completion_tokens = _token_count(value, "completion_tokens")
    total_tokens = _token_count(value, "total_tokens")
    details = value.get("prompt_tokens_details")
    if details is None:
        cached_tokens = 0
    elif isinstance(details, Mapping):
        cached_tokens = _token_count(details, "cached_tokens")
    else:
        raise OXProtocolError(attempt_outcome="COMPLETED")
    return ProviderUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_tokens,
    )


def _token_count(value: Mapping[str, object], field: str) -> int:
    count = value.get(field, 0)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise OXProtocolError(attempt_outcome="COMPLETED")
    return count


def _redact_secret(value: object, secret: str) -> object:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {
            _redact_secret(key, secret): _redact_secret(item, secret) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    return value


def _validate_attempt_id(attempt_id: object) -> None:
    if not isinstance(attempt_id, str) or _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None:
        raise OXRequestError(attempt_outcome="NOT_SENT")


def _reporting_tags(attempt_id: str) -> str:
    review_id = attempt_id.rsplit("-A", 1)[0]
    return f"component:byte-mcp-ox,review:{review_id},attempt:{attempt_id}"


def _validate_messages(messages: object) -> list[dict[str, object]]:
    if isinstance(messages, str | bytes | bytearray) or not isinstance(messages, Sequence):
        raise OXRequestError(attempt_outcome="NOT_SENT")
    invalid = False
    try:
        if len(messages) == 0:
            raise ValueError
        validated = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError
            prepared = dict(message)
            role = prepared.get("role")
            content = prepared.get("content")
            if not isinstance(role, str) or role not in _SAFE_MESSAGE_ROLES:
                raise ValueError
            if not isinstance(content, str):
                raise ValueError
            safe_message = _json_safe_copy(prepared)
            if not isinstance(safe_message, dict):
                raise ValueError
            validated.append(safe_message)
        _validate_json(validated)
    except Exception:
        invalid = True
    if invalid:
        raise OXRequestError(attempt_outcome="NOT_SENT")
    return validated


def _validate_json(value: object) -> None:
    try:
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        invalid = True
    else:
        return
    if invalid:
        raise OXRequestError(attempt_outcome="NOT_SENT")


def _json_safe_copy(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError
        return value
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError
            copied[key] = _json_safe_copy(item)
        return copied
    if isinstance(value, list | tuple):
        return [_json_safe_copy(item) for item in value]
    raise TypeError
