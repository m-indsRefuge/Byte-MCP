"""Narrow loopback client for B87 Chess Arena."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import ByteMCPError


class ArenaClient:
    def __init__(self, base_url: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> Any:
        return self._request("GET", path, None)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> Any:
        if not path.startswith("/"):
            raise ByteMCPError("Arena client path must begin with '/'.")

        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = self._http_error_detail(exc)
            raise ByteMCPError(
                f"Arena returned HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ByteMCPError(f"Arena connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ByteMCPError("Arena request timed out.") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ByteMCPError("Arena returned invalid JSON.") from exc

    @staticmethod
    def _http_error_detail(exc: HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8")
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return exc.reason or "request failed"

        detail = payload.get("detail") if isinstance(payload, dict) else None
        return detail if isinstance(detail, str) else exc.reason or "request failed"
