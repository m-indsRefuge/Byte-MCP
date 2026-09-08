"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaHostedSettings",
    "parse_catalog_payload",
]
