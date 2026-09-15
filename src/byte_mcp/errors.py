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
