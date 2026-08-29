from byte_mcp.errors import ByteMCPError


def test_domain_error_base_does_not_inherit_runtime_error() -> None:
    assert not issubclass(ByteMCPError, RuntimeError)
