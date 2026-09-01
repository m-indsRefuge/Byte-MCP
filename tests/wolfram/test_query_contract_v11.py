import inspect
from pathlib import Path

import httpx
import pytest

from byte_mcp import server
from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframPolicyError, WolframRequestError
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import (
    WolframClientResult,
    WolframQueryRequest,
)
from byte_mcp.wolfram.policy import WolframOutboundPolicy
from byte_mcp.wolfram.quota import QuotaReservation
from byte_mcp.wolfram.service import WolframService

ASSUMPTION_A = "*C.pi-_*Movie-"
ASSUMPTION_B = "DateOrder_**Day.Month.Year--"


class FakeQuota:
    def __init__(self) -> None:
        self.calls = 0

    def reserve_attempt(self) -> QuotaReservation:
        self.calls += 1
        return QuotaReservation("2026-09", 1, 1800)


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.assumption: tuple[str, ...] | None = None

    def query(
        self,
        value: str,
        max_chars: int,
        assumption: tuple[str, ...] = (),
    ) -> WolframClientResult:
        self.calls += 1
        self.assumption = assumption
        return WolframClientResult(
            result="movie result",
            result_url=None,
            response_chars=12,
            response_at_limit=False,
        )


def test_query_input_must_be_single_line() -> None:
    policy = WolframOutboundPolicy()

    with pytest.raises(WolframPolicyError, match="single-line"):
        policy.prepare("solve x^2 = 4\nfor x")


def test_query_request_accepts_only_bounded_assumption_tokens() -> None:
    request = WolframQueryRequest(
        input="pi",
        assumption=(ASSUMPTION_A, ASSUMPTION_B),
    )
    assert request.assumption == (ASSUMPTION_A, ASSUMPTION_B)

    invalid = (
        ("",),
        ("   ",),
        ("bad\nassumption",),
        ("bad\rassumption",),
        ("bad\x00assumption",),
    )

    for assumption in invalid:
        with pytest.raises(WolframRequestError):
            WolframQueryRequest(
                input="pi",
                assumption=assumption,
            )

    with pytest.raises(WolframRequestError, match="at most 8"):
        WolframQueryRequest(
            input="pi",
            assumption=tuple(f"A-{index}" for index in range(9)),
        )


def test_assumption_tokens_are_policy_screened_without_rewriting() -> None:
    policy = WolframOutboundPolicy()

    prepared = policy.prepare_assumptions((ASSUMPTION_A, ASSUMPTION_B))
    assert prepared == (ASSUMPTION_A, ASSUMPTION_B)

    with pytest.raises(WolframPolicyError, match="sensitive"):
        policy.prepare_assumptions(("Authorization: Bearer SECRET-TOKEN",))


def test_client_encodes_multiple_assumptions_as_repeated_parameters(
    wolfram_settings,
) -> None:
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, text="Result:\nmovie")

    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(handler),
    )

    client.query(
        "pi",
        6800,
        assumption=(ASSUMPTION_A, ASSUMPTION_B),
    )

    params = seen["request"].url.params

    assert params["input"] == "pi"
    assert params["maxchars"] == "6800"
    assert params.get_list("assumption") == [
        ASSUMPTION_A,
        ASSUMPTION_B,
    ]


def test_service_forwards_assumptions_without_persisting_raw_tokens(
    tmp_path: Path,
    wolfram_settings,
) -> None:
    quota = FakeQuota()
    client = FakeClient()
    audit_path = tmp_path / "audit.jsonl"

    service = WolframService(
        wolfram_settings,
        AuditLog(audit_path),
        WolframOutboundPolicy(),
        quota,
        client,
    )

    result = service.query(
        "pi",
        1000,
        "COENGINEERING",
        "KNOWLEDGE_LOOKUP",
        assumption=[ASSUMPTION_A, ASSUMPTION_B],
    )

    assert result["result"] == "movie result"
    assert quota.calls == 1
    assert client.calls == 1
    assert client.assumption == (
        ASSUMPTION_A,
        ASSUMPTION_B,
    )

    audit_text = audit_path.read_text(encoding="utf-8")
    assert ASSUMPTION_A not in audit_text
    assert ASSUMPTION_B not in audit_text


def test_mcp_surface_exposes_only_bounded_assumption_authority() -> None:
    parameters = set(inspect.signature(server.wolfram_query).parameters)

    assert parameters == {
        "input",
        "max_chars",
        "purpose",
        "route_reason",
        "source_finding_id",
        "assumption",
    }

    assert parameters.isdisjoint(
        {
            "appid",
            "url",
            "endpoint",
            "headers",
            "method",
        }
    )


def test_mcp_tool_description_contains_wolfram_query_guidance() -> None:
    doc = inspect.getdoc(server.wolfram_query)
    assert doc is not None

    expected_guidance = (
        "single-line",
        "English",
        "6*10^14",
        "single-letter",
        "named physical constants",
        "compound units",
        "exact same input",
        "automatic retries",
    )

    for phrase in expected_guidance:
        assert phrase.lower() in doc.lower()
