"""Domain contracts for the bounded Wolfram capability."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WolframAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    MISCONFIGURED = "MISCONFIGURED"


class WolframPurpose(StrEnum):
    COENGINEERING = "COENGINEERING"
    FALLBACK_VALIDATION = "FALLBACK_VALIDATION"


class WolframRouteReason(StrEnum):
    DIRECT_COMPUTATION = "DIRECT_COMPUTATION"
    KNOWLEDGE_LOOKUP = "KNOWLEDGE_LOOKUP"
    VERIFY_BYTE_HYPOTHESIS = "VERIFY_BYTE_HYPOTHESIS"
    GENERATE_TEST_ORACLE = "GENERATE_TEST_ORACLE"
    SEARCH_COUNTEREXAMPLE = "SEARCH_COUNTEREXAMPLE"
    DEBUG_NUMERICAL_BEHAVIOR = "DEBUG_NUMERICAL_BEHAVIOR"
    CODE_COMPREHENSION = "CODE_COMPREHENSION"
    OX_FALLBACK = "OX_FALLBACK"
    OTHER_BOUNDED_REASON = "OTHER_BOUNDED_REASON"


@dataclass(frozen=True, slots=True)
class WolframQueryRequest:
    input: str
    max_chars: int | None = None
    purpose: WolframPurpose = WolframPurpose.COENGINEERING
    route_reason: WolframRouteReason = WolframRouteReason.OTHER_BOUNDED_REASON
    source_finding_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input, str) or not self.input.strip():
            raise ValueError("Wolfram query input must not be blank.")

        if self.route_reason is WolframRouteReason.OX_FALLBACK:
            if self.purpose is not WolframPurpose.FALLBACK_VALIDATION:
                raise ValueError("OX_FALLBACK requires FALLBACK_VALIDATION purpose.")
            if not isinstance(self.source_finding_id, str) or not self.source_finding_id.strip():
                raise ValueError("OX_FALLBACK requires a local source_finding_id.")
        elif self.source_finding_id is not None:
            raise ValueError("source_finding_id is allowed only for OX_FALLBACK.")


@dataclass(frozen=True, slots=True)
class WolframClientResult:
    text: str
    result_url: str | None
    response_chars: int
    response_at_limit: bool
