"""Domain errors for Byte-MCP."""


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


class OXTransportError(_ProviderCallError):
    pass


class OXProtocolError(_ProviderCallError):
    pass


class OXFindingValidationError(OXProtocolError):
    pass
