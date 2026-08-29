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
