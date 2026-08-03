"""Read-only local file service used by MCP tools."""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .errors import (
    AccessDeniedError,
    LimitExceededError,
    NotFoundError,
)
from .extractors import SUPPORTED_EXTENSIONS, extract_file
from .refs import decode_ref, encode_ref
from .security import (
    is_denied_relative,
    is_link_or_junction,
    resolve_under_root,
)
from .settings import Settings, load_roots


class FileService:
    def __init__(
        self,
        settings: Settings,
        roots: dict[str, Path] | None = None,
    ) -> None:
        self.settings = settings
        self.roots = roots or load_roots(settings)
        self.audit = AuditLog(settings.audit_file)

    def _root(self, alias: str) -> Path:
        try:
            return self.roots[alias]
        except KeyError as exc:
            raise NotFoundError(
                f"Unknown approved root alias: {alias}"
            ) from exc

    @staticmethod
    def _timestamp(value: float) -> str:
        return datetime.fromtimestamp(
            value,
            tz=UTC,
        ).isoformat()

    def _metadata(
        self,
        alias: str,
        path: Path,
    ) -> dict[str, Any]:
        stat = path.stat()
        relative = path.relative_to(
            self._root(alias)
        ).as_posix()

        return {
            "ref": encode_ref(alias, relative),
            "root": alias,
            "relative_path": relative,
            "absolute_path": str(path),
            "name": path.name,
            "extension": path.suffix.casefold(),
            "size_bytes": stat.st_size,
            "modified_utc": self._timestamp(stat.st_mtime),
        }

    def list_roots(self) -> dict[str, Any]:
        result = {
            "server": "Byte-MCP",
            "mode": "read-only",
            "roots": [
                {
                    "alias": alias,
                    "path": str(path),
                }
                for alias, path in sorted(self.roots.items())
            ],
        }
        self.audit.record(
            "list_roots",
            root_count=len(self.roots),
        )
        return result

    def list_directory(
        self,
        root: str,
        relative_path: str = ".",
        max_entries: int = 200,
    ) -> dict[str, Any]:
        max_entries = max(1, min(max_entries, 500))
        base = self._root(root)
        directory = resolve_under_root(
            base,
            relative_path,
        )

        if not directory.is_dir():
            raise NotFoundError(
                "Requested path is not a directory."
            )

        entries: list[dict[str, Any]] = []
        children = sorted(
            directory.iterdir(),
            key=lambda item: (
                not item.is_dir(),
                item.name.casefold(),
            ),
        )

        for child in children:
            relative = child.relative_to(base)
            if (
                is_denied_relative(relative)
                or is_link_or_junction(child)
            ):
                continue

            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "kind": (
                        "directory"
                        if child.is_dir()
                        else "file"
                    ),
                    "relative_path": relative.as_posix(),
                    "size_bytes": (
                        None
                        if child.is_dir()
                        else stat.st_size
                    ),
                    "modified_utc": self._timestamp(
                        stat.st_mtime
                    ),
                }
            )

            if len(entries) >= max_entries:
                break

        self.audit.record(
            "list_directory",
            root=root,
            relative_path=relative_path,
            returned=len(entries),
        )
        return {
            "root": root,
            "relative_path": relative_path,
            "entries": entries,
            "truncated": len(entries) >= max_entries,
        }

    def search(
        self,
        query: str,
        root: str | None = None,
        extension: str | None = None,
        max_results: int = 20,
        search_contents: bool = False,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise AccessDeniedError(
                "Search query must not be empty."
            )

        max_results = max(1, min(max_results, 50))
        normalized_extension = None

        if extension:
            normalized_extension = extension.casefold()
            if not normalized_extension.startswith("."):
                normalized_extension = (
                    "." + normalized_extension
                )

        selected = (
            {root: self._root(root)}
            if root
            else self.roots
        )

        results: list[dict[str, Any]] = []
        scanned = 0
        query_folded = query.casefold()
        stopped = False

        for alias, approved_root in selected.items():
            for current, dirnames, filenames in os.walk(
                approved_root,
                followlinks=False,
            ):
                current_path = Path(current)
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not is_denied_relative(
                        (
                            current_path / name
                        ).relative_to(approved_root)
                    )
                    and not is_link_or_junction(
                        current_path / name
                    )
                ]

                for filename in filenames:
                    scanned += 1
                    if scanned > self.settings.max_search_files:
                        stopped = True
                        break

                    path = current_path / filename
                    relative = path.relative_to(approved_root)

                    if (
                        is_denied_relative(relative)
                        or is_link_or_junction(path)
                    ):
                        continue

                    if (
                        normalized_extension
                        and path.suffix.casefold()
                        != normalized_extension
                    ):
                        continue

                    matched = (
                        query_folded in filename.casefold()
                    )

                    if (
                        not matched
                        and search_contents
                        and path.suffix.casefold()
                        in SUPPORTED_EXTENSIONS
                    ):
                        try:
                            if (
                                path.stat().st_size
                                <= self.settings
                                .content_search_max_bytes
                            ):
                                content, _, _ = extract_file(
                                    path,
                                    200_000,
                                )
                                matched = (
                                    query_folded
                                    in content.casefold()
                                )
                        except (
                            OSError,
                            ValueError,
                            RuntimeError,
                        ):
                            matched = False

                    if matched:
                        results.append(
                            self._metadata(alias, path)
                        )
                        if len(results) >= max_results:
                            stopped = True
                            break

                if stopped:
                    break
            if stopped:
                break

        self.audit.record(
            "search",
            root=root or "*",
            query=query,
            returned=len(results),
            scanned=scanned,
            content_search=search_contents,
        )
        return {
            "query": query,
            "results": results,
            "scanned_files": scanned,
            "truncated": stopped,
        }

    def fetch(
        self,
        reference: str,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        alias, relative = decode_ref(reference)
        path = resolve_under_root(
            self._root(alias),
            relative,
        )

        if not path.is_file():
            raise NotFoundError(
                "Requested reference is not a file."
            )

        size = path.stat().st_size
        if size > self.settings.max_file_bytes:
            raise LimitExceededError(
                f"File is {size} bytes; V1 limit is "
                f"{self.settings.max_file_bytes} bytes."
            )

        bounded_chars = (
            self.settings.max_response_chars
            if max_chars is None
            else max(
                1_000,
                min(
                    max_chars,
                    self.settings.max_response_chars,
                ),
            )
        )

        content, truncated, extractor = extract_file(
            path,
            bounded_chars,
        )

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        metadata = self._metadata(alias, path)
        sha256 = digest.hexdigest()

        self.audit.record(
            "fetch",
            root=alias,
            relative_path=relative,
            size_bytes=size,
            sha256=sha256,
            extractor=extractor,
        )
        return {
            **metadata,
            "sha256": sha256,
            "extractor": extractor,
            "content": content,
            "content_truncated": truncated,
        }
