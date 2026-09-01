"""Fixed-purpose Wolfram|Alpha LLM API client."""

from __future__ import annotations

import re

import httpx

from byte_mcp.errors import (
    WolframAuthenticationError,
    WolframProtocolError,
    WolframProviderError,
    WolframRateLimitError,
    WolframRequestError,
    WolframTimeoutError,
    WolframTransportError,
    WolframUnavailableError,
    WolframUninterpretableError,
)
from byte_mcp.wolfram.domain import WolframClientResult
from byte_mcp.wolfram.settings import WolframSettings

_RESULT_URL_RE = re.compile(r"https://www\.wolframalpha\.com/input\?\S+$", re.MULTILINE)


class WolframLLMClient:
    def __init__(
        self,
        settings: WolframSettings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def __repr__(self) -> str:
        return (
            "WolframLLMClient("
            f"endpoint={self._settings.endpoint!r}, "
            f"configured={self._settings.app_id is not None})"
        )

    @staticmethod
    def _safe_error_body(response: httpx.Response) -> str:
        body = response.text.strip().replace("\r", " ").replace("\n", " ")
        return body[:240]

    def query(
        self,
        input_text: str,
        max_chars: int,
        assumption: tuple[str, ...] = (),
    ) -> WolframClientResult:
        if self._settings.app_id is None:
            raise WolframUnavailableError("Wolfram AppID is not configured.")

        timeout = httpx.Timeout(
            connect=self._settings.connect_timeout_seconds,
            read=self._settings.read_timeout_seconds,
            write=10.0,
            pool=10.0,
        )
        headers = {
            "Authorization": f"Bearer {self._settings.app_id}",
            "Accept": "text/plain",
            "User-Agent": "Byte-MCP-Wolfram/1",
        }
        params: list[tuple[str, str]] = [
            ("input", input_text),
            ("maxchars", str(max_chars)),
        ]
        params.extend(("assumption", token) for token in assumption)

        try:
            with httpx.Client(
                timeout=timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    self._settings.endpoint,
                    params=params,
                    headers=headers,
                )
        except httpx.ReadTimeout as exc:
            raise WolframTimeoutError("Wolfram request timed out.") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise WolframTransportError("Wolfram transport connection failed.") from exc
        except httpx.HTTPError as exc:
            raise WolframTransportError("Wolfram transport failed.") from exc

        if response.status_code in {401, 403}:
            raise WolframAuthenticationError("Wolfram authentication was rejected.")
        if response.status_code == 429:
            raise WolframRateLimitError("Wolfram rate limit was reached.")
        if response.status_code == 501:
            body = self._safe_error_body(response)
            detail = f" Suggested input: {body}" if body else ""
            raise WolframUninterpretableError(f"Wolfram could not interpret the input.{detail}")
        if 400 <= response.status_code < 500:
            raise WolframRequestError(
                f"Wolfram rejected the request with HTTP {response.status_code}."
            )
        if response.status_code >= 500:
            raise WolframProviderError(f"Wolfram provider failed with HTTP {response.status_code}.")
        if response.status_code != 200:
            raise WolframProtocolError(f"Unexpected Wolfram HTTP status {response.status_code}.")

        result = response.text.strip()
        if not result:
            raise WolframProtocolError("Wolfram returned an empty response.")
        matches = _RESULT_URL_RE.findall(result)
        result_url = matches[-1] if matches else None
        return WolframClientResult(
            result=result,
            result_url=result_url,
            response_chars=len(result),
            response_at_limit=len(result) >= max_chars,
        )
