from __future__ import annotations

import ast
import asyncio
import json
import socket
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from byte_mcp import server
from byte_mcp.errors import OXBundleError, OXRepositoryError
from byte_mcp.ox.client import execute_ox_transport
from byte_mcp.ox.evidence import OXEvidenceStore
from byte_mcp.ox.packet import prepare_ox_request, validate_provider_bound_safety
from byte_mcp.ox.runtime import OXRuntime
from byte_mcp.ox.scope import OXScopeResolver
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OX_MAX_ARTIFACT_BYTES, OXSettings
from byte_mcp.providers import (
    ProviderAttemptOutcome,
    ProviderTransmissionContext,
    ProviderTransportError,
)
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity
from byte_mcp.settings import Settings

_PRIVATE_KEY_MARKERS = (
    b"BEGIN PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN EC PRIVATE KEY",
    b"BEGIN OPENSSH PRIVATE KEY",
)
OX_SOURCE_ROOT = Path("src/byte_mcp/ox")
NVIDIA_SOURCE_ROOT = Path("src/byte_mcp/nvidia")


@contextmanager
def _no_connections():
    def denied(*args: object, **kwargs: object) -> object:
        raise AssertionError("network access is forbidden in provider-free OX qualification")

    with (
        patch.object(socket.socket, "connect", denied),
        patch.object(socket.socket, "connect_ex", denied),
        patch.object(socket.socket, "sendto", denied),
        patch.object(socket, "create_connection", denied),
        patch.object(asyncio.BaseEventLoop, "create_connection", denied),
        patch.object(asyncio.BaseEventLoop, "create_datagram_endpoint", denied),
    ):
        yield


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        roots_file=tmp_path / "roots.json",
        audit_file=tmp_path / "audit.jsonl",
        max_file_bytes=10_000_000,
        max_response_chars=60_000,
        max_search_files=20_000,
        content_search_max_bytes=1_000_000,
    )


def _service(projects: Path, evidence_root: Path, credential: str) -> OXReviewService:
    return OXReviewService(
        scope_resolver=OXScopeResolver(projects),
        evidence_store=OXEvidenceStore(evidence_root),
        settings_loader=lambda: OXSettings(
            api_key=credential,
            evidence_root=evidence_root,
        ),
    )


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


@pytest.mark.parametrize("marker", _PRIVATE_KEY_MARKERS)
@pytest.mark.parametrize("location", ("packet", "request"))
def test_private_key_markers_fail_closed_without_echo(marker: bytes, location: str) -> None:
    packet_bytes = b"safe packet"
    request_bytes = b"safe request"
    if location == "packet":
        packet_bytes += b"\n" + marker + b"\n"
    else:
        request_bytes += b"\n" + marker + b"\n"

    with pytest.raises(OXBundleError) as raised:
        validate_provider_bound_safety(
            packet_bytes,
            request_bytes,
            exact_credential=None,
        )

    assert marker.decode("ascii") not in str(raised.value)


@pytest.mark.parametrize("location", ("packet", "request"))
def test_exact_credential_fails_closed_without_echo(location: str) -> None:
    credential = "vercel-secret-credential-ABC123"
    packet_bytes = b"safe packet"
    request_bytes = b"safe request"
    if location == "packet":
        packet_bytes += credential.encode("utf-8")
    else:
        request_bytes += credential.encode("utf-8")

    with pytest.raises(OXBundleError) as raised:
        validate_provider_bound_safety(
            packet_bytes,
            request_bytes,
            exact_credential=credential,
        )

    assert credential not in str(raised.value)


def test_near_match_credential_is_not_treated_as_exact() -> None:
    credential = "vercel-secret-credential-ABC123"

    validate_provider_bound_safety(
        b"packet contains vercel-secret-credential-ABC124",
        b"request contains vercel-secret-credential-ABC12",
        exact_credential=credential,
    )


def test_prepared_request_body_tampering_is_rejected() -> None:
    prepared = prepare_ox_request(b"frozen packet")
    tampered = replace(prepared, body_bytes=prepared.body_bytes + b" ")

    with pytest.raises(ValueError, match="prepared request integrity is invalid"):
        validate_prepared_provider_request_integrity(tampered)


def test_prepared_request_identity_tampering_is_rejected() -> None:
    prepared = prepare_ox_request(b"frozen packet")
    tampered = replace(prepared, request_sha256="0" * 64)

    with pytest.raises(ValueError, match="prepared request integrity is invalid"):
        validate_prepared_provider_request_integrity(tampered)


