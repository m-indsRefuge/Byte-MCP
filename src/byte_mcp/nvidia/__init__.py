"""NVIDIA API Catalog integration primitives."""

from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaHostedSettings",
]
