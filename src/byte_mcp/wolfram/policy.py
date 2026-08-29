"""Outbound data policy for Wolfram provider calls."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from byte_mcp.errors import WolframPolicyError

_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:OPENAI_API_KEY|AI_GATEWAY_API_KEY|WOLFRAM_APP_ID|CONTROL_PLANE_API_KEY)\s*[:=]\s*\S+",
        r"\bAuthorization\s*:\s*Bearer\s+\S+",
        r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----",
        r"\b(?:password|pwd)\s*[:=]\s*[^\s;&]+",
        r"\b(?:sk-(?:proj-)?|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{16,}\b",
        r"\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@[^\s]+",
        r"[?&](?:password|pwd)=[^\s&#]+",
    )
)

_WINDOWS_DRIVE_PATH = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:[A-Z]:\\[^\s\"'<>|]+)")
_UNC_PATH = re.compile(r"(?<!\\)\\\\[^\s\\/]+\\[^\s\"'<>|]+")


@dataclass(frozen=True, slots=True)
class PreparedWolframInput:
    text: str
    sha256: str
    original_chars: int
    transmitted_chars: int
    paths_sanitized: int


class WolframOutboundPolicy:
    def __init__(self, max_input_chars: int, user_profile: Path | None = None) -> None:
        self.max_input_chars = max_input_chars
        self.user_profile = user_profile

    def prepare(self, input_text: str) -> PreparedWolframInput:
        if not isinstance(input_text, str):
            raise WolframPolicyError("Wolfram input must be text.")

        original_chars = len(input_text)
        normalized = input_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if "\x00" in normalized:
            raise WolframPolicyError("Wolfram input contains a forbidden NUL character.")
        if not normalized:
            raise WolframPolicyError("Wolfram input must not be blank.")
        if len(normalized) > self.max_input_chars:
            raise WolframPolicyError(
                f"Wolfram input exceeds the {self.max_input_chars}-character limit."
            )

        for pattern in _SECRET_PATTERNS:
            if pattern.search(normalized):
                raise WolframPolicyError("Wolfram input contains sensitive credential-like data.")

        sanitized, drive_count = _WINDOWS_DRIVE_PATH.subn("<local-path>", normalized)
        sanitized, unc_count = _UNC_PATH.subn("<local-path>", sanitized)
        digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        return PreparedWolframInput(
            text=sanitized,
            sha256=digest,
            original_chars=original_chars,
            transmitted_chars=len(sanitized),
            paths_sanitized=drive_count + unc_count,
        )
