"""Durable append-only evidence for NVIDIA routine code reviews."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from byte_mcp.errors import ByteMCPError
from byte_mcp.providers import (
    MAX_RESPONSE_BODY_BYTES,
    PreparedProviderRequest,
    ProviderAttemptOutcome,
    ProviderTransportFailureKind,
)
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity

from .chat import NVIDIA_CHAT_ENDPOINT_PATH, NVIDIA_CHAT_TARGET_ORIGIN
from .errors import NvidiaChatFailureKind
from .registry import NVIDIA_PROVIDER
from .review_packet import PreparedNvidiaReviewPacket
from .review_protocol import (
    NVIDIA_REVIEW_MODEL_ID,
    NVIDIA_REVIEW_PROTOCOL_VERSION,
    NvidiaReviewResult,
    NvidiaReviewResultError,
    parse_nvidia_review_result,
    prepare_nvidia_review_request,
)

NVIDIA_REVIEW_SCHEMA = "byte-mcp-nvidia-review-v1"
NVIDIA_REVIEW_ID_PATTERN = r"NVR-[0-9]{6}"
_REVIEW_ID = re.compile(rf"{NVIDIA_REVIEW_ID_PATTERN}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_FINISH_REASON = re.compile(r"[A-Za-z0-9._-]{0,64}\Z")
_MAX_PACKET_BYTES = 3_145_728
_MAX_REQUEST_BYTES = 4_000_000
_MAX_BOUNDED_INTEGER = 2_147_483_647
_MAX_RESPONSE_ID_CHARS = 256
_BASE_EVENT_KEYS = frozenset({"event_type", "review_id", "request_sha256", "recorded_at"})
_ALLOWED_BASE_EVENTS = frozenset({"REVIEW_PREPARED", "REVIEW_AUTHORIZED", "PROVIDER_START"})
_TERMINAL_EVENT_KEYS = frozenset(
    {
        "event_type",
        "review_id",
        "request_sha256",
        "provider_id",
        "model_id",
        "provider_started_at",
        "provider_finished_at",
        "attempt_outcome",
        "nvidia_failure_kind",
        "transport_failure_kind",
        "http_status_code",
        "response_headers_received",
        "response_body_started",
        "decoded_body_bytes_received",
        "elapsed_ms",
        "finish_reason",
        "response_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "review_result_status",
        "result_sha256",
        "recorded_at",
    }
)
_ATTEMPT_OUTCOMES = frozenset(outcome.value for outcome in ProviderAttemptOutcome)
_NVIDIA_FAILURE_KINDS = frozenset(kind.value for kind in NvidiaChatFailureKind)
_TRANSPORT_FAILURE_KINDS = frozenset(kind.value for kind in ProviderTransportFailureKind)
_RESULT_STATUSES = frozenset({"VALID", "INVALID", "NOT_AVAILABLE"})


class NvidiaReviewEvidenceError(ByteMCPError):
    """Raised when durable NVIDIA review evidence is invalid or unavailable."""


class NvidiaReviewLockError(ByteMCPError):
    """Raised when exclusive NVIDIA review ownership cannot be acquired."""


def _require_aware_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    return value


def _require_digest(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _require_review_id(value: object) -> str:
    if not isinstance(value, str) or _REVIEW_ID.fullmatch(value) is None:
        raise NvidiaReviewEvidenceError("review identity is invalid")
    return value


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise NvidiaReviewEvidenceError("review evidence is not canonical JSON") from None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_immutable(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise NvidiaReviewEvidenceError("immutable review evidence already exists") from None
    except OSError:
        raise NvidiaReviewEvidenceError("unable to create immutable review evidence") from None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise NvidiaReviewEvidenceError("unable to persist immutable review evidence") from None


def _append_event(path: Path, event: Mapping[str, object]) -> None:
    payload = _canonical_json(dict(event)) + b"\n"
    try:
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise NvidiaReviewEvidenceError("unable to append review lifecycle evidence") from None


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise NvidiaReviewLockError("review lock is already held") from None
    except OSError:
        raise NvidiaReviewLockError("unable to acquire review lock") from None
    try:
        try:
            os.write(descriptor, b"locked\n")
            os.fsync(descriptor)
        except OSError:
            raise NvidiaReviewLockError("unable to persist review lock") from None
        yield
    finally:
        try:
            os.close(descriptor)
        finally:
            with suppress(OSError):
                path.unlink(missing_ok=True)


def _optional_bounded_string(
    value: object,
    *,
    field_name: str,
    max_chars: int,
    pattern: re.Pattern[str] | None = None,
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) > max_chars:
        raise NvidiaReviewEvidenceError(f"terminal {field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise NvidiaReviewEvidenceError(f"terminal {field_name} is invalid")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise NvidiaReviewEvidenceError(f"terminal {field_name} is invalid")


def _optional_counter(value: object, field_name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_BOUNDED_INTEGER
    ):
        raise NvidiaReviewEvidenceError(f"terminal {field_name} is invalid")


def _packet_payload(packet_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(packet_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NvidiaReviewEvidenceError("review packet is malformed") from None
    if not isinstance(payload, dict):
        raise NvidiaReviewEvidenceError("review packet is malformed")
    if _canonical_json(payload) != packet_bytes:
        raise NvidiaReviewEvidenceError("review packet is not canonical")
    return payload


def _allowed_paths(packet_payload: Mapping[str, object]) -> frozenset[str]:
    artifacts = packet_payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise NvidiaReviewEvidenceError("review packet artifacts are malformed")
    paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise NvidiaReviewEvidenceError("review packet artifacts are malformed")
        path = artifact.get("logical_path")
        if not isinstance(path, str):
            raise NvidiaReviewEvidenceError("review packet artifacts are malformed")
        paths.add(path)
    return frozenset(paths)


def _result_payload(result: NvidiaReviewResult) -> dict[str, object]:
    return {
        "decision": result.decision,
        "summary": result.summary,
        "findings": [asdict(finding) for finding in result.findings],
    }


@dataclass(frozen=True, slots=True)
class NvidiaReviewEvidenceManifest:
    schema: str
    review_id: str
    repository_alias: str
    subsystem_id: str
    base_commit: str
    target_commit: str
    protocol_version: str
    provider_id: str
    model_id: str
    method: str
    target_origin: str
    endpoint_path: str
    packet_sha256: str
    packet_bytes: int
    manifest_sha256: str
    payload_sha256: str
    request_sha256: str
    request_body_bytes: int
    prepared_at: str

    def __post_init__(self) -> None:
        if self.schema != NVIDIA_REVIEW_SCHEMA:
            raise ValueError("schema is invalid")
        if not isinstance(self.review_id, str) or _REVIEW_ID.fullmatch(self.review_id) is None:
            raise ValueError("review_id is invalid")
        if not isinstance(self.repository_alias, str) or not self.repository_alias:
            raise ValueError("repository_alias is invalid")
        if not isinstance(self.subsystem_id, str) or not self.subsystem_id:
            raise ValueError("subsystem_id is invalid")
        _require_digest(self.base_commit, "base_commit", _GIT_SHA1)
        _require_digest(self.target_commit, "target_commit", _GIT_SHA1)
        if self.protocol_version != NVIDIA_REVIEW_PROTOCOL_VERSION:
            raise ValueError("protocol_version is invalid")
        if self.provider_id != NVIDIA_PROVIDER.provider_id:
            raise ValueError("provider_id is invalid")
        if self.model_id != NVIDIA_REVIEW_MODEL_ID:
            raise ValueError("model_id is invalid")
        if self.method != "POST":
            raise ValueError("method is invalid")
        if self.target_origin != NVIDIA_CHAT_TARGET_ORIGIN:
            raise ValueError("target_origin is invalid")
        if self.endpoint_path != NVIDIA_CHAT_ENDPOINT_PATH:
            raise ValueError("endpoint_path is invalid")
        _require_digest(self.packet_sha256, "packet_sha256", _SHA256)
        _require_digest(self.manifest_sha256, "manifest_sha256", _SHA256)
        _require_digest(self.payload_sha256, "payload_sha256", _SHA256)
        _require_digest(self.request_sha256, "request_sha256", _SHA256)
        if (
            isinstance(self.packet_bytes, bool)
            or not isinstance(self.packet_bytes, int)
            or not 1 <= self.packet_bytes <= _MAX_PACKET_BYTES
        ):
            raise ValueError("packet_bytes is invalid")
        if (
            isinstance(self.request_body_bytes, bool)
            or not isinstance(self.request_body_bytes, int)
            or not 1 <= self.request_body_bytes <= _MAX_REQUEST_BYTES
        ):
            raise ValueError("request_body_bytes is invalid")
        _require_aware_timestamp(self.prepared_at, "prepared_at")


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaReviewSnapshot:
    manifest: NvidiaReviewEvidenceManifest
    review_packet: bytes = field(repr=False)
    request_body: bytes = field(repr=False)
    events: tuple[dict[str, object], ...]
    authorized_at: str | None
    provider_started_at: str | None
    terminal_event: dict[str, object] | None
    result: NvidiaReviewResult | None
    result_sha256: str | None

    def __repr__(self) -> str:
        return (
            "NvidiaReviewSnapshot("
            f"manifest={self.manifest!r}, review_packet_bytes={len(self.review_packet)!r}, "
            f"request_body_bytes={len(self.request_body)!r}, events={len(self.events)!r}, "
            f"authorized_at={self.authorized_at!r}, "
            f"provider_started_at={self.provider_started_at!r}, "
            f"terminal_event_present={self.terminal_event is not None!r}, "
            f"result_present={self.result is not None!r})"
        )


def _validate_terminal_event(
    event: Mapping[str, object],
    *,
    snapshot: NvidiaReviewSnapshot,
) -> None:
    manifest = snapshot.manifest
    if set(event) != _TERMINAL_EVENT_KEYS or event.get("event_type") != "REVIEW_TERMINAL":
        raise NvidiaReviewEvidenceError("review terminal event is malformed")
    if event.get("review_id") != manifest.review_id:
        raise NvidiaReviewEvidenceError("terminal review identity is invalid")
    if event.get("request_sha256") != manifest.request_sha256:
        raise NvidiaReviewEvidenceError("terminal request identity is invalid")
    if event.get("provider_id") != manifest.provider_id:
        raise NvidiaReviewEvidenceError("terminal provider identity is invalid")
    if event.get("model_id") != manifest.model_id:
        raise NvidiaReviewEvidenceError("terminal model identity is invalid")
    if event.get("provider_started_at") != snapshot.provider_started_at:
        raise NvidiaReviewEvidenceError("terminal provider-start is inconsistent")
    try:
        _require_aware_timestamp(event.get("provider_started_at"), "provider_started_at")
        _require_aware_timestamp(event.get("provider_finished_at"), "provider_finished_at")
        _require_aware_timestamp(event.get("recorded_at"), "recorded_at")
    except ValueError:
        raise NvidiaReviewEvidenceError("terminal timestamp is invalid") from None

    attempt_outcome = event.get("attempt_outcome")
    if attempt_outcome not in _ATTEMPT_OUTCOMES:
        raise NvidiaReviewEvidenceError("terminal attempt outcome is invalid")
    nvidia_failure_kind = event.get("nvidia_failure_kind")
    if nvidia_failure_kind is not None and nvidia_failure_kind not in _NVIDIA_FAILURE_KINDS:
        raise NvidiaReviewEvidenceError("terminal NVIDIA failure kind is invalid")
    transport_failure_kind = event.get("transport_failure_kind")
    if (
        transport_failure_kind is not None
        and transport_failure_kind not in _TRANSPORT_FAILURE_KINDS
    ):
        raise NvidiaReviewEvidenceError("terminal transport failure kind is invalid")

    status_code = event.get("http_status_code")
    if status_code is not None and (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        raise NvidiaReviewEvidenceError("terminal HTTP status code is invalid")
    for field_name in ("response_headers_received", "response_body_started"):
        if not isinstance(event.get(field_name), bool):
            raise NvidiaReviewEvidenceError(f"terminal {field_name} is invalid")
    decoded = event.get("decoded_body_bytes_received")
    if (
        isinstance(decoded, bool)
        or not isinstance(decoded, int)
        or not 0 <= decoded <= MAX_RESPONSE_BODY_BYTES
    ):
        raise NvidiaReviewEvidenceError("terminal decoded body byte count is invalid")
    elapsed_ms = event.get("elapsed_ms")
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, int)
        or not 0 <= elapsed_ms <= _MAX_BOUNDED_INTEGER
    ):
        raise NvidiaReviewEvidenceError("terminal elapsed time is invalid")

    _optional_bounded_string(
        event.get("finish_reason"),
        field_name="finish_reason",
        max_chars=64,
        pattern=_FINISH_REASON,
    )
    _optional_bounded_string(
        event.get("response_id"),
        field_name="response_id",
        max_chars=_MAX_RESPONSE_ID_CHARS,
    )
    for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        _optional_counter(event.get(field_name), field_name)

    result_status = event.get("review_result_status")
    result_sha256 = event.get("result_sha256")
    if result_status not in _RESULT_STATUSES:
        raise NvidiaReviewEvidenceError("terminal review result status is invalid")
    if result_status == "VALID":
        if (
            attempt_outcome != ProviderAttemptOutcome.COMPLETED.value
            or snapshot.result is None
            or snapshot.result_sha256 is None
            or result_sha256 != snapshot.result_sha256
        ):
            raise NvidiaReviewEvidenceError("terminal result identity is invalid")
    elif result_sha256 is not None or snapshot.result is not None:
        raise NvidiaReviewEvidenceError("terminal result identity is invalid")
    if result_status == "INVALID" and attempt_outcome != ProviderAttemptOutcome.COMPLETED.value:
        raise NvidiaReviewEvidenceError("terminal invalid result outcome is inconsistent")


class NvidiaReviewEvidenceStore:
    """Persist and validate local NVIDIA routine-review lifecycle evidence."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise ValueError("root is invalid")
        self.root = root.expanduser().resolve(strict=False)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        platform_name: str | None = None,
        home: Path | None = None,
    ) -> NvidiaReviewEvidenceStore:
        environment = os.environ if environ is None else environ
        platform = sys.platform if platform_name is None else platform_name
        home_path = Path.home() if home is None else home
        explicit = environment.get("BYTE_MCP_NVIDIA_EVIDENCE_DIR", "").strip()
        if explicit:
            return cls(Path(explicit))
        if platform == "win32":
            local_app_data = environment.get("LOCALAPPDATA", "").strip()
            base = Path(local_app_data) if local_app_data else home_path / "AppData" / "Local"
            return cls(base / "Byte-MCP" / "nvidia")
        xdg_data_home = environment.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg_data_home) if xdg_data_home else home_path / ".local" / "share"
        return cls(base / "byte-mcp" / "nvidia")

    def _review_dir(self, review_id: str) -> Path:
        return self.root / "reviews" / _require_review_id(review_id)

    def prepare(
        self,
        packet: PreparedNvidiaReviewPacket,
        prepared_request: PreparedProviderRequest,
        *,
        prepared_at: str,
    ) -> NvidiaReviewEvidenceManifest:
        if not isinstance(packet, PreparedNvidiaReviewPacket):
            raise NvidiaReviewEvidenceError("prepared review packet is invalid")
        try:
            _require_aware_timestamp(prepared_at, "prepared_at")
            validate_prepared_provider_request_integrity(prepared_request)
        except (TypeError, ValueError):
            raise NvidiaReviewEvidenceError("prepared review identity is invalid") from None

        expected_request = prepare_nvidia_review_request(packet)
        if prepared_request != expected_request:
            raise NvidiaReviewEvidenceError("prepared request does not match review packet")
        packet_payload = _packet_payload(packet.serialized_packet)
        if packet_payload.get("repository_alias") != packet.repository_alias:
            raise NvidiaReviewEvidenceError("review packet repository identity is invalid")
        if packet_payload.get("subsystem_id") != packet.subsystem_id:
            raise NvidiaReviewEvidenceError("review packet subsystem identity is invalid")

        self.root.mkdir(parents=True, exist_ok=True)
        reviews_root = self.root / "reviews"
        reviews_root.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.root / ".review-prepare.lock"):
            review_dir: Path | None = None
            review_id = ""
            for number in range(1, 1_000_000):
                candidate = f"NVR-{number:06d}"
                candidate_dir = reviews_root / candidate
                try:
                    candidate_dir.mkdir()
                except FileExistsError:
                    continue
                except OSError:
                    raise NvidiaReviewEvidenceError("unable to allocate review identity") from None
                review_id = candidate
                review_dir = candidate_dir
                break
            if review_dir is None:
                raise NvidiaReviewEvidenceError("no review identity is available")

            manifest = NvidiaReviewEvidenceManifest(
                schema=NVIDIA_REVIEW_SCHEMA,
                review_id=review_id,
                repository_alias=packet.repository_alias,
                subsystem_id=packet.subsystem_id,
                base_commit=packet.base_commit,
                target_commit=packet.target_commit,
                protocol_version=NVIDIA_REVIEW_PROTOCOL_VERSION,
                provider_id=prepared_request.provider_id,
                model_id=prepared_request.model_id,
                method=prepared_request.method,
                target_origin=prepared_request.target_origin,
                endpoint_path=prepared_request.endpoint_path,
                packet_sha256=_sha256(packet.serialized_packet),
                packet_bytes=len(packet.serialized_packet),
                manifest_sha256=packet.manifest.manifest_sha256,
                payload_sha256=prepared_request.payload_sha256,
                request_sha256=prepared_request.request_sha256,
                request_body_bytes=len(prepared_request.body_bytes),
                prepared_at=prepared_at,
            )
            _write_immutable(review_dir / "review-packet.json", packet.serialized_packet)
            _write_immutable(review_dir / "request-body.bin", prepared_request.body_bytes)
            _write_immutable(review_dir / "manifest.json", _canonical_json(asdict(manifest)))
            _append_event(
                review_dir / "events.jsonl",
                {
                    "event_type": "REVIEW_PREPARED",
                    "review_id": review_id,
                    "request_sha256": manifest.request_sha256,
                    "recorded_at": prepared_at,
                },
            )
            return manifest

    def load(self, review_id: str) -> NvidiaReviewSnapshot:
        review_dir = self._review_dir(review_id)
        try:
            manifest_bytes = (review_dir / "manifest.json").read_bytes()
            packet_bytes = (review_dir / "review-packet.json").read_bytes()
            request_body = (review_dir / "request-body.bin").read_bytes()
            event_bytes = (review_dir / "events.jsonl").read_bytes()
        except OSError:
            raise NvidiaReviewEvidenceError("unable to read review evidence") from None

        if not event_bytes.endswith(b"\n"):
            raise NvidiaReviewEvidenceError("review events are malformed")
        try:
            manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
            event_text = event_bytes.decode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NvidiaReviewEvidenceError("review evidence is malformed") from None
        if (
            not isinstance(manifest_payload, dict)
            or _canonical_json(manifest_payload) != manifest_bytes
        ):
            raise NvidiaReviewEvidenceError("review manifest is malformed")
        try:
            manifest = NvidiaReviewEvidenceManifest(**manifest_payload)
        except (TypeError, ValueError):
            raise NvidiaReviewEvidenceError("review manifest is malformed") from None
        if manifest.review_id != review_id:
            raise NvidiaReviewEvidenceError("review manifest identity is inconsistent")
        if (
            len(packet_bytes) != manifest.packet_bytes
            or _sha256(packet_bytes) != manifest.packet_sha256
        ):
            raise NvidiaReviewEvidenceError("review packet integrity failed")
        if (
            len(request_body) != manifest.request_body_bytes
            or _sha256(request_body) != manifest.payload_sha256
        ):
            raise NvidiaReviewEvidenceError("review request body integrity failed")

        packet_payload = _packet_payload(packet_bytes)
        if (
            packet_payload.get("repository_alias") != manifest.repository_alias
            or packet_payload.get("subsystem_id") != manifest.subsystem_id
            or packet_payload.get("base_commit") != manifest.base_commit
            or packet_payload.get("target_commit") != manifest.target_commit
        ):
            raise NvidiaReviewEvidenceError("review packet identity is inconsistent")
        packet_manifest = packet_payload.get("manifest")
        if (
            not isinstance(packet_manifest, dict)
            or packet_manifest.get("manifest_sha256") != manifest.manifest_sha256
        ):
            raise NvidiaReviewEvidenceError("review packet manifest identity is inconsistent")

        prepared_request = PreparedProviderRequest(
            provider_id=manifest.provider_id,
            method=manifest.method,
            target_origin=manifest.target_origin,
            endpoint_path=manifest.endpoint_path,
            model_id=manifest.model_id,
            body_bytes=request_body,
            payload_sha256=manifest.payload_sha256,
            request_sha256=manifest.request_sha256,
        )
        try:
            validate_prepared_provider_request_integrity(prepared_request)
        except ValueError:
            raise NvidiaReviewEvidenceError("review request identity integrity failed") from None

        result: NvidiaReviewResult | None = None
        result_sha256: str | None = None
        result_path = review_dir / "result.json"
        if result_path.exists():
            try:
                result_bytes = result_path.read_bytes()
                result_text = result_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                raise NvidiaReviewEvidenceError("review result is malformed") from None
            try:
                result = parse_nvidia_review_result(result_text, _allowed_paths(packet_payload))
            except NvidiaReviewResultError:
                raise NvidiaReviewEvidenceError("review result is malformed") from None
            if _canonical_json(_result_payload(result)) != result_bytes:
                raise NvidiaReviewEvidenceError("review result is not canonical")
            result_sha256 = _sha256(result_bytes)

        events: list[dict[str, object]] = []
        for line in event_text.splitlines():
            if not line:
                raise NvidiaReviewEvidenceError("review events are malformed")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                raise NvidiaReviewEvidenceError("review events are malformed") from None
            if not isinstance(event, dict):
                raise NvidiaReviewEvidenceError("review events are malformed")
            event_type = event.get("event_type")
            if event_type == "REVIEW_TERMINAL":
                if set(event) != _TERMINAL_EVENT_KEYS:
                    raise NvidiaReviewEvidenceError("review terminal event is malformed")
            elif event_type in _ALLOWED_BASE_EVENTS:
                if set(event) != _BASE_EVENT_KEYS:
                    raise NvidiaReviewEvidenceError("review events are malformed")
            else:
                raise NvidiaReviewEvidenceError("review event type is invalid")
            if event.get("review_id") != review_id:
                raise NvidiaReviewEvidenceError("review event identity is invalid")
            if event.get("request_sha256") != manifest.request_sha256:
                raise NvidiaReviewEvidenceError("review event request identity is invalid")
            try:
                _require_aware_timestamp(event.get("recorded_at"), "recorded_at")
            except ValueError:
                raise NvidiaReviewEvidenceError("review event timestamp is invalid") from None
            events.append(event)

        if not events or events[0].get("event_type") != "REVIEW_PREPARED":
            raise NvidiaReviewEvidenceError("review lifecycle is malformed")
        if events[0].get("recorded_at") != manifest.prepared_at:
            raise NvidiaReviewEvidenceError("review prepared timestamp is inconsistent")

        authorized_at: str | None = None
        provider_started_at: str | None = None
        terminal_event: dict[str, object] | None = None
        snapshot = NvidiaReviewSnapshot(
            manifest=manifest,
            review_packet=packet_bytes,
            request_body=request_body,
            events=tuple(events),
            authorized_at=None,
            provider_started_at=None,
            terminal_event=None,
            result=result,
            result_sha256=result_sha256,
        )
        for index, event in enumerate(events[1:], start=1):
            if terminal_event is not None:
                raise NvidiaReviewEvidenceError("event after review terminal is invalid")
            event_type = event["event_type"]
            recorded_at = str(event["recorded_at"])
            if event_type == "REVIEW_PREPARED":
                raise NvidiaReviewEvidenceError("duplicate review preparation event")
            if event_type == "REVIEW_AUTHORIZED":
                if authorized_at is not None or provider_started_at is not None or index != 1:
                    raise NvidiaReviewEvidenceError("review authorization ordering is invalid")
                authorized_at = recorded_at
                continue
            if event_type == "PROVIDER_START":
                if authorized_at is None or provider_started_at is not None or index != 2:
                    raise NvidiaReviewEvidenceError("provider-start ordering is invalid")
                provider_started_at = recorded_at
                continue
            if event_type == "REVIEW_TERMINAL":
                if provider_started_at is None or index != 3:
                    raise NvidiaReviewEvidenceError("review terminal ordering is invalid")
                snapshot = NvidiaReviewSnapshot(
                    manifest=manifest,
                    review_packet=packet_bytes,
                    request_body=request_body,
                    events=tuple(events),
                    authorized_at=authorized_at,
                    provider_started_at=provider_started_at,
                    terminal_event=None,
                    result=result,
                    result_sha256=result_sha256,
                )
                _validate_terminal_event(event, snapshot=snapshot)
                terminal_event = event
                continue
            raise NvidiaReviewEvidenceError("review lifecycle is malformed")

        if result is not None and provider_started_at is None:
            raise NvidiaReviewEvidenceError("review result exists before provider-start")
        if (
            terminal_event is not None
            and terminal_event.get("review_result_status") != "VALID"
            and result is not None
        ):
            raise NvidiaReviewEvidenceError("review result is inconsistent with terminal state")

        return NvidiaReviewSnapshot(
            manifest=manifest,
            review_packet=packet_bytes,
            request_body=request_body,
            events=tuple(events),
            authorized_at=authorized_at,
            provider_started_at=provider_started_at,
            terminal_event=terminal_event,
            result=result,
            result_sha256=result_sha256,
        )

    def append_authorized(
        self,
        review_id: str,
        *,
        request_sha256: str,
        recorded_at: str,
    ) -> None:
        snapshot = self.load(review_id)
        try:
            _require_aware_timestamp(recorded_at, "recorded_at")
        except ValueError:
            raise NvidiaReviewEvidenceError("authorization timestamp is invalid") from None
        if request_sha256 != snapshot.manifest.request_sha256:
            raise NvidiaReviewEvidenceError("authorization request identity is invalid")
        if snapshot.terminal_event is not None:
            raise NvidiaReviewEvidenceError("review is terminal")
        if snapshot.authorized_at is not None or snapshot.provider_started_at is not None:
            raise NvidiaReviewEvidenceError("review authorization already exists")
        _append_event(
            self._review_dir(review_id) / "events.jsonl",
            {
                "event_type": "REVIEW_AUTHORIZED",
                "review_id": review_id,
                "request_sha256": request_sha256,
                "recorded_at": recorded_at,
            },
        )

    def append_provider_start(
        self,
        review_id: str,
        *,
        request_sha256: str,
        recorded_at: str,
    ) -> None:
        snapshot = self.load(review_id)
        try:
            _require_aware_timestamp(recorded_at, "recorded_at")
        except ValueError:
            raise NvidiaReviewEvidenceError("provider-start timestamp is invalid") from None
        if request_sha256 != snapshot.manifest.request_sha256:
            raise NvidiaReviewEvidenceError("provider-start request identity is invalid")
        if snapshot.terminal_event is not None:
            raise NvidiaReviewEvidenceError("review is terminal")
        if snapshot.authorized_at is None:
            raise NvidiaReviewEvidenceError("review is not authorized")
        if snapshot.provider_started_at is not None:
            raise NvidiaReviewEvidenceError("provider-start already exists")
        _append_event(
            self._review_dir(review_id) / "events.jsonl",
            {
                "event_type": "PROVIDER_START",
                "review_id": review_id,
                "request_sha256": request_sha256,
                "recorded_at": recorded_at,
            },
        )

    def persist_result(self, review_id: str, result: NvidiaReviewResult) -> str:
        snapshot = self.load(review_id)
        if snapshot.provider_started_at is None:
            raise NvidiaReviewEvidenceError("review result requires provider-start")
        if snapshot.terminal_event is not None:
            raise NvidiaReviewEvidenceError("review is terminal")
        if not isinstance(result, NvidiaReviewResult):
            raise NvidiaReviewEvidenceError("review result is invalid")
        packet_payload = _packet_payload(snapshot.review_packet)
        payload = _result_payload(result)
        result_bytes = _canonical_json(payload)
        try:
            validated = parse_nvidia_review_result(
                result_bytes.decode("utf-8"),
                _allowed_paths(packet_payload),
            )
        except NvidiaReviewResultError:
            raise NvidiaReviewEvidenceError("review result is invalid") from None
        if validated != result:
            raise NvidiaReviewEvidenceError("review result is invalid")
        _write_immutable(self._review_dir(review_id) / "result.json", result_bytes)
        return _sha256(result_bytes)

    def append_terminal(self, review_id: str, event: Mapping[str, object]) -> None:
        if not isinstance(event, Mapping):
            raise NvidiaReviewEvidenceError("review terminal event is malformed")
        snapshot = self.load(review_id)
        if snapshot.provider_started_at is None:
            raise NvidiaReviewEvidenceError("review terminal requires provider-start")
        if snapshot.terminal_event is not None:
            raise NvidiaReviewEvidenceError("review terminal already exists")
        terminal_event = dict(event)
        _validate_terminal_event(terminal_event, snapshot=snapshot)
        _append_event(self._review_dir(review_id) / "events.jsonl", terminal_event)

    @contextmanager
    def transmit_lock(self, review_id: str) -> Iterator[None]:
        review_dir = self._review_dir(review_id)
        if not review_dir.is_dir():
            raise NvidiaReviewEvidenceError("review evidence does not exist")
        with _exclusive_lock(review_dir / ".transmit.lock"):
            yield
