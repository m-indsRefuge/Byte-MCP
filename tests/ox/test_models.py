from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from byte_mcp.ox.models import (
    OXArtifact,
    OXPreparedReview,
    OXReviewMode,
    OXReviewScope,
    OXReviewState,
    OXSnapshot,
    OXSnapshotExclusion,
)
from byte_mcp.ox.settings import (
    OX_GATEWAY_URL,
    OX_MAX_ARTIFACT_BYTES,
    OX_MAX_ARTIFACTS,
    OX_MAX_PACKET_BYTES,
    OX_MAX_SNAPSHOT_CONTENT_BYTES,
    OX_MODEL_ID,
    OX_PACKET_POLICY_VERSION,
    OX_REVIEW_ID_PREFIX,
    OX_SNAPSHOT_POLICY_VERSION,
    OX_TIMEOUT_POLICY,
    OXSettings,
)
from byte_mcp.providers.requests import prepare_provider_request


def _artifact(path: str = "src/example.py", content: bytes = b"print('ok')\n") -> OXArtifact:
    return OXArtifact(
        logical_path=path,
        content=content,
        byte_length=len(content),
        content_sha256=sha256(content).hexdigest(),
        classification="text/utf-8",
        git_state="modified",
    )


def _snapshot(artifact: OXArtifact) -> OXSnapshot:
    return OXSnapshot(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        requested_paths=("src",),
        policy_version=OX_SNAPSHOT_POLICY_VERSION,
        artifacts=(artifact,),
        exclusions=(OXSnapshotExclusion(".env", "sensitive-path"),),
        total_content_bytes=artifact.byte_length,
        snapshot_sha256="0" * 64,
    )


def test_review_mode_and_state_vocabularies_are_closed() -> None:
    assert {member.value for member in OXReviewMode} == {"FULL_REPOSITORY", "BOUNDED"}
    assert {member.value for member in OXReviewState} == {
        "READY",
        "COMPLETED",
        "FAILED",
        "OUTCOME_UNKNOWN",
    }


def test_scope_is_frozen_and_requires_normalized_relative_paths() -> None:
    scope = OXReviewScope(
        repository="example",
        mode=OXReviewMode.BOUNDED,
        paths=("src/example.py",),
        objective="Review current behavior",
    )

    with pytest.raises(FrozenInstanceError):
        scope.objective = "changed"  # type: ignore[misc]

    for invalid in ("", "/absolute", "../escape", "src\\windows.py", "src/../escape"):
        with pytest.raises(ValueError):
            OXReviewScope(
                repository="example",
                mode=OXReviewMode.BOUNDED,
                paths=(invalid,),
                objective="Review current behavior",
            )


def test_scope_mode_path_contract_and_objective_validation() -> None:
    with pytest.raises(ValueError):
        OXReviewScope("example", OXReviewMode.FULL_REPOSITORY, ("src",), "Review")
    with pytest.raises(ValueError):
        OXReviewScope("example", OXReviewMode.BOUNDED, (), "Review")
    with pytest.raises(ValueError):
        OXReviewScope("example", OXReviewMode.BOUNDED, ("src",), "   ")


def test_artifact_binds_exact_content_identity_and_hides_bytes_from_repr() -> None:
    artifact = _artifact()
    assert artifact.byte_length == len(artifact.content)
    assert artifact.content_sha256 == sha256(artifact.content).hexdigest()
    assert "print('ok')" not in repr(artifact)

    with pytest.raises(ValueError):
        OXArtifact(
            logical_path="src/example.py",
            content=b"abc",
            byte_length=2,
            content_sha256=sha256(b"abc").hexdigest(),
            classification="text/utf-8",
            git_state=None,
        )


def test_snapshot_binds_counts_and_hides_frozen_content_from_repr() -> None:
    artifact = _artifact()
    snapshot = _snapshot(artifact)
    assert snapshot.total_content_bytes == artifact.byte_length
    assert "print('ok')" not in repr(snapshot)

    with pytest.raises(ValueError):
        OXSnapshot(
            repository="example",
            mode=OXReviewMode.BOUNDED,
            requested_paths=("src",),
            policy_version=OX_SNAPSHOT_POLICY_VERSION,
            artifacts=(artifact,),
            exclusions=(),
            total_content_bytes=artifact.byte_length + 1,
            snapshot_sha256="0" * 64,
        )


def test_prepared_review_hides_packet_and_request_bytes_from_repr() -> None:
    artifact = _artifact()
    scope = OXReviewScope("example", OXReviewMode.BOUNDED, ("src",), "Review")
    snapshot = _snapshot(artifact)
    packet = b"frozen packet"
    request = prepare_provider_request(
        provider_id="ox",
        method="POST",
        target_origin="https://ai-gateway.vercel.sh",
        endpoint_path="/v1/chat/completions",
        model_id=OX_MODEL_ID,
        body={"packet": packet.decode("utf-8")},
    )
    prepared = OXPreparedReview(
        review_id="OX-000001",
        scope=scope,
        snapshot=snapshot,
        packet_bytes=packet,
        packet_sha256=sha256(packet).hexdigest(),
        prepared_request=request,
    )

    rendered = repr(prepared)
    assert "frozen packet" not in rendered
    assert request.body_bytes.decode("utf-8") not in rendered


def test_fixed_initial_product_bounds_match_frozen_plan() -> None:
    assert OX_REVIEW_ID_PREFIX == "OX-"
    assert OX_GATEWAY_URL == "https://ai-gateway.vercel.sh/v1/chat/completions"
    assert OX_MODEL_ID == "zai/glm-5.3-flash"
    assert OX_SNAPSHOT_POLICY_VERSION == "ox-snapshot-v1"
    assert OX_PACKET_POLICY_VERSION == "ox-packet-v1"
    assert OX_MAX_ARTIFACT_BYTES == 1_000_000
    assert OX_MAX_ARTIFACTS == 5_000
    assert OX_MAX_SNAPSHOT_CONTENT_BYTES == 3_250_000
    assert OX_MAX_PACKET_BYTES == 3_500_000
    assert OX_TIMEOUT_POLICY.connect_seconds == 10.0
    assert OX_TIMEOUT_POLICY.write_seconds == 30.0
    assert OX_TIMEOUT_POLICY.read_seconds == 600.0
    assert OX_TIMEOUT_POLICY.pool_seconds == 10.0
    assert OX_TIMEOUT_POLICY.absolute_deadline_seconds == 600.0


def test_settings_loads_credential_lazily_and_repr_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = "secret-value-that-must-not-render"
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("AI_GATEWAY_API_KEY", sentinel)
    monkeypatch.setenv("BYTE_MCP_OX_EVIDENCE_DIR", str(evidence))

    settings = OXSettings.load()

    assert settings.api_key == sentinel
    assert settings.evidence_root == evidence.resolve()
    assert sentinel not in repr(settings)
    assert "configured=True" in repr(settings)
