"""Fixed-purpose Wolfram|Alpha LLM API transport."""
from __future__ import annotations

import re

import httpx

from byte_mcp.errors import (
    WolframAuthenticationError,
    WolframProviderError,
    WolframProtocolError,
    WolframRateLimitError,
    WolframRequestError,
    WolframTimeoutError,
    WolframTransportError,
    WolframUnavailableError,
    WolframUninterpretableError,
)
from byte_mcp.wolfram.domain import WolframClientResult
from byte_mcp.wolfram.settings import WolframSettings

_RESULT_URL_RE = re.compile(r"^https://www\.wolframalpha\.com/input\?\S+$")


class WolframLLMClient:
    def __init__(
        self,
        settings: WolframSettings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def _safe_excerpt(self, text: str) -> str:
        excerpt = text.strip()[:500]
        if self.settings.app_id:
            excerpt = excerpt.replace(self.settings.app_id, "[redacted]")
        return excerpt

    def query(self, input_text: str, max_chars: int) -> WolframClientResult:
        if not self.settings.app_id:
            raise WolframUnavailableError("Wolfram AppID is not configured.")

        timeout = httpx.Timeout(
            connect=self.settings.connect_timeout_seconds,
            read=self.settings.read_timeout_seconds,
            write=10.0,
            pool=10.0,
        )
        headers = {"Authorization": f"Bearer {self.settings.app_id}"}
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
                headers=headers,
            ) as client:
                response = client.get(
                    self.settings.endpoint,
                    params={"input": input_text, "maxchars": str(max_chars)},
                )
        except httpx.ReadTimeout as exc:
            raise WolframTimeoutError("Wolfram provider timed out while reading the response.") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise WolframTransportError("Wolfram provider connection failed.") from exc
        except httpx.TransportError as exc:
            raise WolframTransportError("Wolfram provider transport failed.") from exc

        status = response.status_code
        if status == 403:
            raise WolframAuthenticationError("Wolfram rejected the configured AppID.")
        if status == 429:
            raise WolframRateLimitError("Wolfram rate limit was reached.")
        if status == 501:
            excerpt = self._safe_excerpt(response.text)
            message = "Wolfram could not interpret the input."
            if excerpt:
                message += f" Suggested provider detail: {excerpt}"
            raise WolframUninterpretableError(message)
        if 400 <= status < 500:
            raise WolframRequestError(f"Wolfram rejected the request with HTTP {status}.")
        if status >= 500:
            raise WolframProviderError(f"Wolfram provider failed with HTTP {status}.")
        if status != 200:
            raise WolframProtocolError(f"Unexpected Wolfram HTTP status: {status}.")

        text = response.text
        if not text.strip():
            raise WolframProtocolError("Wolfram returned an empty response.")

        result_url = None
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if _RESULT_URL_RE.fullmatch(candidate):
                result_url = candidate
                break

        return WolframClientResult(
            text=text,
            result_url=result_url,
            response_chars=len(text),
            response_at_limit=len(text) >= max_chars,
        )
