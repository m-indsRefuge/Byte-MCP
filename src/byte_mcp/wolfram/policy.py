"""Outbound data policy for Wolfram requests."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from byte_mcp.errors import WolframPolicyError

_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:OPENAI_API_KEY|AI_GATEWAY_API_KEY|WOLFRAM_APP_ID|CONTROL_PLANE_API_KEY)\s*=",
        r"\bAuthorization\s*:\s*Bearer\s+\S+",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:password|passwd|pwd)\s*[=:]\s*[^\s;]+",
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s]+:[^\s]+@",
        r"\bsk-[A-Za-z0-9_-]{8,}",
        r"\bgh[pousr]_[A-Za-z0-9_]{8,}",
    )
)
_WINDOWS_ABSOLUTE = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:[A-Z]:\\[^\r\n\t\"'<>|]+)")


@dataclass(frozen=True, slots=True)
class PreparedWolframInput:
    text: str
    sha256: str
    original_chars: int
    transmitted_chars: int
    paths_sanitized: int


class WolframOutboundPolicy:
    def __init__(self, user_profile: Path | None = None, max_input_chars: int = 8_000) -> None:
        self.user_profile = user_profile
        self.max_input_chars = max_input_chars

    def prepare(self, input_text: str) -> PreparedWolframInput:
        if not isinstance(input_text, str):
            raise WolframPolicyError("Wolfram input must be text.")
        if "\x00" in input_text:
            raise WolframPolicyError("Wolfram input contains a prohibited NUL character.")

        normalized = input_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise WolframPolicyError("Wolfram input must not be blank.")
        if len(normalized) > self.max_input_chars:
            raise WolframPolicyError(
                f"Wolfram input exceeds the {self.max_input_chars}-character limit."
            )

        for pattern in _SECRET_PATTERNS:
            if pattern.search(normalized):
                raise WolframPolicyError("Wolfram input contains sensitive material.")

        sanitized, count = _WINDOWS_ABSOLUTE.subn("<local-path>", normalized)
        digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        return PreparedWolframInput(
            text=sanitized,
            sha256=digest,
            original_chars=len(normalized),
            transmitted_chars=len(sanitized),
            paths_sanitized=count,
        )
