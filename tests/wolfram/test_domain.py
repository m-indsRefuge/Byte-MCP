import pytest

from byte_mcp.errors import WolframRequestError
from byte_mcp.wolfram.domain import (
    WolframPurpose,
    WolframQueryRequest,
    WolframRouteReason,
)


def test_ox_fallback_is_explicit_purpose_and_route() -> None:
    assert WolframPurpose.FALLBACK_VALIDATION.value == "FALLBACK_VALIDATION"
    assert WolframRouteReason.OX_FALLBACK.value == "OX_FALLBACK"


def test_query_request_rejects_blank_input() -> None:
    with pytest.raises(WolframRequestError, match="must not be blank"):
        WolframQueryRequest(input="   ")


def test_ox_fallback_requires_fallback_purpose_and_source() -> None:
    with pytest.raises(WolframRequestError, match="FALLBACK_VALIDATION"):
        WolframQueryRequest(
            input="check this",
            route_reason=WolframRouteReason.OX_FALLBACK,
        )

    request = WolframQueryRequest(
        input="check this",
        purpose=WolframPurpose.FALLBACK_VALIDATION,
        route_reason=WolframRouteReason.OX_FALLBACK,
        source_finding_id="F-123",
    )
    assert request.source_finding_id == "F-123"


def test_non_fallback_rejects_source_finding_id() -> None:
    with pytest.raises(WolframRequestError, match="only for OX_FALLBACK"):
        WolframQueryRequest(input="2+2", source_finding_id="F-123")
