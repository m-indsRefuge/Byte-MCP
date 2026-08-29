from dataclasses import is_dataclass

import pytest

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
    "contract", [VerificationRecord, ProviderUsage, ProviderResult, Finding, AdjudicationEvent]
)
def test_ox_contracts_are_immutable_dataclasses(contract):
    assert is_dataclass(contract)
    assert contract.__dataclass_params__.frozen
    assert "__slots__" in contract.__dict__
