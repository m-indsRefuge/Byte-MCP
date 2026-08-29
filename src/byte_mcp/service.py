"""Read-only local file service used by MCP tools."""
from __future__ import annotations

import hashlib
import os
import stat as stat_module
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .errors import (
    AccessDeniedError,
    ByteMCPError,
    LimitExceededError,
    NotFoundError,
    UnsupportedFileError,
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

    @contextmanager
    def _audit_failures(
        self,
        action: str,
        **fields: Any,
    ) -> Iterator[None]:
        try:
            yield
        except ByteMCPError as exc:
            self.audit.record(
                action,
                outcome="denied",
                error_type=type(exc).__name__,
                error=str(exc),
                **fields,
            )
            raise
        except Exception as exc:
            self.audit.record(
                action,
                outcome="error",
                error_type=type(exc).__name__,
                **fields,
            )
            raise

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

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

    @staticmethod
    def _directory_sort_key(path: Path) -> tuple[bool, str]:
        try:
            is_directory = path.is_dir()
        except OSError:
            is_directory = False
        return not is_directory, path.name.casefold()

    def _metadata(
        self,
        alias: str,
        path: Path,
    ) -> dict[str, Any]:
        path_stat = path.stat()
        relative = path.relative_to(
            self._root(alias)
        ).as_posix()

        return {
            "ref": encode_ref(alias, relative),
            "root": alias,
            "relative_path": relative,
            "name": path.name,
            "extension": path.suffix.casefold(),
            "size_bytes": path_stat.st_size,
            "modified_utc": self._timestamp(path_stat.st_mtime),
        }

    def list_roots(self) -> dict[str, Any]:
        with self._audit_failures("list_roots"):
            result = {
                "server": "Byte-MCP",
                "mode": "read-only",
                "endpoint": self.settings.mcp_url,
                "roots": [
                    {"alias": alias}
                    for alias in sorted(self.roots)
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
        audit_fields = {
            "root": root,
            "relative_path": relative_path,
            "requested_max_entries": max_entries,
        }

        with self._audit_failures(
            "list_directory",
            **audit_fields,
        ):
            bounded_max_entries = max(1, min(max_entries, 500))
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
            truncated = False
            children = sorted(
                directory.iterdir(),
                key=self._directory_sort_key,
            )

            for child in children:
                relative = child.relative_to(base)
                if (
                    is_denied_relative(relative)
                    or is_link_or_junction(child)
                ):
                    continue

                try:
                    child_stat = child.stat()
                except OSError:
                    continue

                if len(entries) >= bounded_max_entries:
                    truncated = True
                    break

                is_directory = stat_module.S_ISDIR(child_stat.st_mode)
                entries.append(
                    {
                        "name": child.name,
                        "kind": (
                            "directory"
                            if is_directory
                            else "file"
                        ),
                        "relative_path": relative.as_posix(),
                        "size_bytes": (
                            None
                            if is_directory
                            else child_stat.st_size
                        ),
                        "modified_utc": self._timestamp(
                            child_stat.st_mtime
                        ),
                    }
                )

            result = {
                "root": root,
                "relative_path": relative_path,
                "entries": entries,
                "truncated": truncated,
            }

        self.audit.record(
            "list_directory",
            returned=len(entries),
            **audit_fields,
        )
        return result

    def search(
        self,
        query: str,
        root: str | None = None,
        extension: str | None = None,
        max_results: int = 20,
        search_contents: bool = False,
    ) -> dict[str, Any]:
        query = query.strip()
        audit_fields = {
            "root": root or "*",
            "query_sha256": self._fingerprint(query),
            "query_length": len(query),
            "extension": extension,
            "requested_max_results": max_results,
            "content_search": search_contents,
        }

        with self._audit_failures(
            "search",
            **audit_fields,
        ):
            if not query:
                raise AccessDeniedError(
                    "Search query must not be empty."
                )

            bounded_max_results = max(1, min(max_results, 50))
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
            truncated = False
            stop_search = False

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
                        if scanned >= self.settings.max_search_files:
                            truncated = True
                            stop_search = True
                            break
                        scanned += 1

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
                                        max_input_bytes=(
                                            self.settings
                                            .content_search_max_bytes
                                        ),
                                    )
                                    matched = (
                                        query_folded
                                        in content.casefold()
                                    )
                            except Exception:
                                matched = False

                        if matched:
                            if len(results) >= bounded_max_results:
                                truncated = True
                                stop_search = True
                                break

                            try:
                                metadata = self._metadata(alias, path)
                            except OSError:
                                continue
                            results.append(metadata)

                    if stop_search:
                        break
                if stop_search:
                    break

            result = {
                "query": query,
                "results": results,
                "scanned_files": scanned,
                "truncated": truncated,
            }

        self.audit.record(
            "search",
            returned=len(results),
            scanned=scanned,
            **audit_fields,
        )
        return result

    def fetch(
        self,
        reference: str,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        audit_fields = {
            "reference_sha256": self._fingerprint(reference),
            "reference_length": len(reference),
            "requested_max_chars": max_chars,
        }

        with self._audit_failures(
            "fetch",
            **audit_fields,
        ):
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

            try:
                content, truncated, extractor = extract_file(
                    path,
                    bounded_chars,
                    max_input_bytes=self.settings.max_file_bytes,
                )
            except ByteMCPError:
                raise
            except Exception as exc:
                raise UnsupportedFileError(
                    f"Extraction failed for {path.name}: "
                    f"{type(exc).__name__}"
                ) from exc

            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(
                    lambda: handle.read(1024 * 1024),
                    b"",
                ):
                    digest.update(chunk)

            metadata = self._metadata(alias, path)
            sha256 = digest.hexdigest()
            result = {
                **metadata,
                "sha256": sha256,
                "extractor": extractor,
                "max_chars_applied": bounded_chars,
                "content": content,
                "content_truncated": truncated,
            }

        self.audit.record(
            "fetch",
            root=alias,
            relative_path=relative,
            size_bytes=size,
            sha256=sha256,
            extractor=extractor,
            **audit_fields,
        )
        return result
