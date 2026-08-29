"""Fixed, single-attempt HTTP client for the OX validation provider."""

import json
import math
import re
from collections.abc import Mapping, Sequence

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
)

from .models import ProviderResult, ProviderUsage
from .settings import OXSettings

_GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
_MODEL = "zai/glm-5.3-flash"
_PROVIDER_OPTIONS = {"gateway": {"only": ["zai"]}}
_MAX_TOKENS = 16_384
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
_ATTEMPT_ID_PATTERN = re.compile(r"^OX-\d{6}-A\d{3}$")
_SAFE_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})

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


class OXClient:
    """Make one fixed, non-streaming OX provider request at a time."""

    def __init__(
        self, settings: OXSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._api_key = settings.api_key
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
            "max_tokens": _MAX_TOKENS,
            "providerOptions": _PROVIDER_OPTIONS,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        _validate_json(body)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        request_error = None
        try:
            with httpx.Client(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = client.post(_GATEWAY_URL, headers=headers, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            request_error = OXTransportError(attempt_outcome="NOT_SENT")
        except (
            httpx.WriteTimeout,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ):
            request_error = OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        except httpx.HTTPError:
            request_error = OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")
        except (TypeError, ValueError, OverflowError, RecursionError):
            request_error = OXRequestError(attempt_outcome="NOT_SENT")
        if request_error is not None:
            raise request_error

        if response.status_code >= 400:
            self._raise_http_error(response)

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
            result = _parse_response(safe_response)
        except OXProtocolError as error:
            parse_error = error
        except Exception:
            parse_error = OXProtocolError(attempt_outcome="COMPLETED")
        if parse_error is not None:
            raise parse_error
        return result

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise OXAuthenticationError(attempt_outcome="REJECTED")
        if status == 403:
            raise OXPermissionError(attempt_outcome="REJECTED")
        if status == 429:
            error_type = (
                OXQuotaError
                if _safe_error_code(response) in _QUOTA_ERROR_CODES
                else OXRateLimitError
            )
            raise error_type(attempt_outcome="REJECTED")
        if 400 <= status < 500:
            error_type = (
                OXContextLimitError
                if _safe_error_code(response) in _CONTEXT_ERROR_CODES
                else OXRequestError
            )
            raise error_type(attempt_outcome="REJECTED")
        if status >= 500:
            raise OXProviderUnavailableError(attempt_outcome="REJECTED")
        raise OXRequestError(attempt_outcome="REJECTED")


def _safe_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


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
    return ProviderUsage(input_tokens=prompt_tokens, output_tokens=completion_tokens)


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
