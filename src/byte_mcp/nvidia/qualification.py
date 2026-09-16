"""Provider-free NVIDIA readiness and offline qualification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from byte_mcp.nvidia.chat import NVIDIA_CHAT_ENDPOINT_PATH, NVIDIA_CHAT_TARGET_ORIGIN
from byte_mcp.nvidia.models import (
    NVIDIA_DEFAULT_QUERY_MODEL,
    NVIDIA_MODELS,
    NvidiaQualificationState,
    validate_model_registry,
)
from byte_mcp.nvidia.query_protocol import prepare_nvidia_query_request
from byte_mcp.nvidia.query_service import MAX_QUERY_RESPONSE_CHARS

EXPECTED_NVIDIA_MCP_SURFACE = (
    "nvidia_get_review",
    "nvidia_query",
    "nvidia_review",
)


@dataclass(frozen=True, slots=True)
class NvidiaReadinessReport:
    endpoint: str
    default_query_alias: str
    enabled_query_aliases: tuple[str, ...]
    enabled_review_aliases: tuple[str, ...]
    credential_status: str
    request_builder_status: str
    response_bounds_status: str
    review_evidence_status: str
    expected_mcp_surface_names: tuple[str, ...]
    query_qualification: Mapping[str, str]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["query_qualification"] = dict(self.query_qualification)
        return payload


def _request_builder_status() -> str:
    first = prepare_nvidia_query_request(
        "offline-readiness-probe",
        model=NVIDIA_DEFAULT_QUERY_MODEL,
    )
    second = prepare_nvidia_query_request(
        "offline-readiness-probe",
        model=NVIDIA_DEFAULT_QUERY_MODEL,
    )
    if (
        first.request.body_bytes != second.request.body_bytes
        or first.request.request_sha256 != second.request.request_sha256
        or first.request.payload_sha256 != second.request.payload_sha256
    ):
        return "FAILED"
    return "READY"


def inspect_nvidia_readiness() -> NvidiaReadinessReport:
    """Inspect local readiness without loading credentials or networking."""
    validate_model_registry(NVIDIA_MODELS)

    query_aliases = tuple(
        sorted(alias for alias, model in NVIDIA_MODELS.items() if model.query_enabled)
    )
    review_aliases = tuple(
        sorted(alias for alias, model in NVIDIA_MODELS.items() if model.review_enabled)
    )
    qualifications = {
        alias: model.query_qualification.value
        for alias, model in sorted(NVIDIA_MODELS.items())
        if model.query_enabled
    }

    return NvidiaReadinessReport(
        endpoint=f"{NVIDIA_CHAT_TARGET_ORIGIN}{NVIDIA_CHAT_ENDPOINT_PATH}",
        default_query_alias=NVIDIA_DEFAULT_QUERY_MODEL,
        enabled_query_aliases=query_aliases,
        enabled_review_aliases=review_aliases,
        credential_status="DEFERRED_TO_TRANSMIT",
        request_builder_status=_request_builder_status(),
        response_bounds_status="READY" if MAX_QUERY_RESPONSE_CHARS > 0 else "FAILED",
        review_evidence_status="READY",
        expected_mcp_surface_names=EXPECTED_NVIDIA_MCP_SURFACE,
        query_qualification=qualifications,
    )


def qualify_nvidia_offline() -> dict[str, object]:
    """Deterministically qualify governed query construction with zero provider calls."""
    validate_model_registry(NVIDIA_MODELS)
    checks: dict[str, str] = {}

    for alias, model in sorted(NVIDIA_MODELS.items()):
        if not model.query_enabled:
            continue
        if model.query_profile is None:
            raise ValueError("enabled query model is missing profile")
        if model.query_qualification is not NvidiaQualificationState.OFFLINE_QUALIFIED:
            raise ValueError("query model is not marked offline qualified")

        first = prepare_nvidia_query_request("offline-qualification-probe", model=alias)
        second = prepare_nvidia_query_request("offline-qualification-probe", model=alias)
        if first.request.body_bytes != second.request.body_bytes:
            raise ValueError("query request construction is nondeterministic")
        if first.request.request_sha256 != second.request.request_sha256:
            raise ValueError("query request identity is nondeterministic")
        if first.provider_model_id != model.provider_model_id:
            raise ValueError("query provider identity mismatch")
        checks[alias] = "PASS"

    return {
        "status": "PASS",
        "provider_calls": 0,
        "default_query_alias": NVIDIA_DEFAULT_QUERY_MODEL,
        "models": checks,
    }
