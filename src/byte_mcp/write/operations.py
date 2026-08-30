"""Explicit, validated request contracts for Write V1 operations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors import WriteLimitError, WritePatchError, WritePolicyError
from .policy import WritePolicy

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_ID_RE = re.compile(r"^RCV-[0-9a-f]{16,64}$")


class OperationKind(StrEnum):
    """The complete, non-inferred Write V1 operation vocabulary."""

    CREATE_DIRECTORY = "create_directory"
    CREATE_TEXT_FILE = "create_text_file"
    REPLACE_TEXT_FILE = "replace_text_file"
    PATCH_TEXT_FILE = "patch_text_file"
    MOVE = "move"
    RECOVER_DELETE = "recover_delete"
    RESTORE_RECOVERY_ITEM = "restore_recovery_item"


@dataclass(frozen=True, slots=True)
class TextEdit:
    expected_text: str
    replacement_text: str

    def __post_init__(self) -> None:
        _validate_text(self.expected_text, "expected_text", allow_empty=False)
        _validate_text(self.replacement_text, "replacement_text", allow_empty=True)


@dataclass(frozen=True, slots=True)
class MutationOperation:
    """One fully specified mutation request, with irrelevant fields absent."""

    kind: OperationKind
    path: str | None = None
    destination: str | None = None
    content: str | None = None
    expected_sha256: str | None = None
    edits: tuple[TextEdit, ...] = ()
    recovery_id: str | None = None


_FIELDS_BY_KIND: dict[OperationKind, frozenset[str]] = {
    OperationKind.CREATE_DIRECTORY: frozenset({"kind", "path"}),
    OperationKind.CREATE_TEXT_FILE: frozenset({"kind", "path", "content"}),
    OperationKind.REPLACE_TEXT_FILE: frozenset({"kind", "path", "content", "expected_sha256"}),
    OperationKind.PATCH_TEXT_FILE: frozenset({"kind", "path", "expected_sha256", "edits"}),
    OperationKind.MOVE: frozenset({"kind", "path", "destination"}),
    OperationKind.RECOVER_DELETE: frozenset({"kind", "path"}),
    OperationKind.RESTORE_RECOVERY_ITEM: frozenset({"kind", "recovery_id", "destination"}),
}
_OPTIONAL_FIELDS_BY_KIND: dict[OperationKind, frozenset[str]] = {
    OperationKind.MOVE: frozenset({"expected_sha256"}),
    OperationKind.RECOVER_DELETE: frozenset({"expected_sha256"}),
}


def parse_operation(
    payload: Mapping[str, Any], policy: WritePolicy | None = None
) -> MutationOperation:
    """Parse an exact-shape operation request without inferring missing intent."""
    if not isinstance(payload, Mapping) or not all(isinstance(key, str) for key in payload):
        raise WritePolicyError("mutation operation must be an object with string keys")
    try:
        kind = OperationKind(payload.get("kind"))
    except (TypeError, ValueError) as exc:
        raise WritePolicyError("mutation operation kind is unsupported") from exc
    fields = set(payload)
    required_fields = _FIELDS_BY_KIND[kind]
    allowed_fields = required_fields | _OPTIONAL_FIELDS_BY_KIND.get(kind, frozenset())
    if not required_fields <= fields or not fields <= allowed_fields:
        raise WritePolicyError("mutation operation fields do not match its explicit kind")

    path = _required_path(payload, "path") if "path" in payload else None
    destination = _required_path(payload, "destination") if "destination" in payload else None
    content = _required_text(payload, "content") if "content" in payload else None
    expected_sha256 = _required_sha256(payload) if "expected_sha256" in payload else None
    recovery_id = _required_recovery_id(payload) if "recovery_id" in payload else None
    edits = _required_edits(payload, policy) if "edits" in payload else ()

    if (
        policy is not None
        and content is not None
        and len(content.encode("utf-8")) > policy.max_file_bytes
    ):
        raise WriteLimitError("text file content exceeds the policy max_file_bytes limit")
    return MutationOperation(kind, path, destination, content, expected_sha256, edits, recovery_id)


def apply_text_edits(source: str, edits: tuple[TextEdit, ...]) -> str:
    """Apply exact-once non-overlapping text edits from right to left."""
    _validate_text(source, "source", allow_empty=True)
    if not edits:
        raise WritePatchError("patch operations require at least one edit")
    matches: list[tuple[int, int, TextEdit]] = []
    for edit in edits:
        if not isinstance(edit, TextEdit):
            raise WritePatchError("patch edits must be TextEdit values")
        first = source.find(edit.expected_text)
        if first < 0 or source.find(edit.expected_text, first + 1) >= 0:
            raise WritePatchError("each expected patch fragment must occur exactly once")
        matches.append((first, first + len(edit.expected_text), edit))
    matches.sort(key=lambda match: match[0])
    for index in range(len(matches) - 1):
        previous, current = matches[index], matches[index + 1]
        if current[0] < previous[1]:
            raise WritePatchError("patch fragment matches must not overlap")
    result = source
    for start, end, edit in reversed(matches):
        result = result[:start] + edit.replacement_text + result[end:]
    return result


def _required_path(payload: Mapping[str, Any], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WritePolicyError(f"{name} must be a non-empty NUL-free path")
    return value


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload[name]
    _validate_text(value, name, allow_empty=True)
    return value


def _validate_text(value: object, name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, str) or (not allow_empty and not value) or "\x00" in value:
        raise WritePolicyError(
            f"{name} must be {'non-empty ' if not allow_empty else ''}NUL-free text"
        )


def _required_sha256(payload: Mapping[str, Any]) -> str:
    value = payload["expected_sha256"]
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise WritePolicyError("expected_sha256 must be a lowercase SHA-256 hex digest")
    return value


def _required_recovery_id(payload: Mapping[str, Any]) -> str:
    value = payload["recovery_id"]
    if not isinstance(value, str) or _RECOVERY_ID_RE.fullmatch(value) is None:
        raise WritePolicyError("recovery_id must be a well-formed RCV identifier")
    return value


def _required_edits(payload: Mapping[str, Any], policy: WritePolicy | None) -> tuple[TextEdit, ...]:
    raw_edits = payload["edits"]
    if not isinstance(raw_edits, list) or not raw_edits:
        raise WritePolicyError("patch_text_file requires a non-empty edits list")
    edits: list[TextEdit] = []
    patch_bytes = 0
    for raw_edit in raw_edits:
        if not isinstance(raw_edit, Mapping) or set(raw_edit) != {
            "expected_text",
            "replacement_text",
        }:
            raise WritePolicyError(
                "each patch edit must contain exactly expected_text and replacement_text"
            )
        edit = TextEdit(raw_edit["expected_text"], raw_edit["replacement_text"])
        patch_bytes += len(edit.expected_text.encode("utf-8")) + len(
            edit.replacement_text.encode("utf-8")
        )
        edits.append(edit)
    if policy is not None and patch_bytes > policy.max_patch_bytes:
        raise WriteLimitError("patch input exceeds the policy max_patch_bytes limit")
    return tuple(edits)
