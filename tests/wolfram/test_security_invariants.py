import json
from dataclasses import fields
from pathlib import Path

import httpx
import pytest

from byte_mcp.audit import AuditLog
from byte_mcp.errors import (
    WolframPolicyError,
    WolframProtocolError,
    WolframProviderError,
    WolframRateLimitError,
    WolframTimeoutError,
    WolframTransportError,
)
from byte_mcp.service import FileService
from byte_mcp.settings import Settings
from byte_mcp.wolfram.client import WolframLLMClient
from byte_mcp.wolfram.domain import WolframQueryRequest
from byte_mcp.wolfram.policy import WolframOutboundPolicy
from byte_mcp.wolfram.quota import WolframQuotaLedger
from byte_mcp.wolfram.service import WolframService


def _file_service(tmp_path: Path) -> FileService:
    root = tmp_path / "projects"
    root.mkdir()
    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"roots": {"projects": str(root)}}), encoding="utf-8")
    settings = Settings(
        repo_root=tmp_path,
        roots_file=roots,
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=1_000_000,
        max_response_chars=10_000,
        max_search_files=1_000,
        content_search_max_bytes=100_000,
    )
    return FileService(settings)


def test_secret_policy_denial_is_pre_transport(wolfram_settings) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="should-not-run")

    policy = WolframOutboundPolicy()
    with pytest.raises(WolframPolicyError):
        policy.prepare("WOLFRAM_APP_ID=SENTINEL-WOLFRAM-APPID")
    assert calls == 0


def test_public_query_contract_contains_no_ox_transcript_fields() -> None:
    names = {field.name for field in fields(WolframQueryRequest)}
    assert names.isdisjoint(
        {"ox_prompt", "ox_response", "ox_thread", "ox_messages", "provider_context"}
    )
    assert "source_finding_id" in names


@pytest.mark.parametrize(
    ("kind", "error_type"),
    [
        ("429", WolframRateLimitError),
        ("500", WolframProviderError),
        ("blank", WolframProtocolError),
        ("timeout", WolframTimeoutError),
        ("transport", WolframTransportError),
    ],
)
def test_failures_make_one_provider_attempt_and_one_quota_reservation(
    tmp_path: Path,
    wolfram_settings,
    kind: str,
    error_type: type[Exception],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "429":
            return httpx.Response(429, text="rate")
        if kind == "500":
            return httpx.Response(500, text="provider")
        if kind == "blank":
            return httpx.Response(200, text="   ")
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        raise httpx.ConnectError("connect", request=request)

    client = WolframLLMClient(wolfram_settings, transport=httpx.MockTransport(handler))
    quota = WolframQuotaLedger(tmp_path / "usage.json", 10)
    service = WolframService(
        wolfram_settings,
        AuditLog(tmp_path / "audit.jsonl"),
        WolframOutboundPolicy(),
        quota,
        client,
    )

    with pytest.raises(error_type):
        service.query("2+2", 1000, "COENGINEERING", "DIRECT_COMPUTATION")

    assert calls == 1
    assert quota.snapshot().period_count == 1


def test_operational_files_do_not_persist_query_result_or_appid(
    tmp_path: Path,
    wolfram_settings,
) -> None:
    query = "SENTINEL-QUERY-CONTENT"
    result = "SENTINEL-RESULT-CONTENT"
    client = WolframLLMClient(
        wolfram_settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=result)),
    )
    quota = WolframQuotaLedger(tmp_path / "usage.json", 10)
    audit = AuditLog(tmp_path / "audit.jsonl")
    service = WolframService(wolfram_settings, audit, WolframOutboundPolicy(), quota, client)

    response = service.query(query, 1000, "COENGINEERING", "OTHER_BOUNDED_REASON")
    assert response["result"] == result

    persistent = (tmp_path / "audit.jsonl").read_text() + (tmp_path / "usage.json").read_text()
    assert query not in persistent
    assert result not in persistent
    assert "TEST-WOLFRAM-APPID" not in persistent


def test_core_file_service_is_independent_of_wolfram_failures(tmp_path: Path) -> None:
    service = _file_service(tmp_path)
    result = service.list_roots()
    assert [item["alias"] for item in result["roots"]] == ["projects"]
