"""One-shot OX provider transport and free-form response extraction."""

from __future__ import annotations

import json

import httpx

from byte_mcp.errors import OXProtocolError
from byte_mcp.ox.settings import OX_TIMEOUT_POLICY
from byte_mcp.providers import (
    PreparedProviderRequest,
    ProviderAuthorization,
    ProviderTransmissionContext,
    ProviderTransportResponse,
    execute_once,
)


async def execute_ox_transport(
    prepared_request: PreparedProviderRequest,
    transmission_context: ProviderTransmissionContext,
    *,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderTransportResponse:
    """Execute exactly one OX provider transport using frozen request bytes."""
    return await execute_once(
        prepared_request,
        transmission_context,
        ProviderAuthorization(f"Bearer {api_key}"),
        OX_TIMEOUT_POLICY,
        transport=transport,
    )


def extract_ox_review_text(response_body: bytes) -> str:
    """Extract one free-form assistant review from already-persisted response bytes."""
    try:
        payload = json.loads(response_body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OXProtocolError(attempt_outcome="COMPLETED") from None

    if not isinstance(payload, dict):
        raise OXProtocolError(attempt_outcome="COMPLETED")

    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise OXProtocolError(attempt_outcome="COMPLETED")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise OXProtocolError(attempt_outcome="COMPLETED")

    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise OXProtocolError(attempt_outcome="COMPLETED")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OXProtocolError(attempt_outcome="COMPLETED")

    return content
