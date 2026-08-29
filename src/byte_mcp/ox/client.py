"""Fixed, single-attempt HTTP client for the OX validation provider."""

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
        del attempt_id
        if not self._api_key:
            raise OXConfigurationError("AI gateway API key is not configured")

        body: dict[str, object] = {
            "messages": list(messages),
            "model": _MODEL,
            "stream": False,
            "max_tokens": _MAX_TOKENS,
            "providerOptions": _PROVIDER_OPTIONS,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = client.post(_GATEWAY_URL, headers=headers, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise OXTransportError(attempt_outcome="NOT_SENT") from error
        except (
            httpx.WriteTimeout,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ) as error:
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN") from error
        except httpx.HTTPError as error:
            raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN") from error

        if response.status_code >= 400:
            self._raise_http_error(response)

        try:
            raw_response = response.json()
        except (UnicodeError, ValueError) as error:
            raise OXProtocolError(attempt_outcome="COMPLETED") from error
        if not isinstance(raw_response, dict):
            raise OXProtocolError(attempt_outcome="COMPLETED")

        safe_response = _redact_secret(raw_response, self._api_key)
        return _parse_response(safe_response)

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
    except (UnicodeError, ValueError):
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
