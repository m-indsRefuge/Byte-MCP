import json
from pathlib import Path
import pytest

from byte_mcp.audit import AuditLog
from byte_mcp.errors import AuditError, WolframPolicyError, WolframProviderError, WolframQuotaError
from byte_mcp.wolfram.domain import (
    WolframClientResult,
    WolframPurpose,
    WolframQueryRequest,
    WolframRouteReason,
)
from byte_mcp.wolfram.policy import PreparedWolframInput
from byte_mcp.wolfram.quota import QuotaReservation
from byte_mcp.wolfram.service import WolframService


class FakeSettings:
    app_id = "SENTINEL-WOLFRAM-APPID"

    def __init__(self, events):
        self.events = events

    def apply_max_chars(self, requested):
        self.events.append("max_chars")
        return 1000 if requested is None else max(250, min(requested, 6800))


class FakePolicy:
    def __init__(self, events, *, error=None):
        self.events = events
        self.error = error
        self.calls = 0

    def prepare(self, text):
        self.calls += 1
        self.events.append("policy")
        if self.error:
            raise self.error
        return PreparedWolframInput(
            text="sanitized input",
            sha256="a" * 64,
            original_chars=len(text),
            transmitted_chars=len("sanitized input"),
            paths_sanitized=1,
        )


class FakeQuota:
    def __init__(self, events, *, error=None):
        self.events = events
        self.error = error
        self.calls = 0

    def reserve_attempt(self):
        self.calls += 1
        self.events.append("quota")
        if self.error:
            raise self.error
        return QuotaReservation("2026-08", 1, 10)


class FakeClient:
    def __init__(self, events, *, error=None, result_text="42"):
        self.events = events
        self.error = error
        self.result_text = result_text
        self.calls = 0
        self.last_input = None
        self.last_max_chars = None

    def query(self, input_text, max_chars):
        self.calls += 1
        self.events.append("client")
        self.last_input = input_text
        self.last_max_chars = max_chars
        if self.error:
            raise self.error
        return WolframClientResult(
            text=self.result_text,
            result_url="https://www.wolframalpha.com/input?i=42",
            response_chars=len(self.result_text),
            response_at_limit=False,
        )


class FakeAudit:
    def __init__(self, events, *, fail_outcome=None):
        self.events = events
        self.fail_outcome = fail_outcome
        self.records = []

    def record(self, action, *, outcome="allowed", **fields):
        self.events.append(f"audit:{outcome}")
        if outcome == self.fail_outcome:
            raise AuditError("Audit persistence failed.")
        self.records.append({"action": action, "outcome": outcome, **fields})


def build_service(events, *, policy=None, quota=None, client=None, audit=None):
    return WolframService(
        settings=FakeSettings(events),
        audit=audit or FakeAudit(events),
        policy=policy or FakePolicy(events),
        quota=quota or FakeQuota(events),
        client=client or FakeClient(events),
    )


def test_happy_path_obeys_security_order_and_public_shape() -> None:
    events = []
    client = FakeClient(events, result_text="result")
    service = build_service(events, client=client)
    request = WolframQueryRequest(
        input="C:\\Users\\test\\equation",
        purpose=WolframPurpose.COENGINEERING,
        route_reason=WolframRouteReason.DIRECT_COMPUTATION,
    )

    result = service.query(request)

    assert events == ["max_chars", "policy", "quota", "audit:transmitting", "client", "audit:success"]
    assert client.last_input == "sanitized input"
    assert client.last_max_chars == 1000
    assert result == {
        "status": "success",
        "provider": "Wolfram|Alpha",
        "purpose": "COENGINEERING",
        "route_reason": "DIRECT_COMPUTATION",
        "result": "result",
        "result_url": "https://www.wolframalpha.com/input?i=42",
        "response_chars": 6,
        "response_at_limit": False,
        "usage": {
            "local_period_utc": "2026-08",
            "local_period_count": 1,
            "soft_limit": 10,
        },
    }
    assert "request_id" not in result


