"""Durable evidence contracts for the governed NVIDIA canary lifecycle."""

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

from .errors import NvidiaChatFailureKind

NVIDIA_CANARY_SCHEMA = "byte-mcp-nvidia-canary-v1"
NVIDIA_CANARY_ID_PATTERN = r"NVC-[0-9]{6}"
_MAX_PREPARED_BODY_BYTES = 4_000_000
_MAX_BOUNDED_INTEGER = 2_147_483_647
_MAX_RESPONSE_ID_CHARS = 256
_CANARY_ID = re.compile(rf"{NVIDIA_CANARY_ID_PATTERN}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_FINISH_REASON = re.compile(r"[A-Za-z0-9._-]{0,64}\Z")

_NVIDIA_PROVIDER_ID = "nvidia-api-catalog"
_NVIDIA_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
_NVIDIA_METHOD = "POST"
_NVIDIA_TARGET_ORIGIN = "https://integrate.api.nvidia.com"
_NVIDIA_ENDPOINT_PATH = "/v1/chat/completions"
_BASE_EVENT_KEYS = frozenset({"event_type", "canary_id", "request_sha256", "recorded_at"})
_ALLOWED_BASE_EVENTS = frozenset({"CANARY_PREPARED", "CANARY_AUTHORIZED", "PROVIDER_START"})
_TERMINAL_EVENT_KEYS = frozenset(
    {
        "event_type",
        "canary_id",
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
        "semantic_probe_match",
        "recorded_at",
    }
)
_ATTEMPT_OUTCOMES = frozenset(outcome.value for outcome in ProviderAttemptOutcome)
_NVIDIA_FAILURE_KINDS = frozenset(kind.value for kind in NvidiaChatFailureKind)
_TRANSPORT_FAILURE_KINDS = frozenset(kind.value for kind in ProviderTransportFailureKind)


def _require_aware_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    return value


def _require_digest(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _require_canary_id(value: object) -> str:
    if not isinstance(value, str) or _CANARY_ID.fullmatch(value) is None:
        raise NvidiaCanaryEvidenceError("canary identity is invalid")
    return value


def _require_optional_bounded_string(
    value: object,
    *,
    field_name: str,
    max_chars: int,
    pattern: re.Pattern[str] | None = None,
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) > max_chars:
        raise NvidiaCanaryEvidenceError(f"terminal {field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise NvidiaCanaryEvidenceError(f"terminal {field_name} is invalid")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise NvidiaCanaryEvidenceError(f"terminal {field_name} is invalid")


def _require_optional_counter(value: object, field_name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_BOUNDED_INTEGER
    ):
        raise NvidiaCanaryEvidenceError(f"terminal {field_name} is invalid")


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
        raise NvidiaCanaryEvidenceError("canary evidence is not canonical JSON") from None


def _write_immutable(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise NvidiaCanaryEvidenceError("immutable canary evidence already exists") from None
    except OSError:
        raise NvidiaCanaryEvidenceError("unable to create immutable canary evidence") from None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise NvidiaCanaryEvidenceError("unable to persist immutable canary evidence") from None


def _append_event(path: Path, event: Mapping[str, object]) -> None:
    payload = _canonical_json(dict(event)) + b"\n"
    try:
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise NvidiaCanaryEvidenceError("unable to append canary lifecycle evidence") from None


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise NvidiaCanaryLockError("canary lock is already held") from None
    except OSError:
        raise NvidiaCanaryLockError("unable to acquire canary lock") from None
    try:
        try:
            os.write(descriptor, b"locked\n")
            os.fsync(descriptor)
        except OSError:
            raise NvidiaCanaryLockError("unable to persist canary lock") from None
        yield
    finally:
        try:
            os.close(descriptor)
        finally:
            with suppress(OSError):
                path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class NvidiaCanaryManifest:
    schema: str
    canary_id: str
    provider_id: str
    model_id: str
    method: str
    target_origin: str
    endpoint_path: str
    payload_sha256: str
    request_sha256: str
    body_bytes: int
    prepared_at: str
    probe_expected_text: str
    qualified_predecessor_sha: str

    def __post_init__(self) -> None:
        if self.schema != NVIDIA_CANARY_SCHEMA:
            raise ValueError("schema is invalid")
        if not isinstance(self.canary_id, str) or _CANARY_ID.fullmatch(self.canary_id) is None:
            raise ValueError("canary_id is invalid")
        if self.provider_id != _NVIDIA_PROVIDER_ID:
            raise ValueError("provider_id is invalid")
        if self.model_id != _NVIDIA_MODEL_ID:
            raise ValueError("model_id is invalid")
        if self.method != _NVIDIA_METHOD:
            raise ValueError("method is invalid")
        if self.target_origin != _NVIDIA_TARGET_ORIGIN:
            raise ValueError("target_origin is invalid")
        if self.endpoint_path != _NVIDIA_ENDPOINT_PATH:
            raise ValueError("endpoint_path is invalid")
        _require_digest(self.payload_sha256, "payload_sha256", _SHA256)
        _require_digest(self.request_sha256, "request_sha256", _SHA256)
        if (
            isinstance(self.body_bytes, bool)
            or not isinstance(self.body_bytes, int)
            or not 1 <= self.body_bytes <= _MAX_PREPARED_BODY_BYTES
        ):
            raise ValueError("body_bytes is invalid")
        _require_aware_timestamp(self.prepared_at, "prepared_at")
        if not isinstance(self.probe_expected_text, str) or not self.probe_expected_text:
            raise ValueError("probe_expected_text is invalid")
        _require_digest(self.qualified_predecessor_sha, "qualified_predecessor_sha", _GIT_SHA1)


@dataclass(frozen=True, slots=True, repr=False)
class NvidiaCanarySnapshot:
    manifest: NvidiaCanaryManifest
    request_body: bytes = field(repr=False)
    events: tuple[dict[str, object], ...]
    authorized_at: str | None
    provider_started_at: str | None
    terminal_event: dict[str, object] | None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, NvidiaCanaryManifest):
            raise ValueError("manifest is invalid")
        if not isinstance(self.request_body, bytes):
            raise ValueError("request_body is invalid")
        if not isinstance(self.events, tuple) or any(
            not isinstance(event, dict) for event in self.events
        ):
            raise ValueError("events are invalid")
        if self.authorized_at is not None:
            _require_aware_timestamp(self.authorized_at, "authorized_at")
        if self.provider_started_at is not None:
            _require_aware_timestamp(self.provider_started_at, "provider_started_at")
        if self.terminal_event is not None and not isinstance(self.terminal_event, dict):
            raise ValueError("terminal_event is invalid")

    def __repr__(self) -> str:
        return (
            "NvidiaCanarySnapshot("
            f"manifest={self.manifest!r}, request_body_bytes={len(self.request_body)!r}, "
            f"events={len(self.events)!r}, authorized_at={self.authorized_at!r}, "
            f"provider_started_at={self.provider_started_at!r}, "
            f"terminal_event_present={self.terminal_event is not None!r})"
        )


class NvidiaCanaryEvidenceError(ByteMCPError):
    """Raised when durable NVIDIA canary evidence is invalid or unavailable."""


class NvidiaCanaryLockError(ByteMCPError):
    """Raised when exclusive NVIDIA canary ownership cannot be acquired safely."""


def _validate_terminal_event(
    event: Mapping[str, object],
    *,
    canary_id: str,
    manifest: NvidiaCanaryManifest,
    provider_started_at: str,
) -> None:
    if set(event) != _TERMINAL_EVENT_KEYS or event.get("event_type") != "CANARY_TERMINAL":
        raise NvidiaCanaryEvidenceError("canary terminal event is malformed")
    if event.get("canary_id") != canary_id:
        raise NvidiaCanaryEvidenceError("terminal canary identity is invalid")
    if event.get("request_sha256") != manifest.request_sha256:
        raise NvidiaCanaryEvidenceError("terminal request identity is invalid")
    if event.get("provider_id") != manifest.provider_id:
        raise NvidiaCanaryEvidenceError("terminal provider identity is invalid")
    if event.get("model_id") != manifest.model_id:
        raise NvidiaCanaryEvidenceError("terminal model identity is invalid")
    if event.get("provider_started_at") != provider_started_at:
        raise NvidiaCanaryEvidenceError("terminal provider-start is inconsistent")
    try:
        _require_aware_timestamp(event.get("provider_started_at"), "provider_started_at")
        _require_aware_timestamp(event.get("provider_finished_at"), "provider_finished_at")
        _require_aware_timestamp(event.get("recorded_at"), "recorded_at")
    except ValueError:
        raise NvidiaCanaryEvidenceError("terminal timestamp is invalid") from None

    if event.get("attempt_outcome") not in _ATTEMPT_OUTCOMES:
        raise NvidiaCanaryEvidenceError("terminal attempt outcome is invalid")
    nvidia_failure_kind = event.get("nvidia_failure_kind")
    if nvidia_failure_kind is not None and nvidia_failure_kind not in _NVIDIA_FAILURE_KINDS:
        raise NvidiaCanaryEvidenceError("terminal NVIDIA failure kind is invalid")
    transport_failure_kind = event.get("transport_failure_kind")
    if (
        transport_failure_kind is not None
        and transport_failure_kind not in _TRANSPORT_FAILURE_KINDS
    ):
        raise NvidiaCanaryEvidenceError("terminal transport failure kind is invalid")

    status_code = event.get("http_status_code")
    if status_code is not None and (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        raise NvidiaCanaryEvidenceError("terminal HTTP status code is invalid")
    for field_name in ("response_headers_received", "response_body_started"):
        if not isinstance(event.get(field_name), bool):
            raise NvidiaCanaryEvidenceError(f"terminal {field_name} is invalid")

    decoded_body_bytes_received = event.get("decoded_body_bytes_received")
    if (
        isinstance(decoded_body_bytes_received, bool)
        or not isinstance(decoded_body_bytes_received, int)
        or not 0 <= decoded_body_bytes_received <= MAX_RESPONSE_BODY_BYTES
    ):
        raise NvidiaCanaryEvidenceError("terminal decoded body byte count is invalid")
    elapsed_ms = event.get("elapsed_ms")
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, int)
        or not 0 <= elapsed_ms <= _MAX_BOUNDED_INTEGER
    ):
        raise NvidiaCanaryEvidenceError("terminal elapsed time is invalid")

    _require_optional_bounded_string(
        event.get("finish_reason"),
        field_name="finish_reason",
        max_chars=64,
        pattern=_FINISH_REASON,
    )
    _require_optional_bounded_string(
        event.get("response_id"),
        field_name="response_id",
        max_chars=_MAX_RESPONSE_ID_CHARS,
    )
    for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        _require_optional_counter(event.get(field_name), field_name)
    semantic_probe_match = event.get("semantic_probe_match")
    if semantic_probe_match is not None and not isinstance(semantic_probe_match, bool):
        raise NvidiaCanaryEvidenceError("terminal semantic probe result is invalid")


class NvidiaCanaryEvidenceStore:
    """Persist and validate local NVIDIA canary lifecycle evidence."""

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
    ) -> NvidiaCanaryEvidenceStore:
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

    def _canary_dir(self, canary_id: str) -> Path:
        return self.root / "canaries" / _require_canary_id(canary_id)

    def prepare(
        self,
        prepared_request: PreparedProviderRequest,
        *,
        probe_expected_text: str,
        qualified_predecessor_sha: str,
        prepared_at: str,
    ) -> NvidiaCanaryManifest:
        try:
            validate_prepared_provider_request_integrity(prepared_request)
            _require_aware_timestamp(prepared_at, "prepared_at")
            _require_digest(qualified_predecessor_sha, "qualified_predecessor_sha", _GIT_SHA1)
            if not isinstance(probe_expected_text, str) or not probe_expected_text:
                raise ValueError("probe_expected_text is invalid")
        except (TypeError, ValueError):
            raise NvidiaCanaryEvidenceError("prepared canary identity is invalid") from None

        if (
            prepared_request.provider_id != _NVIDIA_PROVIDER_ID
            or prepared_request.model_id != _NVIDIA_MODEL_ID
            or prepared_request.method != _NVIDIA_METHOD
            or prepared_request.target_origin != _NVIDIA_TARGET_ORIGIN
            or prepared_request.endpoint_path != _NVIDIA_ENDPOINT_PATH
        ):
            raise NvidiaCanaryEvidenceError("prepared canary target is invalid")

        self.root.mkdir(parents=True, exist_ok=True)
        canaries_root = self.root / "canaries"
        canaries_root.mkdir(parents=True, exist_ok=True)

        with _exclusive_lock(self.root / ".prepare.lock"):
            canary_dir: Path | None = None
            canary_id = ""
            for number in range(1, 1_000_000):
                candidate = f"NVC-{number:06d}"
                candidate_dir = canaries_root / candidate
                try:
                    candidate_dir.mkdir()
                except FileExistsError:
                    continue
                except OSError:
                    raise NvidiaCanaryEvidenceError("unable to allocate canary identity") from None
                canary_id = candidate
                canary_dir = candidate_dir
                break
            if canary_dir is None:
                raise NvidiaCanaryEvidenceError("no canary identity is available")

            manifest = NvidiaCanaryManifest(
                schema=NVIDIA_CANARY_SCHEMA,
                canary_id=canary_id,
                provider_id=prepared_request.provider_id,
                model_id=prepared_request.model_id,
                method=prepared_request.method,
                target_origin=prepared_request.target_origin,
                endpoint_path=prepared_request.endpoint_path,
                payload_sha256=prepared_request.payload_sha256,
                request_sha256=prepared_request.request_sha256,
                body_bytes=len(prepared_request.body_bytes),
                prepared_at=prepared_at,
                probe_expected_text=probe_expected_text,
                qualified_predecessor_sha=qualified_predecessor_sha,
            )
            _write_immutable(canary_dir / "request-body.bin", prepared_request.body_bytes)
            _write_immutable(canary_dir / "manifest.json", _canonical_json(asdict(manifest)))
            _append_event(
                canary_dir / "events.jsonl",
                {
                    "event_type": "CANARY_PREPARED",
                    "canary_id": canary_id,
                    "request_sha256": manifest.request_sha256,
                    "recorded_at": prepared_at,
                },
            )
            return manifest

    def load(self, canary_id: str) -> NvidiaCanarySnapshot:
        canary_dir = self._canary_dir(canary_id)
        try:
            manifest_text = (canary_dir / "manifest.json").read_text(encoding="utf-8")
            manifest_payload = json.loads(manifest_text)
            request_body = (canary_dir / "request-body.bin").read_bytes()
            event_bytes = (canary_dir / "events.jsonl").read_bytes()
            event_text = event_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise NvidiaCanaryEvidenceError("unable to read canary evidence") from None

        if not event_bytes.endswith(b"\n"):
            raise NvidiaCanaryEvidenceError("canary events are malformed")
        event_lines = event_text.splitlines()

        if not isinstance(manifest_payload, dict):
            raise NvidiaCanaryEvidenceError("canary manifest is malformed")
        try:
            manifest = NvidiaCanaryManifest(**manifest_payload)
        except (TypeError, ValueError):
            raise NvidiaCanaryEvidenceError("canary manifest is malformed") from None
        if manifest.canary_id != canary_id or len(request_body) != manifest.body_bytes:
            raise NvidiaCanaryEvidenceError("canary request identity is inconsistent")
        if hashlib.sha256(request_body).hexdigest() != manifest.payload_sha256:
            raise NvidiaCanaryEvidenceError("canary request body integrity failed")

        prepared = PreparedProviderRequest(
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
            validate_prepared_provider_request_integrity(prepared)
        except ValueError:
            raise NvidiaCanaryEvidenceError("canary request identity integrity failed") from None

        events: list[dict[str, object]] = []
        for line in event_lines:
            if not line:
                raise NvidiaCanaryEvidenceError("canary events are malformed")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                raise NvidiaCanaryEvidenceError("canary events are malformed") from None
            if not isinstance(event, dict):
                raise NvidiaCanaryEvidenceError("canary events are malformed")
            event_type = event.get("event_type")
            if event_type == "CANARY_TERMINAL":
                if set(event) != _TERMINAL_EVENT_KEYS:
                    raise NvidiaCanaryEvidenceError("canary terminal event is malformed")
            elif event_type in _ALLOWED_BASE_EVENTS:
                if set(event) != _BASE_EVENT_KEYS:
                    raise NvidiaCanaryEvidenceError("canary events are malformed")
            else:
                raise NvidiaCanaryEvidenceError("canary event type is invalid")
            if event.get("canary_id") != canary_id:
                raise NvidiaCanaryEvidenceError("canary event identity is invalid")
            if event.get("request_sha256") != manifest.request_sha256:
                raise NvidiaCanaryEvidenceError("canary event request identity is invalid")
            try:
                _require_aware_timestamp(event.get("recorded_at"), "recorded_at")
            except ValueError:
                raise NvidiaCanaryEvidenceError("canary event timestamp is invalid") from None
            events.append(event)

        if not events or events[0].get("event_type") != "CANARY_PREPARED":
            raise NvidiaCanaryEvidenceError("canary lifecycle is malformed")
        if events[0].get("recorded_at") != manifest.prepared_at:
            raise NvidiaCanaryEvidenceError("canary prepared timestamp is inconsistent")

        authorized_at: str | None = None
        provider_started_at: str | None = None
        terminal_event: dict[str, object] | None = None
        for index, event in enumerate(events[1:], start=1):
            if terminal_event is not None:
                raise NvidiaCanaryEvidenceError("event after canary terminal is invalid")
            event_type = event["event_type"]
            recorded_at = event["recorded_at"]
            if event_type == "CANARY_PREPARED":
                raise NvidiaCanaryEvidenceError("duplicate canary preparation event")
            if event_type == "CANARY_AUTHORIZED":
                if authorized_at is not None or provider_started_at is not None or index != 1:
                    raise NvidiaCanaryEvidenceError("canary authorization ordering is invalid")
                authorized_at = str(recorded_at)
                continue
            if event_type == "PROVIDER_START":
                if authorized_at is None or provider_started_at is not None:
                    raise NvidiaCanaryEvidenceError("provider-start ordering is invalid")
                if index != 2:
                    raise NvidiaCanaryEvidenceError("provider-start ordering is invalid")
                provider_started_at = str(recorded_at)
                continue
            if event_type == "CANARY_TERMINAL":
                if provider_started_at is None or index != 3:
                    raise NvidiaCanaryEvidenceError("canary terminal ordering is invalid")
                _validate_terminal_event(
                    event,
                    canary_id=canary_id,
                    manifest=manifest,
                    provider_started_at=provider_started_at,
                )
                terminal_event = event
                continue
            raise NvidiaCanaryEvidenceError("canary lifecycle is malformed")

        return NvidiaCanarySnapshot(
            manifest=manifest,
            request_body=request_body,
            events=tuple(events),
            authorized_at=authorized_at,
            provider_started_at=provider_started_at,
            terminal_event=terminal_event,
        )

    def append_authorized(
        self,
        canary_id: str,
        *,
        request_sha256: str,
        recorded_at: str,
    ) -> None:
        snapshot = self.load(canary_id)
        try:
            _require_aware_timestamp(recorded_at, "recorded_at")
        except ValueError:
            raise NvidiaCanaryEvidenceError("authorization timestamp is invalid") from None
        if request_sha256 != snapshot.manifest.request_sha256:
            raise NvidiaCanaryEvidenceError("authorization request identity is invalid")
        if snapshot.authorized_at is not None or snapshot.provider_started_at is not None:
            raise NvidiaCanaryEvidenceError("canary authorization already exists")
        _append_event(
            self._canary_dir(canary_id) / "events.jsonl",
            {
                "event_type": "CANARY_AUTHORIZED",
                "canary_id": canary_id,
                "request_sha256": request_sha256,
                "recorded_at": recorded_at,
            },
        )

    def append_provider_start(
        self,
        canary_id: str,
        *,
        request_sha256: str,
        recorded_at: str,
    ) -> None:
        snapshot = self.load(canary_id)
        try:
            _require_aware_timestamp(recorded_at, "recorded_at")
        except ValueError:
            raise NvidiaCanaryEvidenceError("provider-start timestamp is invalid") from None
        if request_sha256 != snapshot.manifest.request_sha256:
            raise NvidiaCanaryEvidenceError("provider-start request identity is invalid")
        if snapshot.authorized_at is None:
            raise NvidiaCanaryEvidenceError("canary is not authorized")
        if snapshot.provider_started_at is not None:
            raise NvidiaCanaryEvidenceError("provider-start already exists")
        _append_event(
            self._canary_dir(canary_id) / "events.jsonl",
            {
                "event_type": "PROVIDER_START",
                "canary_id": canary_id,
                "request_sha256": request_sha256,
                "recorded_at": recorded_at,
            },
        )

    def append_terminal(self, canary_id: str, event: Mapping[str, object]) -> None:
        if not isinstance(event, Mapping):
            raise NvidiaCanaryEvidenceError("canary terminal event is malformed")
        snapshot = self.load(canary_id)
        if snapshot.provider_started_at is None:
            raise NvidiaCanaryEvidenceError("canary terminal requires provider-start")
        if snapshot.terminal_event is not None:
            raise NvidiaCanaryEvidenceError("canary terminal already exists")
        terminal_event = dict(event)
        _validate_terminal_event(
            terminal_event,
            canary_id=canary_id,
            manifest=snapshot.manifest,
            provider_started_at=snapshot.provider_started_at,
        )
        _append_event(self._canary_dir(canary_id) / "events.jsonl", terminal_event)

    @contextmanager
    def transmit_lock(self, canary_id: str) -> Iterator[None]:
        canary_dir = self._canary_dir(canary_id)
        if not canary_dir.is_dir():
            raise NvidiaCanaryEvidenceError("canary evidence does not exist")
        with _exclusive_lock(canary_dir / ".transmit.lock"):
            yield
