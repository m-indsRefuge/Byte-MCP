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


class NvidiaErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    MODEL_NOT_ENABLED = "MODEL_NOT_ENABLED"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"
    RESPONSE_INVALID = "RESPONSE_INVALID"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"


class NvidiaPlatformError(ByteMCPError):
    def __init__(
        self,
        *,
        code: NvidiaErrorCode,
        message: str,
        provider_started: bool,
        safe_to_invoke_fresh: bool,
        status_code: int | None = None,
    ) -> None:
        if not isinstance(code, NvidiaErrorCode):
            raise ValueError("code is invalid")
        if not isinstance(message, str) or not message or len(message) > 512:
            raise ValueError("message is invalid")
        if not isinstance(provider_started, bool):
            raise ValueError("provider_started is invalid")
        if not isinstance(safe_to_invoke_fresh, bool):
            raise ValueError("safe_to_invoke_fresh is invalid")
        if status_code is not None and (
            not isinstance(status_code, int) or isinstance(status_code, bool)
        ):
            raise ValueError("status_code is invalid")

        self.code = code
        self.provider_started = provider_started
        self.safe_to_invoke_fresh = safe_to_invoke_fresh
        self.status_code = status_code
        self.automatic_retry = False
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": str(self),
            "provider_started": self.provider_started,
            "safe_to_invoke_fresh": self.safe_to_invoke_fresh,
            "status_code": self.status_code,
            "automatic_retry": self.automatic_retry,
        }


def classify_nvidia_http_status(status_code: int) -> NvidiaErrorCode:
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise ValueError("status_code is invalid")
    if status_code in {401, 403}:
        return NvidiaErrorCode.AUTHENTICATION_FAILED
    if status_code == 429:
        return NvidiaErrorCode.RATE_LIMITED
    if 400 <= status_code <= 599:
        return NvidiaErrorCode.PROVIDER_REJECTED
    raise ValueError("status_code is not a provider error")


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
