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
    ordered = _order_operations(operations)
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


def _path_identity(path: str) -> str:
    return path.casefold()


def _path_sort_key(path: str) -> tuple[str, str]:
    return path.casefold(), path


def _validate_targets(operations: tuple[MutationOperation, ...]) -> None:
    targets: dict[str, str] = {}
    non_move_sources = {
        _path_identity(operation.path)
        for operation in operations
        if operation.kind is not OperationKind.MOVE and operation.path is not None
    }
    for operation in operations:
        for target in _target_paths(operation):
            key = _path_identity(target)
            if key in targets:
                raise WriteConflictError(
                    "mutation manifest contains an occupied planned destination"
                )
            if operation.kind is OperationKind.MOVE and key in non_move_sources:
                raise WriteConflictError(
                    "mutation manifest contains an occupied planned destination"
                )
            targets[key] = target


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


def _order_operations(
    operations: tuple[MutationOperation, ...],
) -> tuple[MutationOperation, ...]:
    create_directories = sorted(
        (operation for operation in operations if operation.kind is OperationKind.CREATE_DIRECTORY),
        key=lambda operation: (
            len(PurePosixPath(operation.path or "").parts),
            _path_sort_key(operation.path or ""),
        ),
    )
    file_operations = sorted(
        (
            operation
            for operation in operations
            if operation.kind
            in {
                OperationKind.CREATE_TEXT_FILE,
                OperationKind.REPLACE_TEXT_FILE,
                OperationKind.PATCH_TEXT_FILE,
            }
        ),
        key=lambda operation: _path_sort_key(operation.path or ""),
    )
    moves = _order_moves(
        tuple(operation for operation in operations if operation.kind is OperationKind.MOVE)
    )
    deletes = sorted(
        (operation for operation in operations if operation.kind is OperationKind.RECOVER_DELETE),
        key=lambda operation: _path_sort_key(operation.path or ""),
    )
    restores = sorted(
        (
            operation
            for operation in operations
            if operation.kind is OperationKind.RESTORE_RECOVERY_ITEM
        ),
        key=lambda operation: _path_sort_key(operation.destination or ""),
    )
    return tuple(create_directories + file_operations + list(moves) + deletes + restores)


def _order_moves(moves: tuple[MutationOperation, ...]) -> tuple[MutationOperation, ...]:
    if not moves:
        return ()

    by_source: dict[str, MutationOperation] = {}
    for operation in moves:
        if operation.path is None or operation.destination is None:
            raise WritePolicyError("move operation is missing a source or destination")
        source_key = _path_identity(operation.path)
        if source_key in by_source:
            raise WriteConflictError("mutation manifest contains a duplicate move source")
        by_source[source_key] = operation

    indegree = {source_key: 0 for source_key in by_source}
    dependents: dict[str, list[str]] = {source_key: [] for source_key in by_source}
    for source_key, operation in by_source.items():
        destination_key = _path_identity(operation.destination or "")
        if destination_key in by_source:
            indegree[source_key] += 1
            dependents[destination_key].append(source_key)

    ready = [source_key for source_key, degree in indegree.items() if degree == 0]
    ready.sort(key=lambda key: _move_sort_key(by_source[key]))
    ordered: list[MutationOperation] = []

    while ready:
        source_key = ready.pop(0)
        ordered.append(by_source[source_key])
        for dependent in sorted(
            dependents[source_key], key=lambda key: _move_sort_key(by_source[key])
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort(key=lambda key: _move_sort_key(by_source[key]))

    if len(ordered) != len(moves):
        raise WriteConflictError("move source and destination dependencies contain a cycle")
    return tuple(ordered)


def _move_sort_key(operation: MutationOperation) -> tuple[tuple[str, str], tuple[str, str]]:
    return _path_sort_key(operation.path or ""), _path_sort_key(operation.destination or "")


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
