from byte_mcp import errors
from byte_mcp.errors import ByteMCPError, OXTransportError


def test_domain_error_base_does_not_inherit_runtime_error() -> None:
    assert not issubclass(ByteMCPError, RuntimeError)


def test_ox_transport_error_exposes_typed_safe_diagnostic_defaults() -> None:
    error = OXTransportError(attempt_outcome="NOT_SENT")

    assert isinstance(errors.OXTransportFailureKind.READ_ERROR, str)
    assert errors.OXTransportFailureKind.READ_ERROR.value == "READ_ERROR"
    assert error.transport_failure_kind is None
    assert error.provider_started_at is None
    assert error.provider_finished_at is None
    assert error.elapsed_ms is None
    assert error.args == ()
