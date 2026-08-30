"""Whole-request validation and canonical ordering for Write V1 manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..errors import WriteConflictError, WriteLimitError, WritePolicyError
from .operations import MutationOperation, OperationKind
from .policy import WritePolicy


@dataclass(frozen=True, slots=True)
class MutationManifest:
    project: str
    ordered_operations: tuple[MutationOperation, ...]
    manifest_sha256: str


def build_manifest(
    operations: tuple[MutationOperation, ...], policy: WritePolicy
) -> MutationManifest:
    """Validate a bounded single-project request and return its deterministic order."""
    if not operations:
        raise WritePolicyError("a mutation manifest requires at least one operation")
    if len(operations) > policy.max_operations:
        raise WriteLimitError("mutation manifest exceeds the policy max_operations limit")
    if not all(isinstance(operation, MutationOperation) for operation in operations):
        raise WritePolicyError("mutation manifest contains an invalid operation")

    projects = {_project_for(operation) for operation in operations}
    if len(projects) != 1:
        raise WritePolicyError("a mutation manifest must affect exactly one top-level project")
    project = projects.pop()
    _validate_cross_project_moves(operations, project)
    _validate_targets(operations)
    _validate_delete_parents(operations)
    _validate_created_file_parents(operations, project)
    _validate_move_cycles(operations)
    ordered = tuple(sorted(operations, key=_order_key))
    canonical = json.dumps(
        _canonical_operations(ordered), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return MutationManifest(project, ordered, hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def _project_for(operation: MutationOperation) -> str:
    path = operation.path or operation.destination
    if path is None:
        raise WritePolicyError("operation does not identify a project-scoped path")
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != "projects":
        raise WritePolicyError("operation paths must be rooted beneath projects/<project>")
    return parts[1]


def _validate_cross_project_moves(operations: tuple[MutationOperation, ...], project: str) -> None:
    for operation in operations:
        if operation.kind is OperationKind.MOVE and _project_for(
            operation
        ) != _project_for_destination(operation):
            raise WritePolicyError("cross-project moves are denied")
        if _project_for(operation) != project:
            raise WritePolicyError("a mutation manifest must affect exactly one top-level project")


def _project_for_destination(operation: MutationOperation) -> str:
    if operation.destination is None:
        raise WritePolicyError("operation is missing a destination")
    parts = PurePosixPath(operation.destination).parts
    if len(parts) < 2 or parts[0] != "projects":
        raise WritePolicyError("operation paths must be rooted beneath projects/<project>")
    return parts[1]


def _target_paths(operation: MutationOperation) -> tuple[str, ...]:
    if operation.kind is OperationKind.MOVE:
        return (operation.destination,) if operation.destination is not None else ()
    if operation.kind is OperationKind.RESTORE_RECOVERY_ITEM:
        return (operation.destination,) if operation.destination is not None else ()
    return (operation.path,) if operation.path is not None else ()


def _validate_targets(operations: tuple[MutationOperation, ...]) -> None:
    targets: set[str] = set()
    source_paths = {operation.path for operation in operations if operation.path is not None}
    for operation in operations:
        for target in _target_paths(operation):
            if target is None:
                continue
            if target in targets or (
                operation.kind is OperationKind.MOVE and target in source_paths
            ):
                raise WriteConflictError(
                    "mutation manifest contains an occupied planned destination"
                )
            targets.add(target)


def _validate_delete_parents(operations: tuple[MutationOperation, ...]) -> None:
    deleted = [
        operation.path for operation in operations if operation.kind is OperationKind.RECOVER_DELETE
    ]
    for parent in deleted:
        if parent is None:
            continue
        prefix = parent.rstrip("/") + "/"
        for operation in operations:
            if operation.path is not None and operation.path.startswith(prefix):
                raise WriteConflictError(
                    "a deleted parent cannot have a child mutation in the same manifest"
                )
            if operation.destination is not None and operation.destination.startswith(prefix):
                raise WriteConflictError(
                    "a deleted parent cannot have a child mutation in the same manifest"
                )


def _validate_created_file_parents(operations: tuple[MutationOperation, ...], project: str) -> None:
    created_directories = {
        operation.path
        for operation in operations
        if operation.kind is OperationKind.CREATE_DIRECTORY
    }
    project_root = f"projects/{project}"
    for operation in operations:
        if operation.kind is not OperationKind.CREATE_TEXT_FILE or operation.path is None:
            continue
        parent = str(PurePosixPath(operation.path).parent)
        if parent != project_root and parent not in created_directories:
            raise WriteConflictError(
                "a created file's missing parent must be a create_directory operation"
            )


def _validate_move_cycles(operations: tuple[MutationOperation, ...]) -> None:
    moves = {
        operation.path: operation.destination
        for operation in operations
        if operation.kind is OperationKind.MOVE
        and operation.path is not None
        and operation.destination is not None
    }
    for source in moves:
        seen: set[str] = set()
        cursor = source
        while cursor in moves:
            if cursor in seen:
                raise WriteConflictError("move source and destination dependencies contain a cycle")
            seen.add(cursor)
            cursor = moves[cursor]


def _order_key(operation: MutationOperation) -> tuple[int, int, str]:
    path = operation.path or operation.destination or ""
    depth = len(PurePosixPath(path).parts)
    kind_order = {
        OperationKind.CREATE_DIRECTORY: 0,
        OperationKind.CREATE_TEXT_FILE: 1,
        OperationKind.REPLACE_TEXT_FILE: 1,
        OperationKind.PATCH_TEXT_FILE: 1,
        OperationKind.MOVE: 2,
        OperationKind.RECOVER_DELETE: 3,
        OperationKind.RESTORE_RECOVERY_ITEM: 4,
    }[operation.kind]
    return kind_order, depth if kind_order == 0 else 0, path


def _canonical_operations(operations: tuple[MutationOperation, ...]) -> list[dict[str, object]]:
    return [
        {
            "kind": operation.kind.value,
            "path": operation.path,
            "destination": operation.destination,
            "content": operation.content,
            "expected_sha256": operation.expected_sha256,
            "edits": [
                {"expected_text": edit.expected_text, "replacement_text": edit.replacement_text}
                for edit in operation.edits
            ],
            "recovery_id": operation.recovery_id,
        }
        for operation in operations
    ]
