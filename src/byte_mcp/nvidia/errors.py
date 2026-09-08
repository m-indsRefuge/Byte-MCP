"""Bounded NVIDIA catalog error classification."""

from enum import StrEnum

from byte_mcp.errors import ByteMCPError


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
