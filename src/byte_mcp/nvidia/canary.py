"""Governed preparation, inspection, and transmission for the NVIDIA Lightning canary."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from byte_mcp.providers import (
    PreparedProviderRequest,
    ProviderAttemptOutcome,
    ProviderTransmissionContext,
)
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity

from .canary_evidence import NvidiaCanaryEvidenceStore
from .chat import (
    NVIDIA_CHAT_ENDPOINT_PATH,
    NVIDIA_CHAT_TARGET_ORIGIN,
    NvidiaChatResult,
    execute_prepared_nvidia_chat,
    prepare_nvidia_chat_request,
)
from .registry import NVIDIA_PROVIDER
from .settings import NvidiaHostedSettings

NVIDIA_LIGHTNING_CANARY_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_LIGHTNING_CANARY_PROMPT = "Reply with exactly: BYTE_NVIDIA_CANARY_OK"
NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT = "BYTE_NVIDIA_CANARY_OK"
NVIDIA_01_QUALIFIED_SHA = "29daea6ef68ebb3d46031ce302b0108617bd1221"


@dataclass(frozen=True, slots=True)
class NvidiaCanaryPrepareReceipt:
    canary_id: str
    provider_id: str
    model_id: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    evidence_root: str


@dataclass(frozen=True, slots=True)
class NvidiaCanaryInspection:
    canary_id: str
    provider_id: str
    model_id: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    probe_text: str
    provider_started_at: str | None
    has_terminal_event: bool


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanaryTransmissionResult:
    canary_id: str
    request_sha256: str
    attempt_outcome: ProviderAttemptOutcome
    model_id: str
    semantic_probe_match: bool | None
    response_content: str | None = field(default=None, repr=False)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_timestamp(now: Callable[[], datetime]) -> str:
    value = now()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat()


def prepare_lightning_canary(
    store: NvidiaCanaryEvidenceStore,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> NvidiaCanaryPrepareReceipt:
    prepared = prepare_nvidia_chat_request(
        model_id=NVIDIA_LIGHTNING_CANARY_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": NVIDIA_LIGHTNING_CANARY_PROMPT,
            }
        ],
        temperature=1.0,
        top_p=0.95,
        max_tokens=64,
    )
    prepared_at = now().isoformat()
    manifest = store.prepare(
        prepared,
        probe_expected_text=NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT,
        qualified_predecessor_sha=NVIDIA_01_QUALIFIED_SHA,
        prepared_at=prepared_at,
    )
    return NvidiaCanaryPrepareReceipt(
        canary_id=manifest.canary_id,
        provider_id=manifest.provider_id,
        model_id=manifest.model_id,
        payload_sha256=manifest.payload_sha256,
        request_sha256=manifest.request_sha256,
        body_bytes=manifest.body_bytes,
        prepared_at=manifest.prepared_at,
        evidence_root=str(store.root),
    )


def inspect_lightning_canary(
    store: NvidiaCanaryEvidenceStore,
    canary_id: str,
) -> NvidiaCanaryInspection:
    snapshot = store.load(canary_id)
    manifest = snapshot.manifest
    return NvidiaCanaryInspection(
        canary_id=manifest.canary_id,
        provider_id=manifest.provider_id,
        model_id=manifest.model_id,
        payload_sha256=manifest.payload_sha256,
        request_sha256=manifest.request_sha256,
        body_bytes=manifest.body_bytes,
        prepared_at=manifest.prepared_at,
        probe_text=manifest.probe_expected_text,
        provider_started_at=snapshot.provider_started_at,
        has_terminal_event=snapshot.terminal_event is not None,
    )


async def transmit_lightning_canary(
    store: NvidiaCanaryEvidenceStore,
    *,
    canary_id: str,
    expected_request_sha256: str,
    approve: bool,
    settings_loader: Callable[[], NvidiaHostedSettings] = NvidiaHostedSettings.load,
    executor: Callable[
        [PreparedProviderRequest, ProviderTransmissionContext, NvidiaHostedSettings],
        Awaitable[NvidiaChatResult],
    ] = execute_prepared_nvidia_chat,
    now: Callable[[], datetime] = _utc_now,
) -> NvidiaCanaryTransmissionResult:
    """Execute one explicitly approved canary after all provider-free preflight checks."""

    with store.transmit_lock(canary_id):
        snapshot = store.load(canary_id)
        manifest = snapshot.manifest

        if approve is not True:
            raise ValueError("explicit canary approval is required")
        if expected_request_sha256 != manifest.request_sha256:
            raise ValueError("expected request identity does not match prepared canary")
        if snapshot.provider_started_at is not None:
            raise ValueError("canary provider-start already exists")
        if snapshot.terminal_event is not None:
            raise ValueError("canary attempt is already terminal")

        settings = settings_loader()
        if not isinstance(settings, NvidiaHostedSettings):
            raise ValueError("settings loader returned invalid NVIDIA hosted settings")
        if settings.api_key is None:
            raise ValueError("NVIDIA API key is not configured")

        prepared_request = PreparedProviderRequest(
            provider_id=manifest.provider_id,
            method=manifest.method,
            target_origin=manifest.target_origin,
            endpoint_path=manifest.endpoint_path,
            model_id=manifest.model_id,
            body_bytes=snapshot.request_body,
            payload_sha256=manifest.payload_sha256,
            request_sha256=manifest.request_sha256,
        )
        if (
            prepared_request.provider_id != NVIDIA_PROVIDER.provider_id
            or prepared_request.model_id != NVIDIA_LIGHTNING_CANARY_MODEL_ID
            or prepared_request.method != "POST"
            or prepared_request.target_origin != NVIDIA_CHAT_TARGET_ORIGIN
            or prepared_request.endpoint_path != NVIDIA_CHAT_ENDPOINT_PATH
        ):
            raise ValueError("prepared canary target is invalid")
        validate_prepared_provider_request_integrity(prepared_request)

        request_sha256 = manifest.request_sha256
        if snapshot.authorized_at is None:
            authorized_at = _utc_timestamp(now)
            store.append_authorized(
                canary_id,
                request_sha256=request_sha256,
                recorded_at=authorized_at,
            )

        provider_started_at = _utc_timestamp(now)
        store.append_provider_start(
            canary_id,
            request_sha256=request_sha256,
            recorded_at=provider_started_at,
        )
        context = ProviderTransmissionContext(
            provider_started_at=provider_started_at,
            expected_request_sha256=request_sha256,
        )
        result = await executor(prepared_request, context, settings)

        return NvidiaCanaryTransmissionResult(
            canary_id=canary_id,
            request_sha256=request_sha256,
            attempt_outcome=ProviderAttemptOutcome.COMPLETED,
            model_id=result.model_id,
            semantic_probe_match=result.content == NVIDIA_LIGHTNING_CANARY_EXPECTED_TEXT,
            response_content=result.content,
        )
