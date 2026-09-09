"""NVIDIA API Catalog integration primitives."""

from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .chat import (
    NVIDIA_CHAT_ENDPOINT_PATH,
    NVIDIA_CHAT_TARGET_ORIGIN,
    NvidiaChatMessage,
    prepare_nvidia_chat_request,
)
from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind
from .registry import (
    NVIDIA_PROVIDER,
    NvidiaQualificationCandidate,
    initial_model_registry,
    initial_qualification_candidates,
)
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_CHAT_ENDPOINT_PATH",
    "NVIDIA_CHAT_TARGET_ORIGIN",
    "NVIDIA_HOSTED_BASE_URL",
    "NVIDIA_PROVIDER",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaChatMessage",
    "NvidiaHostedSettings",
    "NvidiaQualificationCandidate",
    "initial_model_registry",
    "initial_qualification_candidates",
    "parse_catalog_payload",
    "prepare_nvidia_chat_request",
]
