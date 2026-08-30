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


class WriteError(ByteMCPError):
    """Base error for expected controlled-write failures."""


class WriteConfigurationError(WriteError):
    """Raised when operator write configuration is invalid."""


class WritePolicyError(WriteError):
    """Raised when the active policy denies a requested mutation."""


class WritePathError(WriteError):
    """Raised when a mutation path violates write containment rules."""


class WriteConflictError(WriteError):
    """Raised when a mutation conflicts with current state."""


class WriteStaleStateError(WriteError):
    """Raised when a mutation is based on stale state."""


class WritePatchError(WriteError):
    """Raised when a patch is invalid or cannot be applied."""


class WriteTransactionError(WriteError):
    """Raised when a write transaction cannot proceed."""


class WriteExpiredError(WriteError):
    """Raised when a write transaction or lease has expired."""


class WriteLockError(WriteError):
    """Raised when a required write lock cannot be acquired."""


class WriteIntegrityError(WriteError):
    """Raised when write-state integrity verification fails."""


class WriteRollbackError(WriteError):
    """Raised when rollback cannot restore write state."""


class WriteRecoveryRequiredError(WriteError):
    """Raised when recovery is required before further writes."""


class WriteLimitError(WriteError):
    """Raised when a write exceeds a policy limit."""
