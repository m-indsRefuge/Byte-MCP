"""Durable filesystem evidence and irreversible send authority for OX."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox.models import OXPreparedReview, OXReviewMode, OXReviewState
from byte_mcp.ox.settings import OX_REVIEW_ID_PREFIX
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity

_REVIEW_ID_RE = re.compile(r"^OX-(\d{6})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_SCHEMA = "ox-review-evidence-v1"
_SNAPSHOT_SCHEMA = "ox-snapshot-evidence-v1"
_APPROVED_ATTEMPT_OUTCOMES = frozenset(
    {"NOT_SENT", "REJECTED", "COMPLETED", "OUTCOME_UNKNOWN"}
)
_TERMINAL_METADATA_KEYS = frozenset(
    {
        "state",
        "provider_started_at",
        "provider_finished_at",
        "attempt_outcome",
        "response_bytes",
        "response_sha256",
        "review_text_bytes",
        "review_text_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class OXReviewEvidence:
    review_id: str
    state: OXReviewState
    repository: str
    mode: OXReviewMode
    snapshot_sha256: str
    request_sha256: str
    provider_started_at: str | None
    provider_finished_at: str | None
    attempt_outcome: str | None
    response_bytes: int | None
    review_text: str | None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OXEvidenceError("OX evidence metadata is invalid.") from exc


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise OXEvidenceError(f"OX evidence {field_name} is invalid.")
    return value


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise OXEvidenceError(f"OX evidence {field_name} is invalid.")
    return value


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, value: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OXEvidenceError("OX immutable evidence cannot be verified.") from exc
        if existing != value:
            raise OXEvidenceError("OX immutable evidence already exists with different bytes.")
        return
    except OSError as exc:
        raise OXEvidenceError("OX immutable evidence could not be created.") from exc

    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise OXEvidenceError("OX immutable evidence could not be persisted.") from exc
    _fsync_directory(path.parent)


def _write_atomic(path: Path, value: bytes) -> None:
    try:
        descriptor, raw_temp = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
    except OSError as exc:
        raise OXEvidenceError("OX evidence projection could not be staged.") from exc

    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise OXEvidenceError("OX evidence projection could not be persisted.") from exc


def _read_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OXEvidenceError("OX evidence metadata could not be read safely.") from exc
    if not isinstance(raw, dict):
        raise OXEvidenceError("OX evidence metadata is invalid.")
    return raw


def _snapshot_projection(prepared: OXPreparedReview) -> dict[str, object]:
    snapshot = prepared.snapshot
    return {
        "schema": _SNAPSHOT_SCHEMA,
        "review_id": prepared.review_id,
        "repository": snapshot.repository,
        "mode": snapshot.mode.value,
        "requested_paths": list(snapshot.requested_paths),
        "policy_version": snapshot.policy_version,
        "snapshot_sha256": snapshot.snapshot_sha256,
        "total_content_bytes": snapshot.total_content_bytes,
        "artifacts": [
            {
                "logical_path": artifact.logical_path,
                "byte_length": artifact.byte_length,
                "content_sha256": artifact.content_sha256,
                "classification": artifact.classification,
                "git_state": artifact.git_state,
            }
            for artifact in snapshot.artifacts
        ],
        "exclusions": [
            {"logical_path": exclusion.logical_path, "reason": exclusion.reason}
            for exclusion in snapshot.exclusions
        ],
    }


def _prepared_projection(prepared: OXPreparedReview) -> dict[str, object]:
    request = prepared.prepared_request
    return {
        "schema": _EVIDENCE_SCHEMA,
        "review_id": prepared.review_id,
        "state": OXReviewState.READY.value,
        "repository": prepared.scope.repository,
        "mode": prepared.scope.mode.value,
        "requested_paths": list(prepared.scope.paths),
        "snapshot_policy_version": prepared.snapshot.policy_version,
        "snapshot_sha256": prepared.snapshot.snapshot_sha256,
        "artifact_count": len(prepared.snapshot.artifacts),
        "exclusion_count": len(prepared.snapshot.exclusions),
        "snapshot_content_bytes": prepared.snapshot.total_content_bytes,
        "packet_sha256": prepared.packet_sha256,
        "request_payload_sha256": request.payload_sha256,
        "request_sha256": request.request_sha256,
        "provider_id": request.provider_id,
        "target_origin": request.target_origin,
        "endpoint_path": request.endpoint_path,
        "model_id": request.model_id,
        "provider_started_at": None,
        "provider_finished_at": None,
        "attempt_outcome": None,
        "response_bytes": None,
        "response_sha256": None,
        "review_text_bytes": None,
        "review_text_sha256": None,
    }


def _same_prepared_identity(existing: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    identity_fields = (
        "schema",
        "review_id",
        "repository",
        "mode",
        "requested_paths",
        "snapshot_policy_version",
        "snapshot_sha256",
        "artifact_count",
        "exclusion_count",
        "snapshot_content_bytes",
        "packet_sha256",
        "request_payload_sha256",
        "request_sha256",
        "provider_id",
        "target_origin",
        "endpoint_path",
        "model_id",
    )
    return all(existing.get(field) == expected.get(field) for field in identity_fields)


class OXEvidenceStore:
    """Filesystem-backed OX review evidence with fail-closed send authority."""

    def __init__(self, evidence_root: Path) -> None:
        if not isinstance(evidence_root, Path):
            raise OXEvidenceError("OX evidence root is invalid.")
        self._root = evidence_root
        self._reviews_root = self._root / "reviews"
        try:
            self._reviews_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OXEvidenceError("OX evidence root could not be created.") from exc

    def _directory(self, review_id: str) -> Path:
        if not isinstance(review_id, str) or _REVIEW_ID_RE.fullmatch(review_id) is None:
            raise OXEvidenceError("OX review ID is invalid.")
        directory = self._reviews_root / review_id
        if not directory.is_dir():
            raise OXEvidenceError("OX review evidence does not exist.")
        return directory

    def allocate_review_id(self) -> str:
        highest = 0
        try:
            entries = tuple(self._reviews_root.iterdir())
        except OSError as exc:
            raise OXEvidenceError("OX review IDs could not be enumerated.") from exc
        for entry in entries:
            match = _REVIEW_ID_RE.fullmatch(entry.name)
            if match is not None and entry.is_dir():
                highest = max(highest, int(match.group(1)))

        candidate = highest + 1
        while candidate <= 999_999:
            review_id = f"{OX_REVIEW_ID_PREFIX}{candidate:06d}"
            try:
                (self._reviews_root / review_id).mkdir(exist_ok=False)
            except FileExistsError:
                candidate += 1
                continue
            except OSError as exc:
                raise OXEvidenceError("OX review ID could not be allocated.") from exc
            _fsync_directory(self._reviews_root)
            return review_id
        raise OXEvidenceError("OX review ID space is exhausted.")

    def persist_prepared(self, prepared: OXPreparedReview) -> None:
        if not isinstance(prepared, OXPreparedReview):
            raise OXEvidenceError("OX prepared review is invalid.")
        try:
            validate_prepared_provider_request_integrity(prepared.prepared_request)
        except ValueError as exc:
            raise OXEvidenceError("OX prepared request integrity is invalid.") from exc

        directory = self._directory(prepared.review_id)
        snapshot_bytes = _canonical_json(_snapshot_projection(prepared))
        review_projection = _prepared_projection(prepared)

        _write_exclusive(directory / "snapshot.json", snapshot_bytes)
        _write_exclusive(directory / "packet.bin", prepared.packet_bytes)
        _write_exclusive(directory / "request.bin", prepared.prepared_request.body_bytes)

        review_path = directory / "review.json"
        if review_path.exists():
            existing = _read_json(review_path)
            if not _same_prepared_identity(existing, review_projection):
                raise OXEvidenceError("OX prepared evidence identity does not match existing review.")
            return
        _write_atomic(review_path, _canonical_json(review_projection))

    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool:
        directory = self._directory(review_id)
        claim_path = directory / "send.claim"
        if claim_path.exists():
            return False

        request_sha256 = _require_sha256(request_sha256, "request_sha256")
        claimed_at = _require_optional_text(claimed_at, "claimed_at")
        if claimed_at is None:
            raise OXEvidenceError("OX evidence claimed_at is invalid.")

        metadata = _read_json(directory / "review.json")
        if metadata.get("request_sha256") != request_sha256:
            raise OXEvidenceError("OX send claim request identity does not match prepared evidence.")
        for required_name in ("snapshot.json", "packet.bin", "request.bin"):
            if not (directory / required_name).is_file():
                raise OXEvidenceError("OX prepared evidence is incomplete.")

        packet_sha256 = _require_sha256(metadata.get("packet_sha256"), "packet_sha256")
        payload_sha256 = _require_sha256(
            metadata.get("request_payload_sha256"),
            "request_payload_sha256",
        )
        try:
            packet_bytes = (directory / "packet.bin").read_bytes()
            request_bytes = (directory / "request.bin").read_bytes()
        except OSError as exc:
            raise OXEvidenceError("OX prepared evidence could not be verified.") from exc
        if _sha256(packet_bytes) != packet_sha256 or _sha256(request_bytes) != payload_sha256:
            raise OXEvidenceError("OX prepared evidence integrity is invalid.")

        claim_bytes = _canonical_json(
            {"request_sha256": request_sha256, "claimed_at": claimed_at}
        )
        try:
            descriptor = os.open(
                claim_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            return False
        except OSError as exc:
            raise OXEvidenceError("OX send authority could not be claimed.") from exc

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(claim_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(directory)
        except OSError as exc:
            raise OXEvidenceError("OX send claim persistence is uncertain.") from exc
        return True

    def persist_response(self, review_id: str, body: bytes) -> None:
        if not isinstance(body, bytes):
            raise OXEvidenceError("OX response evidence is invalid.")
        directory = self._directory(review_id)
        _write_exclusive(directory / "response.bin", body)

    def persist_review_text(self, review_id: str, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise OXEvidenceError("OX review text is invalid.")
        try:
            encoded = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise OXEvidenceError("OX review text is not valid UTF-8.") from exc
        directory = self._directory(review_id)
        _write_exclusive(directory / "review.txt", encoded)

    def finalize(self, review_id: str, terminal_metadata: Mapping[str, object]) -> None:
        directory = self._directory(review_id)
        if not (directory / "send.claim").is_file():
            raise OXEvidenceError("OX review cannot finalize before send authority is consumed.")
        if not isinstance(terminal_metadata, Mapping):
            raise OXEvidenceError("OX terminal metadata is invalid.")
        if set(terminal_metadata) - _TERMINAL_METADATA_KEYS:
            raise OXEvidenceError("OX terminal metadata contains unsupported fields.")

        try:
            state = OXReviewState(terminal_metadata.get("state"))
        except (TypeError, ValueError) as exc:
            raise OXEvidenceError("OX terminal state is invalid.") from exc
        if state is OXReviewState.READY:
            raise OXEvidenceError("OX terminal state cannot be READY.")

        outcome = terminal_metadata.get("attempt_outcome")
        if not isinstance(outcome, str) or outcome not in _APPROVED_ATTEMPT_OUTCOMES:
            raise OXEvidenceError("OX attempt outcome is invalid.")
        if state is OXReviewState.COMPLETED and outcome != "COMPLETED":
            raise OXEvidenceError("OX completed evidence requires a completed attempt outcome.")

        claim = _read_json(directory / "send.claim")
        claim_started_at = _require_optional_text(claim.get("claimed_at"), "claimed_at")
        started_at = _require_optional_text(
            terminal_metadata.get("provider_started_at"),
            "provider_started_at",
        )
        finished_at = _require_optional_text(
            terminal_metadata.get("provider_finished_at"),
            "provider_finished_at",
        )
        if started_at is None:
            started_at = claim_started_at

        response_path = directory / "response.bin"
        review_text_path = directory / "review.txt"
        response = self._read_optional_bytes(response_path)
        review_text_bytes = self._read_optional_bytes(review_text_path)

        if state is OXReviewState.COMPLETED:
            if response is None or review_text_bytes is None:
                raise OXEvidenceError("OX completed evidence is incomplete.")
            try:
                review_text = review_text_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise OXEvidenceError("OX completed review text is invalid.") from exc
            if not review_text.strip():
                raise OXEvidenceError("OX completed review text is empty.")

        response_bytes = len(response) if response is not None else None
        response_sha256 = _sha256(response) if response is not None else None
        text_bytes = len(review_text_bytes) if review_text_bytes is not None else None
        text_sha256 = _sha256(review_text_bytes) if review_text_bytes is not None else None
        self._validate_optional_terminal_binding(
            terminal_metadata,
            "response_bytes",
            response_bytes,
        )
        self._validate_optional_terminal_binding(
            terminal_metadata,
            "response_sha256",
            response_sha256,
        )
        self._validate_optional_terminal_binding(
            terminal_metadata,
            "review_text_bytes",
            text_bytes,
        )
        self._validate_optional_terminal_binding(
            terminal_metadata,
            "review_text_sha256",
            text_sha256,
        )

        metadata = _read_json(directory / "review.json")
        metadata.update(
            {
                "state": state.value,
                "provider_started_at": started_at,
                "provider_finished_at": finished_at,
                "attempt_outcome": outcome,
                "response_bytes": response_bytes,
                "response_sha256": response_sha256,
                "review_text_bytes": text_bytes,
                "review_text_sha256": text_sha256,
            }
        )
        _write_atomic(directory / "review.json", _canonical_json(metadata))

    def get(self, review_id: str) -> OXReviewEvidence:
        directory = self._directory(review_id)
        metadata = _read_json(directory / "review.json")
        self._validate_core_metadata(review_id, metadata)

        try:
            mode = OXReviewMode(metadata["mode"])
            stored_state = OXReviewState(metadata["state"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OXEvidenceError("OX review projection is invalid.") from exc

        claim_path = directory / "send.claim"
        claim = _read_json(claim_path) if claim_path.is_file() else None
        response = self._read_optional_bytes(directory / "response.bin")
        actual_response_bytes = len(response) if response is not None else None

        if claim is None:
            state = OXReviewState.READY
            provider_started_at = None
        else:
            provider_started_at = _require_optional_text(
                metadata.get("provider_started_at"),
                "provider_started_at",
            )
            if provider_started_at is None:
                provider_started_at = _require_optional_text(
                    claim.get("claimed_at"),
                    "claimed_at",
                )
            state = stored_state
            if stored_state is OXReviewState.READY:
                state = OXReviewState.OUTCOME_UNKNOWN
            elif stored_state is OXReviewState.COMPLETED and not self._completion_is_trustworthy(
                directory,
                metadata,
                claim,
            ):
                state = OXReviewState.OUTCOME_UNKNOWN

        review_text = None
        if state is OXReviewState.COMPLETED:
            review_text_bytes = self._read_optional_bytes(directory / "review.txt")
            if review_text_bytes is None:
                state = OXReviewState.OUTCOME_UNKNOWN
            else:
                try:
                    review_text = review_text_bytes.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    state = OXReviewState.OUTCOME_UNKNOWN
                    review_text = None

        attempt_outcome = metadata.get("attempt_outcome")
        if attempt_outcome is not None and (
            not isinstance(attempt_outcome, str)
            or attempt_outcome not in _APPROVED_ATTEMPT_OUTCOMES
        ):
            raise OXEvidenceError("OX attempt outcome evidence is invalid.")

        finished_at = _require_optional_text(
            metadata.get("provider_finished_at"),
            "provider_finished_at",
        )
        return OXReviewEvidence(
            review_id=review_id,
            state=state,
            repository=str(metadata["repository"]),
            mode=mode,
            snapshot_sha256=str(metadata["snapshot_sha256"]),
            request_sha256=str(metadata["request_sha256"]),
            provider_started_at=provider_started_at,
            provider_finished_at=finished_at,
            attempt_outcome=attempt_outcome,
            response_bytes=actual_response_bytes,
            review_text=review_text,
        )

    @staticmethod
    def _read_optional_bytes(path: Path) -> bytes | None:
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError as exc:
            raise OXEvidenceError("OX evidence bytes could not be read safely.") from exc

    @staticmethod
    def _validate_optional_terminal_binding(
        terminal_metadata: Mapping[str, object],
        field_name: str,
        actual: object,
    ) -> None:
        if field_name in terminal_metadata and terminal_metadata[field_name] != actual:
            raise OXEvidenceError("OX terminal evidence binding does not match durable bytes.")

    @staticmethod
    def _validate_core_metadata(review_id: str, metadata: Mapping[str, object]) -> None:
        if metadata.get("schema") != _EVIDENCE_SCHEMA or metadata.get("review_id") != review_id:
            raise OXEvidenceError("OX review metadata identity is invalid.")
        repository = metadata.get("repository")
        if not isinstance(repository, str) or not repository:
            raise OXEvidenceError("OX review repository evidence is invalid.")
        _require_sha256(metadata.get("snapshot_sha256"), "snapshot_sha256")
        _require_sha256(metadata.get("request_sha256"), "request_sha256")
        _require_sha256(metadata.get("packet_sha256"), "packet_sha256")
        _require_sha256(metadata.get("request_payload_sha256"), "request_payload_sha256")

    def _completion_is_trustworthy(
        self,
        directory: Path,
        metadata: Mapping[str, object],
        claim: Mapping[str, object],
    ) -> bool:
        if metadata.get("attempt_outcome") != "COMPLETED":
            return False
        if claim.get("request_sha256") != metadata.get("request_sha256"):
            return False

        response = self._read_optional_bytes(directory / "response.bin")
        review_text = self._read_optional_bytes(directory / "review.txt")
        if response is None or review_text is None:
            return False
        try:
            decoded = review_text.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
        if not decoded.strip():
            return False
        if metadata.get("response_bytes") != len(response):
            return False
        if metadata.get("response_sha256") != _sha256(response):
            return False
        if metadata.get("review_text_bytes") != len(review_text):
            return False
        if metadata.get("review_text_sha256") != _sha256(review_text):
            return False

        packet = self._read_optional_bytes(directory / "packet.bin")
        request = self._read_optional_bytes(directory / "request.bin")
        if packet is None or request is None:
            return False
        if metadata.get("packet_sha256") != _sha256(packet):
            return False
        if metadata.get("request_payload_sha256") != _sha256(request):
            return False

        try:
            snapshot_metadata = _read_json(directory / "snapshot.json")
        except OXEvidenceError:
            return False
        return snapshot_metadata.get("snapshot_sha256") == metadata.get("snapshot_sha256")
