from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import httpx
import pytest

import byte_mcp.ox.service as ox_service
from byte_mcp.errors import OXBundleError, OXConfigurationError, OXEvidenceError, OXScopeError
from byte_mcp.ox.evidence import OXEvidenceStore
from byte_mcp.ox.models import OXPreparedReview, OXReviewMode, OXReviewScope
from byte_mcp.ox.scope import OXResolvedRepository, OXScopeResolver
from byte_mcp.ox.settings import OXSettings
from byte_mcp.providers import ProviderTransmissionContext

_API_KEY = "test-only-ox-service-key"
_OBJECTIVE = "Review the frozen repository for correctness and reliability."


def _projects_root(tmp_path: Path, *, content: str = "print('hello')\n") -> Path:
    projects = tmp_path / "projects"
    repository = projects / "repo"
    repository.mkdir(parents=True)
    (repository / "app.py").write_text(content, encoding="utf-8")
    return projects


def _settings_loader(evidence_root: Path, api_key: str | None = _API_KEY) -> Callable[[], OXSettings]:
    return lambda: OXSettings(api_key=api_key, evidence_root=evidence_root)


def _service(
    tmp_path: Path,
    *,
    api_key: str | None = _API_KEY,
    resolver: OXScopeResolver | None = None,
    store: OXEvidenceStore | None = None,
) -> tuple[ox_service.OXReviewService, OXEvidenceStore, Path]:
    projects = _projects_root(tmp_path)
    evidence_root = tmp_path / "evidence"
    evidence_store = store or OXEvidenceStore(evidence_root)
    scope_resolver = resolver or OXScopeResolver(projects)
    service = ox_service.OXReviewService(
        scope_resolver=scope_resolver,
        evidence_store=evidence_store,
        settings_loader=_settings_loader(evidence_root, api_key),
    )
    return service, evidence_store, evidence_root


def _review(
    service: ox_service.OXReviewService,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    repository: str = "repo",
    mode: str = "FULL_REPOSITORY",
    paths: Sequence[str] | None = None,
) -> dict[str, object]:
    return asyncio.run(
        service.review(
            repository=repository,
            mode=mode,
            paths=paths,
            objective=_OBJECTIVE,
            transport=transport,
        )
    )


def _response_body(review_text: str, *, sentinel: str | None = None) -> bytes:
    payload: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": review_text,
                }
            }
        ]
    }
    if sentinel is not None:
        payload["debug"] = sentinel
    return json.dumps(payload).encode("utf-8")


def _review_directory(evidence_root: Path, review_id: str = "OX-000001") -> Path:
    return evidence_root / "reviews" / review_id


class _RecordingScopeResolver(OXScopeResolver):
    def __init__(self, projects_root: Path, events: list[str]) -> None:
        super().__init__(projects_root)
        self._events = events

    def resolve_scope(
        self,
        repository: str,
        mode: OXReviewMode,
        paths: Sequence[str],
        objective: str,
    ) -> tuple[OXResolvedRepository, OXReviewScope]:
        self._events.append("scope")
        return super().resolve_scope(repository, mode, paths, objective)


class _RecordingEvidenceStore(OXEvidenceStore):
    def __init__(self, evidence_root: Path, events: list[str]) -> None:
        super().__init__(evidence_root)
        self._events = events

    def persist_prepared(self, prepared: OXPreparedReview) -> None:
        self._events.append("persist_prepared")
        super().persist_prepared(prepared)

    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool:
        self._events.append("claim")
        return super().claim_send(review_id, request_sha256, claimed_at)

    def persist_response(self, review_id: str, body: bytes) -> None:
        self._events.append("persist_response")
        super().persist_response(review_id, body)

    def persist_review_text(self, review_id: str, text: str) -> None:
        self._events.append("persist_review")
        super().persist_review_text(review_id, text)

    def finalize(self, review_id: str, terminal_metadata: Mapping[str, object]) -> None:
        self._events.append("finalize")
        super().finalize(review_id, terminal_metadata)


