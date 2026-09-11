"""Bounded NVIDIA provider error classification."""

from __future__ import annotations

import re
from enum import StrEnum

from byte_mcp.errors import ByteMCPError
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransportObservation,
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class NvidiaCatalogFailureKind(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    REQUEST = "REQUEST"
    RATE_LIMIT = "RATE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"
    TRANSPORT = "TRANSPORT"
    PROTOCOL = "PROTOCOL"


class NvidiaCatalogError(ByteMCPError):
    def __init__(self, kind: NvidiaCatalogFailureKind) -> None:
        if not isinstance(kind, NvidiaCatalogFailureKind):
            raise ValueError("kind is invalid")
        self.kind = kind
        super().__init__(kind.value)


class NvidiaChatFailureKind(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    REQUEST = "REQUEST"
    MODEL_OR_ENDPOINT_UNAVAILABLE = "MODEL_OR_ENDPOINT_UNAVAILABLE"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    REDIRECT_REJECTED = "REDIRECT_REJECTED"
    PROTOCOL = "PROTOCOL"


class NvidiaChatError(ByteMCPError):
    def __init__(
        self,
        *,
        kind: NvidiaChatFailureKind,
        attempt_outcome: ProviderAttemptOutcome,
        transport_observation: ProviderTransportObservation,
        request_sha256: str,
    ) -> None:
        if not isinstance(kind, NvidiaChatFailureKind):
            raise ValueError("kind is invalid")
        if not isinstance(attempt_outcome, ProviderAttemptOutcome):
            raise ValueError("attempt_outcome is invalid")
        if not isinstance(transport_observation, ProviderTransportObservation):
            raise ValueError("transport_observation is invalid")
        if not isinstance(request_sha256, str) or not _SHA256_PATTERN.fullmatch(request_sha256):
            raise ValueError("request_sha256 is invalid")
        self.kind = kind
        self.attempt_outcome = attempt_outcome
        self.transport_observation = transport_observation
        self.request_sha256 = request_sha256
        super().__init__(f"nvidia chat failed: {attempt_outcome.value}/{kind.value}")
