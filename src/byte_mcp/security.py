"""Filesystem containment and secret-denial rules."""
from __future__ import annotations

from pathlib import Path

from .errors import AccessDeniedError, NotFoundError

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
    try:
        if path.is_symlink():
            return True
        checker = getattr(path, "is_junction", None)
        return bool(checker and checker())
    except OSError:
        # If the entry vanishes or cannot be inspected, fail closed and let
        # directory/search callers skip it rather than trusting its type.
        return True


def _name_variants(name: str) -> set[str]:
    variants = {name}
    current = Path(name)
    while current.suffix:
        current = Path(current.stem)
        variants.add(current.name.casefold())
    return variants


def is_denied_relative(relative_path: Path) -> bool:
    lowered_parts = {part.casefold() for part in relative_path.parts}
    if lowered_parts & DENIED_NAMES:
        return True

    name = relative_path.name.casefold()
    if _name_variants(name) & DENIED_NAMES:
        return True

    suffixes = {suffix.casefold() for suffix in Path(name).suffixes}
    return bool(suffixes & DENIED_SUFFIXES)


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

    try:
        candidate = (root / relative).resolve(strict=True)
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise NotFoundError(
            f"Path cannot be resolved: {relative_path}"
        ) from exc

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