def test_service_blocks_exact_credential_in_frozen_source_before_send(tmp_path: Path) -> None:
    credential = "vercel-secret-credential-SERVICE-BOUNDARY"
    projects = tmp_path / "projects"
    repository = projects / "repo"
    repository.mkdir(parents=True)
    (repository / "config.txt").write_text(
        f"credential-like test fixture: {credential}\n",
        encoding="utf-8",
    )
    evidence_root = tmp_path / "evidence"
    service = _service(projects, evidence_root, credential)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"unexpected", request=request)

    with pytest.raises(OXBundleError) as raised:
        asyncio.run(
            service.review(
                repository="repo",
                mode="FULL_REPOSITORY",
                paths=None,
                objective="Review the frozen repository.",
                transport=httpx.MockTransport(handler),
            )
        )

    assert calls == 0
    assert credential not in str(raised.value)
    review_dir = evidence_root / "reviews" / "OX-000001"
    assert (review_dir / "review.json").is_file()
    assert not (review_dir / "send.claim").exists()


def test_privacy_sentinel_matrix_keeps_restricted_evidence_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "OX-API-KEY-SENTINEL-7f4f"
    packet_source = "PACKET-SOURCE-SENTINEL-b5a6"
    excluded_secret = "EXCLUDED-SECRET-SENTINEL-a92e"
    raw_envelope = "RAW-PROVIDER-ENVELOPE-SENTINEL-42bd"
    proxy_value = "http://PROXY-VALUE-SENTINEL-731c.invalid:8080"
    projects = tmp_path / "projects"
    repository = projects / "privacy-repo"
    repository.mkdir(parents=True)
    (repository / "review_me.py").write_text(
        f"VALUE = {packet_source!r}\n",
        encoding="utf-8",
    )
    (repository / ".env").write_text(
        f"TOKEN={excluded_secret}\n",
        encoding="utf-8",
    )
    absolute_repository_path = str(repository.resolve())
    evidence_root = tmp_path / "evidence"
    service = _service(projects, evidence_root, api_key)
    monkeypatch.setenv("HTTPS_PROXY", proxy_value)
    seen_request: dict[str, object] = {}

    response_body = json.dumps(
        {
            "raw_debug": raw_envelope,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Review completed without sentinel leakage.",
                    }
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_request["authorization"] = request.headers.get("Authorization")
        seen_request["body"] = request.content
        return httpx.Response(200, content=response_body, request=request)

    transport = httpx.MockTransport(handler)

    class PublicService:
        async def review(self, **kwargs: object) -> dict[str, object]:
            return await service.review(**kwargs, transport=transport)

        def get_review(self, review_id: str) -> dict[str, object]:
            return service.get_review(review_id)

    monkeypatch.setattr(server, "ox_service", lambda: PublicService())

    public_review = asyncio.run(
        server.ox_review(
            repository="privacy-repo",
            mode="FULL_REPOSITORY",
            objective="Review the frozen repository.",
            paths=None,
        )
    )
    public_get = server.ox_get_review(public_review["review_id"])

    assert public_review["state"] == "COMPLETED"
    assert public_get == public_review
    assert seen_request["authorization"] == f"Bearer {api_key}"

    review_dir = evidence_root / "reviews" / public_review["review_id"]
    review_json = (review_dir / "review.json").read_text(encoding="utf-8")
    snapshot_json = (review_dir / "snapshot.json").read_text(encoding="utf-8")
    public_text = json.dumps(
        {"ox_review": public_review, "ox_get_review": public_get},
        sort_keys=True,
    )
    safe_surfaces = "\n".join((public_text, caplog.text, review_json, snapshot_json))

    for forbidden in (
        api_key,
        proxy_value,
        excluded_secret,
        absolute_repository_path,
        raw_envelope,
        packet_source,
    ):
        assert forbidden not in safe_surfaces

    packet_bytes = (review_dir / "packet.bin").read_bytes()
    request_bytes = (review_dir / "request.bin").read_bytes()
    response_bytes = (review_dir / "response.bin").read_bytes()

    assert packet_source.encode("utf-8") in packet_bytes
    assert packet_source.encode("utf-8") in request_bytes
    assert raw_envelope.encode("utf-8") in response_bytes
    assert response_bytes == response_body
    assert request_bytes == seen_request["body"]

    for restricted in (packet_bytes, request_bytes, response_bytes):
        for forbidden in (
            api_key,
            proxy_value,
            excluded_secret,
            absolute_repository_path,
        ):
            assert forbidden.encode("utf-8") not in restricted


def test_transport_exception_sentinel_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exception_sentinel = "TRANSPORT-EXCEPTION-SENTINEL-e8a4"
    prepared = prepare_ox_request(b"safe transport packet")
    context = ProviderTransmissionContext(
        provider_started_at=datetime.now(UTC).isoformat(),
        expected_request_sha256=prepared.request_sha256,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError(exception_sentinel, request=request)

    with pytest.raises(ProviderTransportError) as raised:
        asyncio.run(
            execute_ox_transport(
                prepared,
                context,
                api_key="safe-test-key",
                transport=httpx.MockTransport(handler),
            )
        )

    assert raised.value.attempt_outcome is ProviderAttemptOutcome.OUTCOME_UNKNOWN
    assert exception_sentinel not in str(raised.value)
    assert exception_sentinel not in repr(raised.value)
    assert exception_sentinel not in caplog.text


def test_ox_and_nvidia_imports_are_provider_isolated() -> None:
    ox_violations: list[str] = []
    for path in sorted(OX_SOURCE_ROOT.glob("*.py")):
        for module in sorted(_imported_modules(path)):
            if module.startswith(("byte_mcp.nvidia", "byte_mcp.wolfram", "mcp")):
                ox_violations.append(f"{path.as_posix()}: {module}")

    nvidia_violations: list[str] = []
    for path in sorted(NVIDIA_SOURCE_ROOT.rglob("*.py")):
        for module in sorted(_imported_modules(path)):
            if module.startswith("byte_mcp.ox"):
                nvidia_violations.append(f"{path.as_posix()}: {module}")

    assert ox_violations == []
    assert nvidia_violations == []


def test_provider_free_local_paths_never_open_network_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "NETWORK-GUARD-CREDENTIAL-97a4"
    projects = tmp_path / "projects"
    repository = projects / "repo"
    repository.mkdir(parents=True)
    evidence_root = tmp_path / "evidence"
    service = _service(projects, evidence_root, credential)
    monkeypatch.setenv("BYTE_MCP_OX_EVIDENCE_DIR", str(tmp_path / "runtime-evidence"))

    async def exercise() -> None:
        with _no_connections():
            with pytest.raises(OXRepositoryError):
                await service.review(
                    repository="../escape",
                    mode="FULL_REPOSITORY",
                    paths=None,
                    objective="Reject unsafe scope locally.",
                )

            oversized = repository / "oversized.txt"
            oversized.write_bytes(b"x" * (OX_MAX_ARTIFACT_BYTES + 1))
            with pytest.raises(OXBundleError):
                await service.review(
                    repository="repo",
                    mode="FULL_REPOSITORY",
                    paths=None,
                    objective="Reject oversized snapshot locally.",
                )
            oversized.unlink()

            (repository / "credential.txt").write_text(
                credential,
                encoding="utf-8",
            )
            with pytest.raises(OXBundleError):
                await service.review(
                    repository="repo",
                    mode="FULL_REPOSITORY",
                    paths=None,
                    objective="Reject provider-bound credential locally.",
                )

            projection = service.get_review("OX-000001")
            assert projection["state"] == "READY"

            runtime = OXRuntime.load(
                _settings(tmp_path),
                {"projects": projects},
            )
            assert runtime.require_service() is not None

    asyncio.run(exercise())


def test_redirects_are_rejected_without_followup_request() -> None:
    prepared = prepare_ox_request(b"redirect qualification packet")
    context = ProviderTransmissionContext(
        provider_started_at=datetime.now(UTC).isoformat(),
        expected_request_sha256=prepared.request_sha256,
    )
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://redirect-sentinel.invalid/next"},
            content=b"redirect not followed",
            request=request,
        )

    response = asyncio.run(
        execute_ox_transport(
            prepared,
            context,
            api_key="safe-test-key",
            transport=httpx.MockTransport(handler),
        )
    )

    assert response.outcome is ProviderAttemptOutcome.REJECTED
    assert response.status_code == 302
    assert len(calls) == 1
    assert calls[0].startswith("https://ai-gateway.vercel.sh/")


def test_prepared_ox_request_has_no_provider_tool_authority_or_wolfram_route() -> None:
    prepared = prepare_ox_request(b"tool-authority qualification packet")
    body = json.loads(prepared.body_bytes.decode("utf-8"))

    assert isinstance(body, dict)
    assert {"tools", "tool_choice", "functions", "function_call"}.isdisjoint(body)
    messages = body["messages"]
    assert isinstance(messages, list)
    assert all(isinstance(message, dict) for message in messages)
    assert all(message.get("role") != "tool" for message in messages)
    assert "wolfram" not in prepared.body_bytes.decode("utf-8").lower()