def test_success_lifecycle_persists_raw_response_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    projects = _projects_root(tmp_path)
    evidence_root = tmp_path / "evidence"
    resolver = _RecordingScopeResolver(projects, events)
    store = _RecordingEvidenceStore(evidence_root, events)

    def load_settings() -> OXSettings:
        events.append("settings")
        return OXSettings(api_key=_API_KEY, evidence_root=evidence_root)

    service = ox_service.OXReviewService(
        scope_resolver=resolver,
        evidence_store=store,
        settings_loader=load_settings,
    )

    original_freeze = ox_service.freeze_snapshot
    original_build = ox_service.build_review_packet
    original_prepare = ox_service.prepare_ox_request
    original_validate = ox_service.validate_prepared_provider_request_integrity
    original_safety = ox_service.validate_provider_bound_safety
    original_execute = ox_service.execute_ox_transport
    original_extract = ox_service.extract_ox_review_text

    def freeze(repository: OXResolvedRepository, scope: OXReviewScope):
        events.append("snapshot")
        return original_freeze(repository, scope)

    def build(scope: OXReviewScope, snapshot):
        events.append("packet")
        return original_build(scope, snapshot)

    def prepare(packet_bytes: bytes):
        events.append("request")
        return original_prepare(packet_bytes)

    def validate(prepared_request) -> None:
        events.append("integrity")
        original_validate(prepared_request)

    def safety(packet_bytes: bytes, request_bytes: bytes, *, exact_credential: str | None) -> None:
        events.append("safety")
        original_safety(packet_bytes, request_bytes, exact_credential=exact_credential)

    async def execute(
        prepared_request,
        transmission_context: ProviderTransmissionContext,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        events.append("execute")
        return await original_execute(
            prepared_request,
            transmission_context,
            api_key=api_key,
            transport=transport,
        )

    def extract(response_body: bytes) -> str:
        events.append("extract")
        assert (_review_directory(evidence_root) / "response.bin").read_bytes() == response_body
        return original_extract(response_body)

    monkeypatch.setattr(ox_service, "freeze_snapshot", freeze)
    monkeypatch.setattr(ox_service, "build_review_packet", build)
    monkeypatch.setattr(ox_service, "prepare_ox_request", prepare)
    monkeypatch.setattr(ox_service, "validate_prepared_provider_request_integrity", validate)
    monkeypatch.setattr(ox_service, "validate_provider_bound_safety", safety)
    monkeypatch.setattr(ox_service, "execute_ox_transport", execute)
    monkeypatch.setattr(ox_service, "extract_ox_review_text", extract)

    calls = 0
    raw_response = _response_body("Free-form OX review.\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        events.append("transport")
        return httpx.Response(200, content=raw_response)

    result = _review(service, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result["state"] == "COMPLETED"
    assert result["review_text"] == "Free-form OX review.\n"
    assert events == [
        "scope",
        "snapshot",
        "packet",
        "request",
        "persist_prepared",
        "settings",
        "integrity",
        "safety",
        "claim",
        "execute",
        "transport",
        "persist_response",
        "extract",
        "persist_review",
        "finalize",
    ]


def test_missing_credential_is_preclaim_and_zero_transport(tmp_path: Path) -> None:
    service, _, evidence_root = _service(tmp_path, api_key=None)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    with pytest.raises(OXConfigurationError):
        _review(service, transport=httpx.MockTransport(handler))

    review_dir = _review_directory(evidence_root)
    assert calls == 0
    assert (review_dir / "review.json").is_file()
    assert not (review_dir / "send.claim").exists()


def test_prepared_integrity_failure_is_preclaim_and_zero_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, evidence_root = _service(tmp_path)
    calls = 0

    def invalid_integrity(prepared_request) -> None:
        raise ValueError("test-only prepared request integrity mismatch")

    monkeypatch.setattr(
        ox_service,
        "validate_prepared_provider_request_integrity",
        invalid_integrity,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    with pytest.raises(OXBundleError):
        _review(service, transport=httpx.MockTransport(handler))

    assert calls == 0
    assert not (_review_directory(evidence_root) / "send.claim").exists()


@pytest.mark.parametrize("boundary", ["snapshot", "packet", "request"])
def test_preclaim_build_failures_do_not_allocate_send_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    service, _, evidence_root = _service(tmp_path)
    calls = 0

    def fail(*args, **kwargs):
        raise OXBundleError(f"test-only {boundary} failure")

    target = {
        "snapshot": "freeze_snapshot",
        "packet": "build_review_packet",
        "request": "prepare_ox_request",
    }[boundary]
    monkeypatch.setattr(ox_service, target, fail)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    with pytest.raises(OXBundleError):
        _review(service, transport=httpx.MockTransport(handler))

    assert calls == 0
    reviews_root = evidence_root / "reviews"
    assert not reviews_root.exists() or not any(reviews_root.iterdir())


def test_invalid_scope_is_preclaim_and_zero_transport(tmp_path: Path) -> None:
    service, _, evidence_root = _service(tmp_path)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    with pytest.raises(OXScopeError):
        _review(
            service,
            repository="../repo",
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0
    reviews_root = evidence_root / "reviews"
    assert not reviews_root.exists() or not any(reviews_root.iterdir())


def test_prepared_evidence_persistence_failure_is_preclaim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, evidence_root = _service(tmp_path)
    calls = 0

    def fail_persist(prepared: OXPreparedReview) -> None:
        raise OXEvidenceError("test-only prepared evidence failure")

    monkeypatch.setattr(store, "persist_prepared", fail_persist)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    with pytest.raises(OXEvidenceError):
        _review(service, transport=httpx.MockTransport(handler))

    assert calls == 0
    assert not (_review_directory(evidence_root) / "send.claim").exists()


class _RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, exception_type: type[httpx.TransportError]) -> None:
        self.exception_type = exception_type
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise self.exception_type("test-only transport detail", request=request)


@pytest.mark.parametrize(
    ("exception_type", "expected_state", "expected_outcome"),
    [
        (httpx.ConnectError, "FAILED", "NOT_SENT"),
        (httpx.PoolTimeout, "FAILED", "NOT_SENT"),
        (httpx.WriteError, "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
        (httpx.ReadTimeout, "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
        (httpx.RemoteProtocolError, "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
    ],
)
def test_postclaim_transport_failure_is_terminal_without_retry(
    tmp_path: Path,
    exception_type: type[httpx.TransportError],
    expected_state: str,
    expected_outcome: str,
) -> None:
    service, _, evidence_root = _service(tmp_path)
    transport = _RaisingTransport(exception_type)

    result = _review(service, transport=transport)

    assert transport.calls == 1
    assert result["state"] == expected_state
    assert result["attempt_outcome"] == expected_outcome
    assert (_review_directory(evidence_root) / "send.claim").is_file()
    assert not (_review_directory(evidence_root) / "response.bin").exists()


def test_complete_provider_rejection_persists_response_then_fails(tmp_path: Path) -> None:
    service, _, evidence_root = _service(tmp_path)
    calls = 0
    raw_response = b"complete provider rejection"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, content=raw_response)

    result = _review(service, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result["state"] == "FAILED"
    assert result["attempt_outcome"] == "REJECTED"
    assert (_review_directory(evidence_root) / "response.bin").read_bytes() == raw_response


def test_malformed_2xx_is_persisted_before_failed_protocol_projection(tmp_path: Path) -> None:
    service, _, evidence_root = _service(tmp_path)
    calls = 0
    raw_response = b'{"choices":[]}'

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=raw_response)

    result = _review(service, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result["state"] == "FAILED"
    assert result["attempt_outcome"] == "COMPLETED"
    assert result["review_text"] is None
    assert (_review_directory(evidence_root) / "response.bin").read_bytes() == raw_response


def test_response_persistence_failure_projects_outcome_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, evidence_root = _service(tmp_path)
    calls = 0

    def fail_response(review_id: str, body: bytes) -> None:
        raise OXEvidenceError("test-only response persistence failure")

    monkeypatch.setattr(store, "persist_response", fail_response)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("valid review"))

    result = _review(service, transport=httpx.MockTransport(handler))

    assert calls == 1
    assert result["state"] == "OUTCOME_UNKNOWN"
    assert result["attempt_outcome"] == "OUTCOME_UNKNOWN"
    assert (_review_directory(evidence_root) / "send.claim").is_file()
    assert not (_review_directory(evidence_root) / "response.bin").exists()


class _ClaimLostStore(OXEvidenceStore):
    def claim_send(self, review_id: str, request_sha256: str, claimed_at: str) -> bool:
        claimed = super().claim_send(review_id, request_sha256, claimed_at)
        assert claimed is True
        return False


def test_lost_send_claim_projects_existing_evidence_without_transport(tmp_path: Path) -> None:
    projects = _projects_root(tmp_path)
    evidence_root = tmp_path / "evidence"
    store = _ClaimLostStore(evidence_root)
    service = ox_service.OXReviewService(
        scope_resolver=OXScopeResolver(projects),
        evidence_store=store,
        settings_loader=_settings_loader(evidence_root),
    )
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_response_body("unexpected"))

    result = _review(service, transport=httpx.MockTransport(handler))

    assert calls == 0
    assert result["state"] == "OUTCOME_UNKNOWN"
    assert (_review_directory(evidence_root) / "send.claim").is_file()


def test_get_review_is_local_and_returns_only_safe_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = _service(tmp_path)
    raw_sentinel = "RAW-ENVELOPE-SENTINEL"
    raw_response = _response_body("Safe free-form review", sentinel=raw_sentinel)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw_response)

    created = _review(service, transport=httpx.MockTransport(handler))

    async def forbidden_transport(*args, **kwargs):
        raise AssertionError("get_review must never perform provider networking")

    monkeypatch.setattr(ox_service, "execute_ox_transport", forbidden_transport)
    result = service.get_review(str(created["review_id"]))

    assert set(result) == {
        "review_id",
        "state",
        "repository",
        "mode",
        "scope",
        "snapshot_sha256",
        "request_sha256",
        "provider",
        "model",
        "provider_started_at",
        "provider_finished_at",
        "attempt_outcome",
        "response_bytes",
        "review_text",
    }
    assert result["state"] == "COMPLETED"
    assert result["scope"] == {"repository": "repo", "mode": "FULL_REPOSITORY"}
    assert result["provider"] == "ox"
    assert result["model"] == "zai/glm-5.3-flash"
    assert result["review_text"] == "Safe free-form review"

    rendered = json.dumps(result, sort_keys=True)
    assert _API_KEY not in rendered
    assert raw_sentinel not in rendered
    assert str(tmp_path.resolve()) not in rendered
