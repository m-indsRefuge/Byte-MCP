"""Domain errors for Byte-MCP."""

from enum import StrEnum


class ByteMCPError(Exception):
    """Base error for expected Byte-MCP failures."""


class AuditError(ByteMCPError):
    """Raised when the configured audit trail cannot be persisted."""


class AccessDeniedError(ByteMCPError):
    """Raised when a path or file is outside the approved security contract."""


class NotFoundError(ByteMCPError):
    """Raised when a requested root or file cannot be found."""


class UnsupportedFileError(ByteMCPError):
    """Raised when no safe extractor is registered for a file type."""


class LimitExceededError(ByteMCPError):
    """Raised when a request exceeds a configured safety limit."""


class WolframError(ByteMCPError):
    """Base error for expected Wolfram capability failures."""


class WolframUnavailableError(WolframError):
    """Raised when the Wolfram capability is disabled or unavailable."""


class WolframConfigurationError(WolframError):
    """Raised when Wolfram configuration is invalid."""


class WolframPolicyError(WolframError):
    """Raised when outbound content violates the Wolfram data policy."""


class WolframQuotaError(WolframError):
    """Raised when the local conservative Wolfram budget is exhausted."""


class WolframAuthenticationError(WolframError):
    """Raised when Wolfram rejects the AppID."""


class WolframRequestError(WolframError):
    """Raised when the request itself is invalid."""


class WolframUninterpretableError(WolframError):
    """Raised when Wolfram cannot interpret the input."""


class WolframRateLimitError(WolframError):
    """Raised when Wolfram rate-limits the request."""


class WolframTimeoutError(WolframError):
    """Raised on a bounded provider timeout."""


class WolframTransportError(WolframError):
    """Raised for DNS, TLS, connection, or transport failures."""


class WolframProviderError(WolframError):
    """Raised for Wolfram provider/server failures."""


class WolframProtocolError(WolframError):
    """Raised for malformed or unusable provider responses."""


class OXUnavailableError(ByteMCPError):
    pass


class OXConfigurationError(ByteMCPError):
    pass


class OXApprovalError(ByteMCPError):
    pass


class OXRepositoryError(ByteMCPError):
    pass


class OXScopeError(ByteMCPError):
    pass


class OXBundleError(ByteMCPError):
    pass


class OXEvidenceError(ByteMCPError):
    pass


class _ProviderCallError(ByteMCPError):
    _APPROVED_OUTCOMES = frozenset({"NOT_SENT", "REJECTED", "COMPLETED", "OUTCOME_UNKNOWN"})

    def __init__(self, *, attempt_outcome: str = "OUTCOME_UNKNOWN"):
        if attempt_outcome not in self._APPROVED_OUTCOMES:
            raise ValueError("attempt_outcome must use an approved outcome")
        self.attempt_outcome = attempt_outcome
        super().__init__()


class OXAuthenticationError(_ProviderCallError):
    pass


class OXPermissionError(_ProviderCallError):
    pass


class OXRequestError(_ProviderCallError):
    pass


class OXContextLimitError(_ProviderCallError):
    pass


class OXRateLimitError(_ProviderCallError):
    pass


class OXQuotaError(_ProviderCallError):
    pass


class OXProviderUnavailableError(_ProviderCallError):
    pass


class OXTransportFailureKind(StrEnum):
    ABSOLUTE_DEADLINE = "ABSOLUTE_DEADLINE"
    READ_TIMEOUT = "READ_TIMEOUT"
    READ_ERROR = "READ_ERROR"
    WRITE_TIMEOUT = "WRITE_TIMEOUT"
    WRITE_ERROR = "WRITE_ERROR"
    REMOTE_PROTOCOL_ERROR = "REMOTE_PROTOCOL_ERROR"
    HTTP_TRANSPORT_ERROR = "HTTP_TRANSPORT_ERROR"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    CONNECT_ERROR = "CONNECT_ERROR"
    POOL_TIMEOUT = "POOL_TIMEOUT"


class OXTransportError(_ProviderCallError):
    def __init__(
        self,
        *,
        attempt_outcome: str = "OUTCOME_UNKNOWN",
        transport_failure_kind: OXTransportFailureKind | None = None,
        provider_started_at: str | None = None,
        provider_finished_at: str | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        self.transport_failure_kind = transport_failure_kind
        self.provider_started_at = provider_started_at
        self.provider_finished_at = provider_finished_at
        self.elapsed_ms = elapsed_ms
        super().__init__(attempt_outcome=attempt_outcome)


class OXProtocolError(_ProviderCallError):
    pass


class OXFindingValidationError(OXProtocolError):
    pass
