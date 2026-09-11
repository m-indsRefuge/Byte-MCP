import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from byte_mcp.nvidia.chat import NvidiaChatResult, NvidiaChatUsage
from byte_mcp.nvidia.errors import NvidiaChatError, NvidiaChatFailureKind
from byte_mcp.nvidia.review_evidence import NvidiaReviewEvidenceStore, NvidiaReviewLockError
from byte_mcp.nvidia.review_registry import NvidiaReviewRepositoryRegistry
from byte_mcp.nvidia.review_service import NvidiaReviewService
from byte_mcp.nvidia.settings import NvidiaHostedSettings
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransportError,
    ProviderTransportFailureKind,
    ProviderTransportObservation,
)
from tests.ox.helpers import create_repository

BASE_TIME = datetime(2026, 9, 10, 14, 0, tzinfo=UTC)
MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"


def write_registry(path: Path, repository_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "repositories": {
                    "fixture": {
                        "path": str(repository_path),
                        "subsystems": {
                            "validation": {
                                "version": 1,
                                "source_roots": ["src"],
                                "test_roots": ["tests"],
                                "boundary_files": ["README.md"],
                                "context_files": ["README.md"],
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def verification() -> list[dict[str, object]]:
    return [
        {
            "id": "pytest",
            "kind": "test",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "912 passed",
            "stderr": "",
            "recorded_at": BASE_TIME.isoformat(),
            "provenance": "operator",
        }
    ]


def prepared_service(tmp_path: Path):
    repository_path, base, target = create_repository(tmp_path / "repo")
    registry_path = tmp_path / "review-repositories.json"
    write_registry(registry_path, repository_path)
    registry = NvidiaReviewRepositoryRegistry.load(registry_path)
    store = NvidiaReviewEvidenceStore(tmp_path / "evidence")
    service = NvidiaReviewService(registry, store)
    prepared = service.prepare_review(
        repository="fixture",
        subsystem="validation",
        target_commit=target,
        base_commit=base,
        objective="Review correctness and regression risk",
        verification=verification(),
    )
    return service, store, prepared


def clock(*offsets: int):
    moments = iter(BASE_TIME + timedelta(seconds=offset) for offset in offsets)
    return lambda: next(moments)


def settings(key: str | None = "configured") -> NvidiaHostedSettings:
    return NvidiaHostedSettings(api_key=key)


def observation(
    provider_started_at: str,
    *,
    outcome: ProviderAttemptOutcome = ProviderAttemptOutcome.COMPLETED,
    transport_failure_kind: ProviderTransportFailureKind | None = None,
) -> ProviderTransportObservation:
    started = datetime.fromisoformat(provider_started_at)
    finished = (started + timedelta(seconds=1)).isoformat()
    has_headers = outcome is not ProviderAttemptOutcome.NOT_SENT
    has_body = outcome is ProviderAttemptOutcome.COMPLETED
    return ProviderTransportObservation(
        response_headers_received=has_headers,
        response_headers_at=finished if has_headers else None,
        response_headers_elapsed_ms=10 if has_headers else None,
        http_status_code=200 if outcome is ProviderAttemptOutcome.COMPLETED else 429,
        response_body_started=has_body,
        first_body_at=finished if has_body else None,
        first_body_elapsed_ms=20 if has_body else None,
        last_body_at=finished if has_body else None,
        last_body_elapsed_ms=25 if has_body else None,
        decoded_body_bytes_received=128 if has_body else 0,
        provider_started_at=provider_started_at,
        provider_finished_at=finished,
        elapsed_ms=25,
        transport_failure_kind=transport_failure_kind,
        trust_env_enabled=True,
        proxy_environment_present=False,
    )


def valid_content() -> str:
    return json.dumps(
        {
            "decision": "FINDINGS",
            "summary": "One bounded finding.",
            "findings": [
                {
                    "severity": "MEDIUM",
                    "path": "src/alpha.py",
                    "line": 1,
                    "title": "Regression risk",
                    "explanation": "The changed value may alter expected behavior.",
                    "recommendation": "Verify the change with a regression test.",
                }
            ],
        },
        separators=(",", ":"),
    )


def success_result(prepared_request, context, *, content: str | None = None) -> NvidiaChatResult:
    return NvidiaChatResult(
        model_id=MODEL_ID,
        content=valid_content() if content is None else content,
        finish_reason="stop",
        response_id="nvr-test-response",
        usage=NvidiaChatUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        request_sha256=prepared_request.request_sha256,
        payload_sha256=prepared_request.payload_sha256,
        transport_observation=observation(context.provider_started_at),
    )


@pytest.mark.parametrize(
    ("approve", "hash_override"),
    [(False, None), (True, "0" * 64)],
)
def test_preflight_rejection_makes_zero_settings_and_executor_calls(
    tmp_path: Path,
    approve: bool,
    hash_override: str | None,
) -> None:
    service, store, prepared = prepared_service(tmp_path)
    calls = {"settings": 0, "executor": 0}

    def loader():
        calls["settings"] += 1
        return settings()

    async def executor(*args, **kwargs):
        calls["executor"] += 1
        raise AssertionError("executor must not run")

    expected_hash = hash_override or prepared["request_sha256"]
    with pytest.raises(ValueError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=expected_hash,
                approve=approve,
                settings_loader=loader,
                executor=executor,
                now=clock(1, 2),
            )
        )

    snapshot = store.load(prepared["review_id"])
    assert calls == {"settings": 0, "executor": 0}
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


@pytest.mark.parametrize("api_key", [None, "bad key"])
def test_credential_preflight_happens_before_authorization_and_start(
    tmp_path: Path,
    api_key: str | None,
) -> None:
    service, store, prepared = prepared_service(tmp_path)
    calls = {"executor": 0}

    async def executor(*args, **kwargs):
        calls["executor"] += 1
        raise AssertionError("executor must not run")

    with pytest.raises(ValueError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=lambda: settings(api_key),
                executor=executor,
                now=clock(1, 2),
            )
        )

    snapshot = store.load(prepared["review_id"])
    assert calls["executor"] == 0
    assert snapshot.authorized_at is None
    assert snapshot.provider_started_at is None


def test_success_executes_exactly_once_and_persists_valid_result(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)
    calls = []

    async def executor(prepared_request, context, hosted_settings):
        calls.append((prepared_request, context, hosted_settings))
        return success_result(prepared_request, context)

    result = asyncio.run(
        service.transmit_review(
            prepared["review_id"],
            expected_request_sha256=prepared["request_sha256"],
            approve=True,
            settings_loader=lambda: settings(),
            executor=executor,
            now=clock(1, 2),
        )
    )

    assert len(calls) == 1
    transmitted, context, _hosted_settings = calls[0]
    snapshot = store.load(prepared["review_id"])
    assert transmitted.body_bytes == snapshot.request_body
    assert transmitted.request_sha256 == prepared["request_sha256"]
    assert context.expected_request_sha256 == prepared["request_sha256"]
    assert snapshot.provider_started_at == context.provider_started_at
    assert snapshot.terminal_event["attempt_outcome"] == "COMPLETED"
    assert snapshot.terminal_event["review_result_status"] == "VALID"
    assert snapshot.result is not None
    assert snapshot.result.decision == "FINDINGS"
    assert result["review_id"] == prepared["review_id"]
    assert result["review_result_status"] == "VALID"
    assert result["decision"] == "FINDINGS"

    with pytest.raises(ValueError, match="provider-start"):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=lambda: settings(),
                executor=executor,
                now=clock(3, 4),
            )
        )
    assert len(calls) == 1


def test_malformed_provider_result_terminalizes_completed_invalid(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)

    async def executor(prepared_request, context, hosted_settings):
        return success_result(prepared_request, context, content="not-json")

    result = asyncio.run(
        service.transmit_review(
            prepared["review_id"],
            expected_request_sha256=prepared["request_sha256"],
            approve=True,
            settings_loader=lambda: settings(),
            executor=executor,
            now=clock(1, 2),
        )
    )

    snapshot = store.load(prepared["review_id"])
    assert snapshot.terminal_event["attempt_outcome"] == "COMPLETED"
    assert snapshot.terminal_event["review_result_status"] == "INVALID"
    assert snapshot.result is None
    assert result["review_result_status"] == "INVALID"
    assert result["decision"] is None


def test_known_nvidia_error_is_terminalized_once_and_reraised(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)

    async def executor(prepared_request, context, hosted_settings):
        raise NvidiaChatError(
            kind=NvidiaChatFailureKind.RATE_LIMIT,
            attempt_outcome=ProviderAttemptOutcome.REJECTED,
            transport_observation=observation(
                context.provider_started_at,
                outcome=ProviderAttemptOutcome.REJECTED,
            ),
            request_sha256=prepared_request.request_sha256,
        )

    with pytest.raises(NvidiaChatError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=lambda: settings(),
                executor=executor,
                now=clock(1, 2),
            )
        )

    snapshot = store.load(prepared["review_id"])
    assert snapshot.terminal_event["attempt_outcome"] == "REJECTED"
    assert snapshot.terminal_event["nvidia_failure_kind"] == "RATE_LIMIT"
    assert snapshot.terminal_event["review_result_status"] == "NOT_AVAILABLE"


