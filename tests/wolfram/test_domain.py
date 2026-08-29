import pytest

from byte_mcp.wolfram.domain import (
    WolframPurpose,
    WolframQueryRequest,
    WolframRouteReason,
)


def test_ox_fallback_requires_fallback_purpose_and_local_finding_id() -> None:
    with pytest.raises(ValueError):
        WolframQueryRequest(input="check invariant", route_reason=WolframRouteReason.OX_FALLBACK)

    request = WolframQueryRequest(
        input="check invariant",
        purpose=WolframPurpose.FALLBACK_VALIDATION,
        route_reason=WolframRouteReason.OX_FALLBACK,
        source_finding_id="F-local-1",
    )
    assert request.source_finding_id == "F-local-1"


def test_non_fallback_route_rejects_source_finding_id() -> None:
    with pytest.raises(ValueError):
        WolframQueryRequest(input="2+2", source_finding_id="F-local-1")


@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_blank_input_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        WolframQueryRequest(input=value)
