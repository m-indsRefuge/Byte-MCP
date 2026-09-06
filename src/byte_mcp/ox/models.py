from dataclasses import dataclass
from enum import StrEnum

from byte_mcp.errors import OXTransportFailureKind


class OXAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    MISCONFIGURED = "MISCONFIGURED"


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
    total_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderTransportObservation:
    response_headers_received: bool
    response_headers_at: str | None
    response_headers_elapsed_ms: int | None
    http_status_code: int | None
    response_body_started: bool
    first_body_at: str | None
    first_body_elapsed_ms: int | None
    last_body_at: str | None
    last_body_elapsed_ms: int | None
    decoded_body_bytes_received: int
    provider_finished_at: str
    elapsed_ms: int
    transport_failure_kind: OXTransportFailureKind | None
    trust_env_enabled: bool
    proxy_environment_present: bool


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: str
    usage: ProviderUsage | None = None
    response_id: str | None = None
    model: str | None = None
    raw_response: dict[str, object] | None = None
    transport_observation: ProviderTransportObservation | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    status: FindingStatus
    summary: str = ""
    category: str = ""
    severity: str = ""
    confidence: float = 0.0
    location: str = ""
    claim: str = ""
    evidence: str = ""
    reproduction: str = ""
    expected_behavior: str = ""
    observed_or_predicted_behavior: str = ""
    disproof_condition: str = ""
    recommended_investigation: str = ""


@dataclass(frozen=True, slots=True)
class AdjudicationEvent:
    event_id: str
    finding_id: str
    status: FindingStatus
    rationale: str = ""
