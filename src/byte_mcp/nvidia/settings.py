"""Hosted NVIDIA API Catalog settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

NVIDIA_HOSTED_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaHostedSettings:
    api_key: str | None
    base_url: str = NVIDIA_HOSTED_BASE_URL
    catalog_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if self.api_key is not None and (
            not isinstance(self.api_key, str)
            or not self.api_key
            or self.api_key != self.api_key.strip()
        ):
            raise ValueError("api_key is invalid")
        if self.base_url != NVIDIA_HOSTED_BASE_URL:
            raise ValueError("NVIDIA hosted base_url is invalid")
        if not isinstance(self.catalog_timeout_seconds, int) or isinstance(
            self.catalog_timeout_seconds, bool
        ):
            raise ValueError("catalog_timeout_seconds is invalid")
        if not 1 <= self.catalog_timeout_seconds <= 60:
            raise ValueError("catalog_timeout_seconds must be between 1 and 60")

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
        )