def test_known_transport_error_is_terminalized_once_and_reraised(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)

    async def executor(prepared_request, context, hosted_settings):
        kind = ProviderTransportFailureKind.READ_TIMEOUT
        raise ProviderTransportError(
            attempt_outcome=ProviderAttemptOutcome.OUTCOME_UNKNOWN,
            transport_failure_kind=kind,
            transport_observation=observation(
                context.provider_started_at,
                outcome=ProviderAttemptOutcome.OUTCOME_UNKNOWN,
                transport_failure_kind=kind,
            ),
        )

    with pytest.raises(ProviderTransportError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=lambda: settings(),
                executor=executor,
                now=clock(1, 2),
            )
        )

    snapshot = store.load(prepared["review_id"])
    assert snapshot.terminal_event["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert snapshot.terminal_event["transport_failure_kind"] == "READ_TIMEOUT"
    assert snapshot.terminal_event["review_result_status"] == "NOT_AVAILABLE"


def test_unexpected_post_start_failure_stays_ambiguous_and_blocks_replay(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)
    calls = {"executor": 0, "settings": 0}

    def loader():
        calls["settings"] += 1
        return settings()

    async def executor(*args, **kwargs):
        calls["executor"] += 1
        raise RuntimeError("unexpected post-start failure")

    with pytest.raises(RuntimeError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=loader,
                executor=executor,
                now=clock(1, 2),
            )
        )

    snapshot = store.load(prepared["review_id"])
    assert snapshot.provider_started_at is not None
    assert snapshot.terminal_event is None
    assert calls == {"executor": 1, "settings": 1}

    with pytest.raises(ValueError, match="provider-start"):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=loader,
                executor=executor,
                now=clock(3, 4),
            )
        )
    assert calls == {"executor": 1, "settings": 1}


def test_existing_transmit_lock_blocks_before_settings_or_executor(tmp_path: Path) -> None:
    service, store, prepared = prepared_service(tmp_path)
    calls = {"settings": 0, "executor": 0}

    def loader():
        calls["settings"] += 1
        return settings()

    async def executor(*args, **kwargs):
        calls["executor"] += 1
        raise AssertionError("executor must not run")

    with store.transmit_lock(prepared["review_id"]), pytest.raises(NvidiaReviewLockError):
        asyncio.run(
            service.transmit_review(
                prepared["review_id"],
                expected_request_sha256=prepared["request_sha256"],
                approve=True,
                settings_loader=loader,
                executor=executor,
                now=clock(1, 2),
            )
        )
    assert calls == {"settings": 0, "executor": 0}
