import pytest


MODULE_NAME = "byte_mcp.wolfram.native_calibration"


def _module():
    try:
        return __import__(MODULE_NAME, fromlist=["*"])
    except ModuleNotFoundError:
        pytest.fail("native Wolfram calibration module must exist")


def test_native_calibration_corpus_is_fixed_and_byte_owned() -> None:
    module = _module()

    observed = [
        (case.name, case.query, case.route_reason, case.expected_fragments)
        for case in module.NATIVE_CALIBRATION_CASES
    ]

    assert observed == [
        (
            "IDENTITY",
            "expand (a+b)^2-a^2-2*a*b-b^2",
            "VERIFY_BYTE_HYPOTHESIS",
            ("Result:\n0",),
        ),
        (
            "OPTIMIZATION",
            "maximize x*y, x+y=10, x>=0, y>=0",
            "DIRECT_COMPUTATION",
            ("= 25", "(5, 5)"),
        ),
        (
            "RECURRENCE",
            "f(n)=2*f(n/2)+n, f(1)=1",
            "VERIFY_BYTE_HYPOTHESIS",
            ("n log",),
        ),
        (
            "BACKOFF",
            "table min(2*2^n,60), n=0 to 6",
            "GENERATE_TEST_ORACLE",
            ("{2, 4, 8, 16, 32, 60, 60}",),
        ),
        (
            "STATE_COUNT",
            "2^8*5",
            "DIRECT_COMPUTATION",
            ("Result:\n1280",),
        ),
        (
            "FALSEY_CACHE_MODEL",
            "P && V",
            "SEARCH_COUNTEREXAMPLE",
            ("T | F | F",),
        ),
    ]


def test_native_calibration_queries_are_single_line_and_bounded() -> None:
    module = _module()

    for case in module.NATIVE_CALIBRATION_CASES:
        assert case.query == case.query.strip()
        assert "\n" not in case.query
        assert len(case.query) <= 80


def test_assess_native_result_accepts_expected_evidence() -> None:
    module = _module()
    case = module.NATIVE_CALIBRATION_CASES[5]
    payload = {
        "status": "success",
        "result": "Truth table:\nP | V | P ∧ V\nT | T | T\nT | F | F\nF | T | F\nF | F | F",
        "response_at_limit": False,
        "usage": {"local_period_count": 18},
    }

    observation = module.assess_native_result(case, payload)

    assert observation == {
        "name": "FALSEY_CACHE_MODEL",
        "status": "pass",
        "local_period_count": 18,
    }


def test_assess_native_result_rejects_missing_expected_evidence() -> None:
    module = _module()
    case = module.NATIVE_CALIBRATION_CASES[0]
    payload = {
        "status": "success",
        "result": "Result:\n1",
        "response_at_limit": False,
        "usage": {"local_period_count": 19},
    }

    with pytest.raises(ValueError, match="expected Wolfram evidence"):
        module.assess_native_result(case, payload)


def test_assess_native_result_rejects_truncated_response() -> None:
    module = _module()
    case = module.NATIVE_CALIBRATION_CASES[4]
    payload = {
        "status": "success",
        "result": "Result:\n1280",
        "response_at_limit": True,
        "usage": {"local_period_count": 20},
    }

    with pytest.raises(ValueError, match="response limit"):
        module.assess_native_result(case, payload)
