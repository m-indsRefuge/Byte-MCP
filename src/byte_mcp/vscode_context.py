"""Bounded reader for VS Code editor-state telemetry."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .errors import LimitExceededError, NotFoundError, UnsupportedFileError
from .security import is_denied_relative, is_link_or_junction, resolve_under_root

MAX_SELECTION_CHARS = 12_000
MAX_STATE_BYTES = 1_000_000
STALE_AFTER_SECONDS = 600
_MAX_SCAN_DIRS = 5_000
_MAX_STATE_FILES = 64
_PRUNED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
    }
)


def _state_candidates(projects_root: Path) -> list[Path]:
    candidates: list[Path] = []
    visited = 0

    for current, dirnames, filenames in os.walk(projects_root, followlinks=False):
        visited += 1
        if visited > _MAX_SCAN_DIRS:
            break

        current_path = Path(current)
        kept: list[str] = []
        for name in dirnames:
            child = current_path / name
            relative = child.relative_to(projects_root)
            if name.casefold() in _PRUNED_DIRECTORY_NAMES:
                continue
            if is_denied_relative(relative) or is_link_or_junction(child):
                continue
            kept.append(name)
        dirnames[:] = kept

        if current_path.name != ".editor-state":
            continue

        dirnames[:] = []
        if "state.json" not in filenames:
            continue

        state_path = current_path / "state.json"
        if is_link_or_junction(state_path):
            continue
        candidates.append(state_path)
        if len(candidates) >= _MAX_STATE_FILES:
            break

    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return sorted(candidates, key=modified, reverse=True)


def _load_state(path: Path, max_state_bytes: int) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise NotFoundError("VS Code editor state cannot be inspected.") from exc

    if size > max_state_bytes:
        raise LimitExceededError(
            f"VS Code editor state is {size} bytes; limit is {max_state_bytes} bytes."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UnsupportedFileError("VS Code editor state is not valid UTF-8 JSON.") from exc

    if not isinstance(payload, dict):
        raise UnsupportedFileError("VS Code editor state must be a JSON object.")
    if payload.get("schemaVersion") != 1:
        raise UnsupportedFileError("Unsupported VS Code editor-state schema version.")

    extension = payload.get("extension")
    if not isinstance(extension, dict) or extension.get("name") != "editor-state-mcp":
        raise UnsupportedFileError("VS Code editor state has an unexpected producer.")

    return payload


def _same_relative_path(left: object, right: str) -> bool:
    if not isinstance(left, str):
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _bounded_selection(
    payload: dict[str, Any],
    active_relative: str,
    max_chars: int,
) -> dict[str, Any] | None:
    selected: dict[str, Any] | None = None
    source: str | None = None

    current = payload.get("selection")
    if isinstance(current, dict) and current.get("isEmpty") is False:
        selected = current
        source = "current"
    else:
        deliberate = payload.get("lastDeliberateSelection")
        if isinstance(deliberate, dict) and _same_relative_path(
            deliberate.get("relativePath"), active_relative
        ):
            selected = deliberate
            source = "last_deliberate"

    if selected is None or source is None:
        return None

    raw_text = selected.get("text", "")
    if not isinstance(raw_text, str):
        raise UnsupportedFileError("VS Code selection text must be a string.")
    truncated = len(raw_text) > max_chars

    return {
        "source": source,
        "start_line": selected.get("startLine"),
        "start_column": selected.get("startColumn"),
        "end_line": selected.get("endLine"),
        "end_column": selected.get("endColumn"),
        "line_count": selected.get("lineCount"),
        "text": raw_text[:max_chars],
        "text_truncated_by_byte_mcp": truncated,
        "text_truncated_by_extension": bool(selected.get("textTruncated", False)),
        "text_omitted_reason": selected.get("textOmittedReason"),
    }


def read_vscode_active_context(
    projects_root: Path,
    *,
    max_state_bytes: int = MAX_STATE_BYTES,
    max_selection_chars: int = MAX_SELECTION_CHARS,
) -> dict[str, Any]:
    """Return the freshest bounded editor context under the approved projects root."""
    try:
        resolved_projects = projects_root.resolve(strict=True)
    except OSError as exc:
        raise NotFoundError("Approved projects root cannot be resolved.") from exc

    candidates = _state_candidates(resolved_projects)
    if not candidates:
        raise NotFoundError("No VS Code editor state found under the approved projects root.")

    state_path = candidates[0]
    payload = _load_state(state_path, max_state_bytes)

    workspace_root = state_path.parent.parent
    workspace_relative = workspace_root.relative_to(resolved_projects).as_posix()
    workspace_root = resolve_under_root(
        resolved_projects,
        workspace_relative if workspace_relative else ".",
    )

    active = payload.get("activeEditor")
    if not isinstance(active, dict):
        raise UnsupportedFileError("VS Code editor state has no active editor object.")
    if active.get("scheme") != "file":
        raise UnsupportedFileError("VS Code active editor is not a local file.")

    active_relative = active.get("relativePath")
    if not isinstance(active_relative, str) or not active_relative:
        raise UnsupportedFileError("VS Code active editor has no relative path.")
    active_path = resolve_under_root(workspace_root, active_relative)
    if not active_path.is_file():
        raise NotFoundError("VS Code active editor path is not a file.")

    selection = _bounded_selection(
        payload,
        active_relative,
        max_selection_chars,
    )

    cursor_payload = payload.get("cursor")
    cursor = None
    if isinstance(cursor_payload, dict):
        cursor = {
            "line": cursor_payload.get("line"),
            "column": cursor_payload.get("column"),
        }

    window = payload.get("window")
    focused = bool(window.get("focused", False)) if isinstance(window, dict) else False

    workspace = payload.get("workspace")
    workspace_name = workspace_root.name
    if isinstance(workspace, dict):
        reported_name = workspace.get("name")
        if isinstance(reported_name, str) and reported_name:
            workspace_name = reported_name

    try:
        state_mtime = state_path.stat().st_mtime
    except OSError as exc:
        raise NotFoundError("VS Code editor state cannot be inspected.") from exc
    age_seconds = max(0.0, time.time() - state_mtime)

    return {
        "workspace": workspace_name,
        "workspace_relative_path": workspace_relative or ".",
        "active_file": Path(active_relative).as_posix(),
        "language": active.get("languageId"),
        "is_dirty": bool(active.get("isDirty", False)),
        "selection": selection,
        "cursor": cursor,
        "focused": focused,
        "updated_at": payload.get("updatedAt"),
        "age_seconds": round(age_seconds, 3),
        "stale": age_seconds > STALE_AFTER_SECONDS,
        "telemetry_relative_path": state_path.relative_to(resolved_projects).as_posix(),
    }
