import json
from pathlib import Path

import pytest

from byte_mcp.audit import AuditLog
from byte_mcp.errors import WolframPolicyError, WolframQuotaError
from byte_mcp.wolfram.domain import WolframClientResult
from byte_mcp.wolfram.policy import PreparedWolframInput
from byte_mcp.wolfram.quota import QuotaReservation
from byte_mcp.wolfram.service import WolframService


class FakePolicy:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def prepare(self, value: str) -> PreparedWolframInput:
        self.calls += 1
        if self.fail:
            raise WolframPolicyError("sensitive")
        return PreparedWolframInput(value, "a" * 64, len(value), len(value), 0)


class FakeQuota:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def reserve_attempt(self) -> QuotaReservation:
        self.calls += 1
        if self.fail:
            raise WolframQuotaError("quota")
        return QuotaReservation("2026-08", 1, 10)


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, value: str, max_chars: int) -> WolframClientResult:
        self.calls += 1
        return WolframClientResult(
            result="4",
            result_url="https://www.wolframalpha.com/input?i=2%2B2",
            response_chars=1,
            response_at_limit=False,
        )


def build_service(tmp_path: Path, wolfram_settings, policy, quota, client) -> WolframService:
    return WolframService(
        wolfram_settings,
        AuditLog(tmp_path / "audit.jsonl"),
        policy,
        quota,
        client,
    )


def test_service_happy_path_and_audit_privacy(tmp_path, wolfram_settings) -> None:
    policy = FakePolicy()
    quota = FakeQuota()
    client = FakeClient()
    service = build_service(tmp_path, wolfram_settings, policy, quota, client)

    result = service.query(
        "2+2",
        1000,
        "COENGINEERING",
        "DIRECT_COMPUTATION",
    )

    assert result["result"] == "4"
    assert result["usage"] == {
        "local_period_utc": "2026-08",
        "local_period_count": 1,
        "soft_limit": 10,
    }
    assert policy.calls == quota.calls == client.calls == 1

    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "2+2" not in audit_text
    assert "TEST-WOLFRAM-APPID" not in audit_text
    assert '"result"' not in audit_text
    events = [json.loads(line) for line in audit_text.splitlines()]
    assert [event["outcome"] for event in events] == ["transmitting", "allowed"]
    assert all(event["input_sha256"] == "a" * 64 for event in events)


def test_policy_failure_happens_before_quota_or_network(tmp_path, wolfram_settings) -> None:
    policy = FakePolicy(fail=True)
    quota = FakeQuota()
    client = FakeClient()
    service = build_service(tmp_path, wolfram_settings, policy, quota, client)

    with pytest.raises(WolframPolicyError):
        service.query("secret", None, "COENGINEERING", "DIRECT_COMPUTATION")
    assert policy.calls == 1
    assert quota.calls == 0
    assert client.calls == 0


def test_quota_failure_happens_before_network(tmp_path, wolfram_settings) -> None:
    policy = FakePolicy()
    quota = FakeQuota(fail=True)
    client = FakeClient()
    service = build_service(tmp_path, wolfram_settings, policy, quota, client)

    with pytest.raises(WolframQuotaError):
        service.query("2+2", None, "COENGINEERING", "DIRECT_COMPUTATION")
    assert policy.calls == 1
    assert quota.calls == 1
    assert client.calls == 0
