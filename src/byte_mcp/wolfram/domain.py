"""Domain contracts for the Wolfram co-engineering capability."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from byte_mcp.errors import WolframRequestError


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
        if not self.input.strip():
            raise WolframRequestError("Wolfram input must not be blank.")
        if self.route_reason is WolframRouteReason.OX_FALLBACK:
            if self.purpose is not WolframPurpose.FALLBACK_VALIDATION:
                raise WolframRequestError(
                    "OX_FALLBACK requires purpose FALLBACK_VALIDATION."
                )
            if not self.source_finding_id or not self.source_finding_id.strip():
                raise WolframRequestError(
                    "OX_FALLBACK requires a local source_finding_id."
                )
        elif self.source_finding_id is not None:
            raise WolframRequestError(
                "source_finding_id is permitted only for OX_FALLBACK."
            )


@dataclass(frozen=True, slots=True)
class WolframClientResult:
    result: str
    result_url: str | None
    response_chars: int
    response_at_limit: bool


@dataclass(frozen=True, slots=True)
class WolframQueryResult:
    status: str
    provider: str
    purpose: WolframPurpose
    route_reason: WolframRouteReason
    result: str
    result_url: str | None
    response_chars: int
    response_at_limit: bool
    local_period_utc: str
    local_period_count: int
    soft_limit: int
