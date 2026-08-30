"""Fixed Byte-mediated Wolfram-native calibration cases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NativeCalibrationCase:
    name: str
    query: str
    route_reason: str
    expected_fragments: tuple[str, ...]


NATIVE_CALIBRATION_CASES = (
    NativeCalibrationCase(
        name="IDENTITY",
        query="expand (a+b)^2-a^2-2*a*b-b^2",
        route_reason="VERIFY_BYTE_HYPOTHESIS",
        expected_fragments=("Result:\n0",),
    ),
    NativeCalibrationCase(
        name="OPTIMIZATION",
        query="maximize x*y, x+y=10, x>=0, y>=0",
        route_reason="DIRECT_COMPUTATION",
        expected_fragments=("= 25", "(5, 5)"),
    ),
    NativeCalibrationCase(
        name="RECURRENCE",
        query="f(n)=2*f(n/2)+n, f(1)=1",
        route_reason="VERIFY_BYTE_HYPOTHESIS",
        expected_fragments=("n log",),
    ),
    NativeCalibrationCase(
        name="BACKOFF",
        query="table min(2*2^n,60), n=0 to 6",
        route_reason="GENERATE_TEST_ORACLE",
        expected_fragments=("{2, 4, 8, 16, 32, 60, 60}",),
    ),
    NativeCalibrationCase(
        name="STATE_COUNT",
        query="2^8*5",
        route_reason="DIRECT_COMPUTATION",
        expected_fragments=("Result:\n1280",),
    ),
    NativeCalibrationCase(
        name="FALSEY_CACHE_MODEL",
        query="P && V",
        route_reason="SEARCH_COUNTEREXAMPLE",
        expected_fragments=("T | F | F",),
    ),
)


def native_call_arguments(
    case: NativeCalibrationCase,
    *,
    max_chars: int,
) -> dict[str, object]:
    return {
        "input": case.query,
        "max_chars": max_chars,
        "purpose": "COENGINEERING",
        "route_reason": case.route_reason,
    }


def assess_native_result(
    case: NativeCalibrationCase,
    payload: dict[str, Any],
) -> dict[str, object]:
    if payload.get("status") != "success":
        raise ValueError("Wolfram calibration response was not successful.")
    if payload.get("response_at_limit") is True:
        raise ValueError("Wolfram calibration response reached the response limit.")

    result = payload.get("result")
    if not isinstance(result, str):
        raise ValueError("Wolfram calibration response contained no result text.")
    if any(fragment not in result for fragment in case.expected_fragments):
        raise ValueError(f"Missing expected Wolfram evidence for {case.name}.")

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("Wolfram calibration response contained no usage metadata.")
    local_period_count = usage.get("local_period_count")
    if not isinstance(local_period_count, int) or local_period_count < 1:
        raise ValueError("Wolfram calibration response contained invalid usage metadata.")

    return {
        "name": case.name,
        "status": "pass",
        "local_period_count": local_period_count,
    }
