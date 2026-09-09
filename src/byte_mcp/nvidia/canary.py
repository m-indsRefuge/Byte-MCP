"""Fixed, provider-free preparation and inspection for the NVIDIA Lightning canary."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .canary_evidence import NvidiaCanaryEvidenceStore
from .chat import prepare_nvidia_chat_request

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


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
