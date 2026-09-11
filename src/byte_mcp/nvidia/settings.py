"""Hosted NVIDIA API Catalog settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from byte_mcp.providers import ProviderTimeoutPolicy

NVIDIA_HOSTED_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_CHAT_TIMEOUT_POLICY = ProviderTimeoutPolicy(
    connect_seconds=10.0,
    write_seconds=30.0,
    read_seconds=300.0,
    pool_seconds=10.0,
    absolute_deadline_seconds=300.0,
)


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _validate_bounded_int(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaHostedSettings:
    api_key: str | None
    base_url: str = NVIDIA_HOSTED_BASE_URL
    catalog_timeout_seconds: int = 10
    chat_connect_timeout_seconds: int = 10
    chat_write_timeout_seconds: int = 30
    chat_read_timeout_seconds: int = 300
    chat_pool_timeout_seconds: int = 10
    chat_absolute_deadline_seconds: int = 300
    chat_timeout_policy: ProviderTimeoutPolicy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is not None and (
            not isinstance(self.api_key, str)
            or not self.api_key
            or self.api_key != self.api_key.strip()
        ):
            raise ValueError("api_key is invalid")
        if self.base_url != NVIDIA_HOSTED_BASE_URL:
            raise ValueError("NVIDIA hosted base_url is invalid")
        _validate_bounded_int(
            self.catalog_timeout_seconds,
            "catalog_timeout_seconds",
            1,
            60,
        )
        connect_seconds = _validate_bounded_int(
            self.chat_connect_timeout_seconds,
            "chat_connect_timeout_seconds",
            1,
            60,
        )
        write_seconds = _validate_bounded_int(
            self.chat_write_timeout_seconds,
            "chat_write_timeout_seconds",
            1,
            120,
        )
        read_seconds = _validate_bounded_int(
            self.chat_read_timeout_seconds,
            "chat_read_timeout_seconds",
            1,
            600,
        )
        pool_seconds = _validate_bounded_int(
            self.chat_pool_timeout_seconds,
            "chat_pool_timeout_seconds",
            1,
            60,
        )
        absolute_deadline_seconds = _validate_bounded_int(
            self.chat_absolute_deadline_seconds,
            "chat_absolute_deadline_seconds",
            1,
            600,
        )
        object.__setattr__(
            self,
            "chat_timeout_policy",
            ProviderTimeoutPolicy(
                connect_seconds=float(connect_seconds),
                write_seconds=float(write_seconds),
                read_seconds=float(read_seconds),
                pool_seconds=float(pool_seconds),
                absolute_deadline_seconds=float(absolute_deadline_seconds),
            ),
        )

    def __repr__(self) -> str:
        return f"NvidiaHostedSettings(api_key_configured={self.api_key is not None})"

    @classmethod
    def load(cls) -> NvidiaHostedSettings:
        key = os.getenv("NVIDIA_API_KEY", "").strip() or None
        return cls(
            api_key=key,
            catalog_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CATALOG_TIMEOUT_SECONDS", 10, 1, 60
            ),
            chat_connect_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CHAT_CONNECT_TIMEOUT_SECONDS", 10, 1, 60
            ),
            chat_write_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CHAT_WRITE_TIMEOUT_SECONDS", 30, 1, 120
            ),
            chat_read_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CHAT_READ_TIMEOUT_SECONDS", 300, 1, 600
            ),
            chat_pool_timeout_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CHAT_POOL_TIMEOUT_SECONDS", 10, 1, 60
            ),
            chat_absolute_deadline_seconds=_bounded_int(
                "BYTE_MCP_NVIDIA_CHAT_ABSOLUTE_DEADLINE_SECONDS", 300, 1, 600
            ),
        )
