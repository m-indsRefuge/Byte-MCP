"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .registry import (
    NVIDIA_PROVIDER,
    NvidiaQualificationCandidate,
    initial_model_registry,
    initial_qualification_candidates,
)
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_HOSTED_BASE_URL",
    "NVIDIA_PROVIDER",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaHostedSettings",
    "NvidiaQualificationCandidate",
    "initial_model_registry",
    "initial_qualification_candidates",
    "parse_catalog_payload",
]
