from dataclasses import is_dataclass

import pytest

from byte_mcp.errors import (
    OXAuthenticationError,
    OXContextLimitError,
    OXFindingValidationError,
    OXPermissionError,
    OXProtocolError,
    OXProviderUnavailableError,
    OXQuotaError,
    OXRateLimitError,
    OXRequestError,
    OXTransportError,
)
from byte_mcp.ox.models import (
    AdjudicationEvent,
    AttemptOutcome,
    Finding,
    FindingStatus,
    OXAvailability,
    ProviderResult,
    ProviderUsage,
    ReviewState,
    VerificationRecord,
)


def test_ox_enums_use_approved_values():
    assert OXAvailability.AVAILABLE.value == "AVAILABLE"
    assert ReviewState.REVIEWED.value == "REVIEWED"
    assert AttemptOutcome.OUTCOME_UNKNOWN.value == "OUTCOME_UNKNOWN"
    assert FindingStatus.REVALIDATED.value == "REVALIDATED"


@pytest.mark.parametrize(
    "error_type",
    [
        OXAuthenticationError,
        OXContextLimitError,
        OXFindingValidationError,
        OXProtocolError,
        OXPermissionError,
        OXProviderUnavailableError,
        OXQuotaError,
        OXRateLimitError,
        OXRequestError,
        OXTransportError,
    ],
)
def test_provider_call_errors_store_only_approved_attempt_outcome(error_type):
    error = error_type(attempt_outcome="NOT_SENT")
    assert error.attempt_outcome == "NOT_SENT"
    assert error.args == ()
    with pytest.raises(ValueError):
        error_type(attempt_outcome="sent")
    with pytest.raises(TypeError):
        error_type(attempt_outcome="NOT_SENT", headers={"Authorization": "secret"})


@pytest.mark.parametrize(
    "contract", [VerificationRecord, ProviderUsage, ProviderResult, Finding, AdjudicationEvent]
)
def test_ox_contracts_are_immutable_dataclasses(contract):
    assert is_dataclass(contract)
    assert contract.__dataclass_params__.frozen
    assert "__slots__" in contract.__dict__
