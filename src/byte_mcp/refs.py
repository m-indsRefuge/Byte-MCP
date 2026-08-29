"""Opaque, versioned file references returned by search results.

References are identifiers, not authentication tokens or a security boundary.
Every decoded root/path pair is revalidated by FileService against the approved
root and filesystem containment policy before any file is accessed.
"""
from __future__ import annotations

import base64
import json

from .errors import AccessDeniedError


def encode_ref(root_alias: str, relative_path: str) -> str:
    payload = json.dumps(
        {"v": 1, "root": root_alias, "path": relative_path},
        separators=(",", ":"),
    )
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


def decode_ref(reference: str) -> tuple[str, str]:
    try:
        padded = reference + "=" * (-len(reference) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded).decode("utf-8")
        )
    except Exception as exc:
        raise AccessDeniedError(
            "Invalid Byte-MCP file reference."
        ) from exc

    if (
        payload.get("v") != 1
        or not isinstance(payload.get("root"), str)
        or not isinstance(payload.get("path"), str)
    ):
        raise AccessDeniedError(
            "Invalid Byte-MCP file reference payload."
        )

    return payload["root"], payload["path"]
