"""Canonical provider-neutral request preparation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .models import _require_slug, validate_model_id

MAX_PREPARED_BODY_BYTES = 4_000_000
REQUEST_SCHEMA = "byte-mcp-provider-request-v1"


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("body must be valid JSON") from exc


def _validate_origin(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("target_origin is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
    ):
        raise ValueError("target_origin is invalid")
    return value


def _validate_endpoint(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or any(character in value for character in ("?", "#", "\r", "\n", " "))
    ):
        raise ValueError("endpoint_path is invalid")
    return value


def _request_sha256(
    *,
    provider_id: str,
    method: str,
    target_origin: str,
    endpoint_path: str,
    model_id: str,
    payload_sha256: str,
) -> str:
    envelope = {
        "endpoint_path": endpoint_path,
        "method": method,
        "model_id": model_id,
        "payload_sha256": payload_sha256,
        "provider_id": provider_id,
        "request_schema": REQUEST_SCHEMA,
        "target_origin": target_origin,
    }
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedProviderRequest:
    provider_id: str
    method: str
    target_origin: str
    endpoint_path: str
    model_id: str
    body_bytes: bytes = field(repr=False)
    payload_sha256: str
    request_sha256: str


def validate_prepared_provider_request_integrity(
    prepared_request: PreparedProviderRequest,
) -> None:
    """Fail closed if prepared fields no longer match their frozen request identity."""

    if not isinstance(prepared_request, PreparedProviderRequest):
        raise ValueError("prepared request integrity is invalid")
    try:
        _require_slug(prepared_request.provider_id, "provider_id")
        if prepared_request.method != "POST":
            raise ValueError("method must be POST")
        origin = _validate_origin(prepared_request.target_origin)
        endpoint = _validate_endpoint(prepared_request.endpoint_path)
        validate_model_id(prepared_request.model_id)
        if not isinstance(prepared_request.body_bytes, bytes):
            raise ValueError("body_bytes is invalid")
        if len(prepared_request.body_bytes) > MAX_PREPARED_BODY_BYTES:
            raise ValueError("body exceeds maximum prepared size")

        payload_sha256 = hashlib.sha256(prepared_request.body_bytes).hexdigest()
        if payload_sha256 != prepared_request.payload_sha256:
            raise ValueError("payload_sha256 does not match body_bytes")
        request_sha256 = _request_sha256(
            provider_id=prepared_request.provider_id,
            method=prepared_request.method,
            target_origin=origin,
            endpoint_path=endpoint,
            model_id=prepared_request.model_id,
            payload_sha256=payload_sha256,
        )
        if request_sha256 != prepared_request.request_sha256:
            raise ValueError("request_sha256 does not match prepared fields")
    except (TypeError, ValueError):
        raise ValueError("prepared request integrity is invalid") from None


def prepare_provider_request(
    *,
    provider_id: str,
    method: str,
    target_origin: str,
    endpoint_path: str,
    model_id: str,
    body: object,
) -> PreparedProviderRequest:
    _require_slug(provider_id, "provider_id")
    if method != "POST":
        raise ValueError("method must be POST")
    origin = _validate_origin(target_origin)
    endpoint = _validate_endpoint(endpoint_path)
    validate_model_id(model_id)
    body_bytes = _canonical_json(body)
    if len(body_bytes) > MAX_PREPARED_BODY_BYTES:
        raise ValueError("body exceeds maximum prepared size")
    payload_sha256 = hashlib.sha256(body_bytes).hexdigest()
    request_sha256 = _request_sha256(
        provider_id=provider_id,
        method=method,
        target_origin=origin,
        endpoint_path=endpoint,
        model_id=model_id,
        payload_sha256=payload_sha256,
    )
    return PreparedProviderRequest(
        provider_id=provider_id,
        method=method,
        target_origin=origin,
        endpoint_path=endpoint,
        model_id=model_id,
        body_bytes=body_bytes,
        payload_sha256=payload_sha256,
        request_sha256=request_sha256,
    )