def test_audit_persists_only_metadata_not_query_result_or_appid(tmp_path: Path) -> None:
    events = []
    audit_path = tmp_path / "audit.jsonl"
    service = WolframService(
        settings=FakeSettings(events),
        audit=AuditLog(audit_path),
        policy=FakePolicy(events),
        quota=FakeQuota(events),
        client=FakeClient(events, result_text="SENTINEL-RESULT-CONTENT"),
    )
    service.query(
        WolframQueryRequest(
            input="SENTINEL-QUERY-CONTENT",
            route_reason=WolframRouteReason.VERIFY_BYTE_HYPOTHESIS,
        )
    )

    raw = audit_path.read_text(encoding="utf-8")
    assert "SENTINEL-QUERY-CONTENT" not in raw
    assert "SENTINEL-RESULT-CONTENT" not in raw
    assert "SENTINEL-WOLFRAM-APPID" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    allowed = {
        "timestamp_utc", "action", "outcome", "provider", "purpose", "route_reason",
        "request_id", "input_sha256", "input_chars", "transmitted_chars",
        "paths_sanitized", "max_chars_applied", "period_utc", "period_count",
        "response_chars", "duration_ms", "error_type", "source_finding_id",
    }
    assert len(records) == 2
    assert all(set(record) <= allowed for record in records)


def test_policy_denial_happens_before_quota_and_network() -> None:
    events = []
    policy = FakePolicy(events, error=WolframPolicyError("sensitive"))
    quota = FakeQuota(events)
    client = FakeClient(events)
    service = build_service(events, policy=policy, quota=quota, client=client)

    with pytest.raises(WolframPolicyError):
        service.query(WolframQueryRequest(input="secret-looking"))

    assert events == ["max_chars", "policy"]
    assert quota.calls == 0
    assert client.calls == 0


def test_quota_denial_happens_before_audit_and_network() -> None:
    events = []
    quota = FakeQuota(events, error=WolframQuotaError("exhausted"))
    client = FakeClient(events)
    audit = FakeAudit(events)
    service = build_service(events, quota=quota, client=client, audit=audit)

    with pytest.raises(WolframQuotaError):
        service.query(WolframQueryRequest(input="2+2"))

    assert events == ["max_chars", "policy", "quota"]
    assert client.calls == 0
    assert audit.records == []


def test_transmission_intent_audit_failure_aborts_before_network_but_keeps_reservation() -> None:
    events = []
    quota = FakeQuota(events)
    client = FakeClient(events)
    service = build_service(events, quota=quota, client=client, audit=FakeAudit(events, fail_outcome="transmitting"))

    with pytest.raises(AuditError):
        service.query(WolframQueryRequest(input="2+2"))

    assert events == ["max_chars", "policy", "quota", "audit:transmitting"]
    assert quota.calls == 1
    assert client.calls == 0


def test_provider_failure_is_audited_once_and_re_raised() -> None:
    events = []
    client = FakeClient(events, error=WolframProviderError("provider down"))
    audit = FakeAudit(events)
    service = build_service(events, client=client, audit=audit)

    with pytest.raises(WolframProviderError):
        service.query(WolframQueryRequest(input="2+2"))

    assert events == ["max_chars", "policy", "quota", "audit:transmitting", "client", "audit:error"]
    assert client.calls == 1
    assert audit.records[-1]["error_type"] == "WolframProviderError"


def test_final_success_audit_failure_does_not_retry_provider_or_return_result() -> None:
    events = []
    client = FakeClient(events)
    service = build_service(events, client=client, audit=FakeAudit(events, fail_outcome="success"))

    with pytest.raises(AuditError):
        service.query(WolframQueryRequest(input="2+2"))

    assert events == ["max_chars", "policy", "quota", "audit:transmitting", "client", "audit:success"]
    assert client.calls == 1


def test_ox_fallback_audit_contains_only_local_finding_reference() -> None:
    events = []
    audit = FakeAudit(events)
    service = build_service(events, audit=audit)
    request = WolframQueryRequest(
        input="independently check this invariant",
        purpose=WolframPurpose.FALLBACK_VALIDATION,
        route_reason=WolframRouteReason.OX_FALLBACK,
        source_finding_id="F-local-9",
    )

    service.query(request)

    assert all(record["source_finding_id"] == "F-local-9" for record in audit.records)
    serialized = repr(audit.records)
    assert "ox_prompt" not in serialized
    assert "ox_response" not in serialized
