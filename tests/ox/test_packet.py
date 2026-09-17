from __future__ import annotations

import hashlib
import json

import pytest

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.models import (
    OXArtifact,
    OXReviewMode,
    OXReviewScope,
    OXSnapshot,
    OXSnapshotExclusion,
)
from byte_mcp.ox.packet import SYSTEM_PROMPT, build_review_packet, prepare_ox_request
from byte_mcp.ox.settings import (
    OX_MAX_PACKET_BYTES,
    OX_MODEL_ID,
    OX_PACKET_POLICY_VERSION,
    OX_SNAPSHOT_POLICY_VERSION,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact(path: str, content: bytes) -> OXArtifact:
    return OXArtifact(
        logical_path=path,
        content=content,
        byte_length=len(content),
        content_sha256=_sha256(content),
        classification="text/utf-8",
        git_state=None,
    )


def _scope() -> OXReviewScope:
    return OXReviewScope(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        paths=("src", "tests"),
        objective="Review the retry boundary and its regression coverage.",
    )


def _snapshot(*, artifacts: tuple[OXArtifact, ...] | None = None) -> OXSnapshot:
    included = artifacts or (
        _artifact("tests/test_worker.py", b"def test_worker():\n    assert True\n"),
        _artifact("src/worker.py", "VALUE = 'caf\u00e9'\n".encode()),
    )
    return OXSnapshot(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        requested_paths=("src", "tests"),
        policy_version=OX_SNAPSHOT_POLICY_VERSION,
        artifacts=included,
        exclusions=(
            OXSnapshotExclusion(
                logical_path="src/private.pem",
                reason="sensitive-key-material",
            ),
        ),
        total_content_bytes=sum(artifact.byte_length for artifact in included),
        snapshot_sha256=_sha256(b"snapshot-identity"),
    )


def test_build_review_packet_is_deterministic_and_uses_exact_frozen_text() -> None:
    scope = _scope()
    snapshot = _snapshot()

    first = build_review_packet(scope, snapshot)
    second = build_review_packet(scope, snapshot)

    assert first == second
    assert first.startswith(b"OX REVIEW PACKET\n")
    assert f"PACKET_POLICY: {OX_PACKET_POLICY_VERSION}\n".encode() in first
    assert b"REPOSITORY: example\n" in first
    assert b"MODE: BOUNDED\n" in first
    assert b"REQUESTED_PATHS:\n- src\n- tests\n" in first
    assert f"SNAPSHOT_SHA256: {snapshot.snapshot_sha256}\n".encode() in first
    assert b"OBJECTIVE:\nReview the retry boundary and its regression coverage.\n" in first
    assert b"EXCLUSIONS:\n- src/private.pem :: sensitive-key-material\n" in first

    src_marker = b"--- FILE: src/worker.py ---\n"
    tests_marker = b"--- FILE: tests/test_worker.py ---\n"
    assert first.count(src_marker) == 1
    assert first.count(tests_marker) == 1
    assert first.index(src_marker) < first.index(tests_marker)
    assert b"VALUE = 'caf\xc3\xa9'\n" in first
    assert b"def test_worker():\n    assert True\n" in first

    lowered = first.lower()
    assert b"json response" not in lowered
    assert b"structured output" not in lowered
    assert b"c:\\" not in lowered
    assert b"/home/runner/" not in lowered


def test_build_review_packet_rejects_scope_snapshot_identity_mismatch() -> None:
    scope = OXReviewScope(
        repository="other",
        mode=OXReviewMode.BOUNDED,
        paths=("src", "tests"),
        objective="Review the current implementation.",
    )

    with pytest.raises(OXBundleError):
        build_review_packet(scope, _snapshot())


def test_build_review_packet_rejects_packet_over_hard_limit() -> None:
    oversized = _artifact("src/huge.txt", b"x" * OX_MAX_PACKET_BYTES)

    with pytest.raises(OXBundleError):
        build_review_packet(_scope(), _snapshot(artifacts=(oversized,)))


def test_prepare_ox_request_uses_exact_canonical_provider_body() -> None:
    packet_bytes = build_review_packet(_scope(), _snapshot())

    prepared = prepare_ox_request(packet_bytes)
    packet_text = packet_bytes.decode("utf-8")
    expected_body = {
        "model": OX_MODEL_ID,
        "stream": False,
        "max_tokens": 65536,
        "reasoning": {"effort": "medium"},
        "providerOptions": {"gateway": {"only": ["zai"]}},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": packet_text},
        ],
    }
    expected_body_bytes = json.dumps(
        expected_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    assert prepared.provider_id == "ox"
    assert prepared.method == "POST"
    assert prepared.target_origin == "https://ai-gateway.vercel.sh"
    assert prepared.endpoint_path == "/v1/chat/completions"
    assert prepared.model_id == OX_MODEL_ID
    assert prepared.body_bytes == expected_body_bytes
    assert prepared.payload_sha256 == _sha256(expected_body_bytes)
    assert packet_bytes in prepared.body_bytes
    assert "independent adversarial code reviewer" in SYSTEM_PROMPT
    assert "only the frozen repository material" in SYSTEM_PROMPT
    assert "correctness" in SYSTEM_PROMPT
    assert "security" in SYSTEM_PROMPT
    assert "reliability" in SYSTEM_PROMPT
    assert "regression" in SYSTEM_PROMPT
    assert "architecture" in SYSTEM_PROMPT
    assert "edge cases" in SYSTEM_PROMPT
    assert "testing" in SYSTEM_PROMPT
    assert "Respond naturally" in SYSTEM_PROMPT


def test_prepare_ox_request_rejects_non_utf8_or_oversized_packet() -> None:
    with pytest.raises(OXBundleError):
        prepare_ox_request(b"\xff")

    with pytest.raises(OXBundleError):
        prepare_ox_request(b"x" * (OX_MAX_PACKET_BYTES + 1))
