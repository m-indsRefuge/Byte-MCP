"""Filesystem containment and secret-denial rules."""
from __future__ import annotations

from pathlib import Path

from .errors import AccessDeniedError

DENIED_NAMES = frozenset(
    {
        ".env",
        ".git",
        ".gnupg",
        ".ssh",
        "__pycache__",
        "appdata",
        "credentials",
        "credential",
        "secrets",
        "secret",
        "ntuser.dat",
    }
)
DENIED_SUFFIXES = frozenset(
    {
        ".key",
        ".pem",
        ".pfx",
        ".p12",
        ".kdbx",
        ".sqlite-wal",
        ".sqlite-shm",
    }
)


def is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


def is_denied_relative(relative_path: Path) -> bool:
    lowered_parts = {part.casefold() for part in relative_path.parts}
    if lowered_parts & DENIED_NAMES:
        return True

    name = relative_path.name.casefold()
    return name in DENIED_NAMES or any(
        name.endswith(suffix) for suffix in DENIED_SUFFIXES
    )


def resolve_under_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AccessDeniedError(
            "Only relative paths inside an approved root are allowed."
        )

    cursor = root
    for part in relative.parts:
        if part in ("", "."):
            continue
        cursor = cursor / part
        if cursor.exists() and is_link_or_junction(cursor):
            raise AccessDeniedError(
                "Symbolic links and junctions are not traversed."
            )

    candidate = (root / relative).resolve(strict=True)
    resolved_root = root.resolve(strict=True)

    try:
        normalized_relative = candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AccessDeniedError(
            "Resolved path escaped the approved root."
        ) from exc

    if is_denied_relative(normalized_relative):
        raise AccessDeniedError(
            "The requested path is blocked by the secret-denial policy."
        )

    return candidate
