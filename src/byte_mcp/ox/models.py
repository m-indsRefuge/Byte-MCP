from dataclasses import dataclass
from enum import StrEnum


class OXAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ReviewState(StrEnum):
    PREPARED = "PREPARED"
    TRANSMITTING = "TRANSMITTING"
    REVIEWED = "REVIEWED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    REVALIDATION_PREPARED = "REVALIDATION_PREPARED"
    REVALIDATION_TRANSMITTING = "REVALIDATION_TRANSMITTING"
    BLIND_REVALIDATED = "BLIND_REVALIDATED"
    REVALIDATED = "REVALIDATED"


class AttemptOutcome(StrEnum):
    NOT_SENT = "NOT_SENT"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class FindingStatus(StrEnum):
    RAISED = "RAISED"
    REPRODUCED = "REPRODUCED"
    CONFIRMED = "CONFIRMED"
    DISPROVED = "DISPROVED"
    DEFERRED = "DEFERRED"
    UNRESOLVED = "UNRESOLVED"
    REMEDIATED = "REMEDIATED"
    REVALIDATED = "REVALIDATED"


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    review_id: str
    state: ReviewState


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: str
    usage: ProviderUsage | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    status: FindingStatus
    summary: str = ""


@dataclass(frozen=True, slots=True)
class AdjudicationEvent:
    event_id: str
    finding_id: str
    status: FindingStatus
    rationale: str = ""
