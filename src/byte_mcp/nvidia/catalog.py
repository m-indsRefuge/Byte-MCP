"""Bounded NVIDIA hosted model-catalog parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from byte_mcp.providers.models import validate_model_id

from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NvidiaHostedSettings

_MAX_CATALOG_BYTES = 1_000_000
_MAX_CATALOG_MODELS = 1_000


@dataclass(frozen=True, slots=True)
class NvidiaCatalogSnapshot:
    model_ids: tuple[str, ...]
    observed_at: str


def _protocol_error() -> NvidiaCatalogError:
    return NvidiaCatalogError(NvidiaCatalogFailureKind.PROTOCOL)


def parse_catalog_payload(
    payload: object,
    *,
    observed_at: str,
) -> NvidiaCatalogSnapshot:
    if not isinstance(payload, Mapping):
        raise _protocol_error()
    data = payload.get("data")
    if not isinstance(data, list) or len(data) > _MAX_CATALOG_MODELS:
        raise _protocol_error()

    model_ids: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            raise _protocol_error()
        try:
            model_id = validate_model_id(item.get("id"))
        except ValueError:
            raise _protocol_error() from None
        model_ids.add(model_id)

    try:
        parsed_time = datetime.fromisoformat(observed_at)
    except (TypeError, ValueError):
        raise _protocol_error() from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise _protocol_error()

    return NvidiaCatalogSnapshot(
        model_ids=tuple(sorted(model_ids)),
        observed_at=observed_at,
    )


def _http_failure(status_code: int) -> NvidiaCatalogError:
    if status_code == 401:
        kind = NvidiaCatalogFailureKind.AUTHENTICATION
    elif status_code == 403:
        kind = NvidiaCatalogFailureKind.PERMISSION
    elif status_code == 404:
        kind = NvidiaCatalogFailureKind.UNAVAILABLE
    elif status_code == 429:
        kind = NvidiaCatalogFailureKind.RATE_LIMIT
    elif status_code >= 500:
        kind = NvidiaCatalogFailureKind.UNAVAILABLE
    else:
        kind = NvidiaCatalogFailureKind.REQUEST
    return NvidiaCatalogError(kind)


class NvidiaCatalogClient:
    """Perform one bounded hosted catalog GET with no retry or inference behavior."""

    def __init__(
        self,
        settings: NvidiaHostedSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(settings, NvidiaHostedSettings):
            raise ValueError("settings is invalid")
        self._settings = settings
        self._transport = transport

    def __repr__(self) -> str:
        return f"NvidiaCatalogClient(api_key_configured={self._settings.api_key is not None})"

    def discover(self) -> NvidiaCatalogSnapshot:
        if self._settings.api_key is None:
            raise NvidiaCatalogError(NvidiaCatalogFailureKind.CONFIGURATION)

        url = f"{self._settings.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(float(self._settings.catalog_timeout_seconds))

        transport_failed = False
        try:
            with (
                httpx.Client(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,
                ) as client,
                client.stream("GET", url, headers=headers) as response,
            ):
                if response.status_code >= 300:
                    raise _http_failure(response.status_code)
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > _MAX_CATALOG_BYTES:
                        raise _protocol_error()
                    body.extend(chunk)
        except NvidiaCatalogError:
            raise
        except (
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.PoolTimeout,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteTimeout,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.HTTPError,
        ):
            transport_failed = True
        if transport_failed:
            raise NvidiaCatalogError(NvidiaCatalogFailureKind.TRANSPORT)

        invalid_json = False
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            invalid_json = True
        if invalid_json:
            raise _protocol_error()

        return parse_catalog_payload(
            payload,
            observed_at=datetime.now(UTC).isoformat(),
        )
