from byte_mcp import errors
from byte_mcp.errors import ByteMCPError, OXTransportError, OXTransportFailureKind


def test_domain_error_base_does_not_inherit_runtime_error() -> None:
    assert not issubclass(ByteMCPError, RuntimeError)


def test_ox_transport_error_exposes_typed_safe_diagnostic_defaults() -> None:
    error = OXTransportError(attempt_outcome="NOT_SENT")

    assert [(kind.name, kind.value) for kind in OXTransportFailureKind] == [
        ("ABSOLUTE_DEADLINE", "ABSOLUTE_DEADLINE"),
        ("READ_TIMEOUT", "READ_TIMEOUT"),
        ("READ_ERROR", "READ_ERROR"),
        ("WRITE_TIMEOUT", "WRITE_TIMEOUT"),
        ("WRITE_ERROR", "WRITE_ERROR"),
        ("REMOTE_PROTOCOL_ERROR", "REMOTE_PROTOCOL_ERROR"),
        ("HTTP_TRANSPORT_ERROR", "HTTP_TRANSPORT_ERROR"),
        ("CONNECT_TIMEOUT", "CONNECT_TIMEOUT"),
        ("CONNECT_ERROR", "CONNECT_ERROR"),
        ("POOL_TIMEOUT", "POOL_TIMEOUT"),
    ]
    assert all(isinstance(kind, OXTransportFailureKind) for kind in OXTransportFailureKind)
    assert errors.OXTransportFailureKind is OXTransportFailureKind
    assert error.__dict__ == {
        "transport_failure_kind": None,
        "provider_started_at": None,
        "provider_finished_at": None,
        "elapsed_ms": None,
        "attempt_outcome": "NOT_SENT",
    }
    assert error.transport_failure_kind is None
    assert error.provider_started_at is None
    assert error.provider_finished_at is None
    assert error.elapsed_ms is None
    assert error.args == ()
