"""NVIDIA API Catalog integration primitives."""

from .canary import (
    NVIDIA_01_QUALIFIED_SHA,
    NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT,
    NVIDIA_LIGHTNING_CANARY_MODEL_ID,
    NVIDIA_LIGHTNING_CANARY_PROMPT,
    NvidiaCanaryInspection,
    NvidiaCanaryPrepareReceipt,
    inspect_lightning_canary,
    prepare_lightning_canary,
)
from .catalog import NvidiaCatalogClient, NvidiaCatalogSnapshot, parse_catalog_payload
from .chat import (
    NVIDIA_CHAT_ENDPOINT_PATH,
    NVIDIA_CHAT_TARGET_ORIGIN,
    NvidiaChatMessage,
    NvidiaChatResult,
    NvidiaChatUsage,
    classify_nvidia_chat_rejection,
    execute_prepared_nvidia_chat,
    parse_nvidia_chat_response,
    prepare_nvidia_chat_request,
)
from .errors import (
    NvidiaCatalogError,
    NvidiaCatalogFailureKind,
    NvidiaChatError,
    NvidiaChatFailureKind,
)
from .registry import (
    NVIDIA_PROVIDER,
    NvidiaQualificationCandidate,
    initial_model_registry,
    initial_qualification_candidates,
)
from .settings import NVIDIA_HOSTED_BASE_URL, NvidiaHostedSettings

__all__ = [
    "NVIDIA_01_QUALIFIED_SHA",
    "NVIDIA_CHAT_ENDPOINT_PATH",
    "NVIDIA_CHAT_TARGET_ORIGIN",
    "NVIDIA_HOSTED_BASE_URL",
    "NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT",
    "NVIDIA_LIGHTNING_CANARY_MODEL_ID",
    "NVIDIA_LIGHTNING_CANARY_PROMPT",
    "NVIDIA_PROVIDER",
    "NvidiaCanaryInspection",
    "NvidiaCanaryPrepareReceipt",
    "NvidiaCatalogClient",
    "NvidiaCatalogError",
    "NvidiaCatalogFailureKind",
    "NvidiaCatalogSnapshot",
    "NvidiaChatError",
    "NvidiaChatFailureKind",
    "NvidiaChatMessage",
    "NvidiaChatResult",
    "NvidiaChatUsage",
    "NvidiaHostedSettings",
    "NvidiaQualificationCandidate",
    "classify_nvidia_chat_rejection",
    "execute_prepared_nvidia_chat",
    "initial_model_registry",
    "initial_qualification_candidates",
    "inspect_lightning_canary",
    "parse_catalog_payload",
    "parse_nvidia_chat_response",
    "prepare_lightning_canary",
    "prepare_nvidia_chat_request",
]
