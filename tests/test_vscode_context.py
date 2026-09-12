import json
import os
import time
from pathlib import Path

import pytest

from byte_mcp.errors import AccessDeniedError, NotFoundError
from byte_mcp.service import FileService
from byte_mcp.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=60_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
    )


def write_editor_state(
    workspace: Path,
    *,
    active_file: str,
    selection_text: str = "selected text",
    current_selection_empty: bool = False,
    deliberate_file: str | None = None,
    deliberate_text: str | None = None,
    focused: bool = True,
    mtime: float | None = None,
) -> Path:
    source_file = workspace / active_file
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("content\n", encoding="utf-8")

    state_dir = workspace / ".editor-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state.json"
    timestamp = time.time() if mtime is None else mtime
    deliberate_relative = deliberate_file or active_file
    deliberate_value = selection_text if deliberate_text is None else deliberate_text
    payload = {
        "schemaVersion": 1,
        "updatedAt": "2026-09-12T18:43:34.000Z",
        "updatedAtMs": int(timestamp * 1000),
        "extension": {
            "name": "editor-state-mcp",
            "version": "0.1.4",
        },
        "window": {
            "focused": focused,
        },
        "workspace": {
            "name": workspace.name,
            "folders": [str(workspace)],
        },
        "activeEditor": {
            "path": str(source_file),
            "relativePath": active_file,
            "scheme": "file",
            "languageId": "python",
            "isDirty": False,
            "lineCount": 100,
        },
        "selection": {
            "isEmpty": current_selection_empty,
            "startLine": 5,
            "startColumn": 1,
            "endLine": 7,
            "endColumn": 4,
            "lineCount": 3,
            "text": "" if current_selection_empty else selection_text,
            "textTruncated": False,
            "textOmittedReason": None,
        },
        "lastDeliberateSelection": {
            "relativePath": deliberate_relative,
            "capturedAtMs": int(timestamp * 1000),
            "startLine": 10,
            "startColumn": 1,
            "endLine": 12,
            "endColumn": 4,
            "lineCount": 3,
            "text": deliberate_value,
        },
        "cursor": {
            "line": 7,
            "column": 4,
        },
    }
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(state_path, (timestamp, timestamp))
    return state_path


def test_vscode_active_context_returns_freshest_workspace_and_selection(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    older = projects / "older-project"
    newer = projects / "newer-project"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    now = time.time()
    write_editor_state(
        older,
        active_file="src/old.py",
        selection_text="older selection",
        mtime=now - 30,
    )
    write_editor_state(
        newer,
        active_file="src/current.py",
        selection_text="fresh selection",
        focused=False,
        mtime=now,
    )
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    result = service.vscode_active_context()

    assert result["workspace"] == "newer-project"
    assert result["workspace_relative_path"] == "newer-project"
    assert result["active_file"] == "src/current.py"
    assert result["language"] == "python"
    assert result["focused"] is False
    assert result["selection"]["source"] == "current"
    assert result["selection"]["text"] == "fresh selection"
    assert result["cursor"] == {"line": 7, "column": 4}
    assert result["stale"] is False


def test_vscode_active_context_preserves_last_deliberate_selection_after_focus_loss(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    workspace = projects / "byte-mcp"
    workspace.mkdir(parents=True)
    write_editor_state(
        workspace,
        active_file="src/byte_mcp/security.py",
        current_selection_empty=True,
        deliberate_text="def is_link_or_junction(path: Path) -> bool:",
        focused=False,
    )
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    result = service.vscode_active_context()

    assert result["selection"]["source"] == "last_deliberate"
    assert result["selection"]["start_line"] == 10
    assert result["selection"]["end_line"] == 12
    assert result["selection"]["text"] == "def is_link_or_junction(path: Path) -> bool:"


def test_vscode_active_context_does_not_reuse_deliberate_selection_from_other_file(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    workspace = projects / "byte-mcp"
    workspace.mkdir(parents=True)
    write_editor_state(
        workspace,
        active_file="README.md",
        current_selection_empty=True,
        deliberate_file="src/byte_mcp/security.py",
        deliberate_text="unrelated old selection",
    )
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    result = service.vscode_active_context()

    assert result["selection"] is None


def test_vscode_active_context_rejects_active_file_escape(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    workspace = projects / "byte-mcp"
    workspace.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    state_path = write_editor_state(
        workspace,
        active_file="README.md",
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["activeEditor"]["relativePath"] = "../../outside.py"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    with pytest.raises(AccessDeniedError):
        service.vscode_active_context()


def test_vscode_active_context_bounds_selected_text(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    workspace = projects / "byte-mcp"
    workspace.mkdir(parents=True)
    write_editor_state(
        workspace,
        active_file="src/large.py",
        selection_text="x" * 20_000,
    )
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    result = service.vscode_active_context()

    assert len(result["selection"]["text"]) == 12_000
    assert result["selection"]["text_truncated_by_byte_mcp"] is True


def test_vscode_active_context_marks_old_telemetry_stale(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    workspace = projects / "byte-mcp"
    workspace.mkdir(parents=True)
    write_editor_state(
        workspace,
        active_file="README.md",
        mtime=time.time() - 601,
    )
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    result = service.vscode_active_context()

    assert result["stale"] is True
    assert result["age_seconds"] >= 600


def test_vscode_active_context_requires_editor_state(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    service = FileService(
        make_settings(tmp_path),
        {"projects": projects.resolve()},
    )

    with pytest.raises(NotFoundError, match="VS Code editor state"):
        service.vscode_active_context()
