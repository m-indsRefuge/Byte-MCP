"""Deterministic review packets and provider request preparation for OX."""

from __future__ import annotations

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.models import OXReviewScope, OXSnapshot
from byte_mcp.ox.settings import (
    OX_MAX_PACKET_BYTES,
    OX_MODEL_ID,
    OX_PACKET_POLICY_VERSION,
    OX_SNAPSHOT_POLICY_VERSION,
)
from byte_mcp.providers.requests import PreparedProviderRequest, prepare_provider_request

SYSTEM_PROMPT = (
    "You are OX, an independent adversarial code reviewer. "
    "Review only the frozen repository material supplied in the user message. "
    "Check correctness, security, reliability, regression risk, architecture, edge cases, "
    "and testing. Respond naturally as a technical reviewer in free-form prose."
)

_TARGET_ORIGIN = "https://ai-gateway.vercel.sh"
_ENDPOINT_PATH = "/v1/chat/completions"
_PRIVATE_KEY_MARKERS = (
    b"BEGIN PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN EC PRIVATE KEY",
    b"BEGIN OPENSSH PRIVATE KEY",
)


def _encode_text(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise OXBundleError("OX packet text is not valid UTF-8.") from exc


def _append_bounded(buffer: bytearray, value: bytes) -> None:
    if len(buffer) + len(value) > OX_MAX_PACKET_BYTES:
        raise OXBundleError("OX review packet exceeds the configured hard limit.")
    buffer.extend(value)


def _append_text(buffer: bytearray, value: str) -> None:
    _append_bounded(buffer, _encode_text(value))


def _validate_scope_snapshot(scope: OXReviewScope, snapshot: OXSnapshot) -> None:
    if not isinstance(scope, OXReviewScope) or not isinstance(snapshot, OXSnapshot):
        raise OXBundleError("OX packet scope or snapshot is invalid.")
    if (
        scope.repository != snapshot.repository
        or scope.mode is not snapshot.mode
        or scope.paths != snapshot.requested_paths
    ):
        raise OXBundleError("OX packet scope and snapshot identity do not match.")
    if snapshot.policy_version != OX_SNAPSHOT_POLICY_VERSION:
        raise OXBundleError("OX snapshot policy version is not reviewable.")


def validate_provider_bound_safety(
    packet_bytes: bytes,
    request_bytes: bytes,
    *,
    exact_credential: str | None,
) -> None:
    """Fail closed if frozen provider-bound bytes contain strong secret indicators."""
    if not isinstance(packet_bytes, bytes) or not isinstance(request_bytes, bytes):
        raise OXBundleError("OX provider-bound safety input is invalid.")

    provider_bound = (packet_bytes, request_bytes)
    if any(marker in material for marker in _PRIVATE_KEY_MARKERS for material in provider_bound):
        raise OXBundleError("OX provider-bound material failed the local safety scan.")

    if exact_credential is None:
        return
    if not isinstance(exact_credential, str) or not exact_credential:
        raise OXBundleError("OX provider-bound safety input is invalid.")
    try:
        credential_bytes = exact_credential.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise OXBundleError("OX provider-bound safety input is invalid.") from exc

    if any(credential_bytes in material for material in provider_bound):
        raise OXBundleError("OX provider-bound material failed the local safety scan.")


def build_review_packet(scope: OXReviewScope, snapshot: OXSnapshot) -> bytes:
    """Build one deterministic provider-bound packet from a frozen snapshot."""
    _validate_scope_snapshot(scope, snapshot)

    packet = bytearray()
    _append_text(packet, "OX REVIEW PACKET\n")
    _append_text(packet, f"PACKET_POLICY: {OX_PACKET_POLICY_VERSION}\n")
    _append_text(packet, f"REPOSITORY: {scope.repository}\n")
    _append_text(packet, f"MODE: {scope.mode.value}\n")
    _append_text(packet, "REQUESTED_PATHS:\n")
    if scope.paths:
        for logical_path in scope.paths:
            _append_text(packet, f"- {logical_path}\n")
    else:
        _append_text(packet, "- (full repository)\n")
    _append_text(packet, f"SNAPSHOT_POLICY: {snapshot.policy_version}\n")
    _append_text(packet, f"SNAPSHOT_SHA256: {snapshot.snapshot_sha256}\n")
    _append_text(packet, f"ARTIFACT_COUNT: {len(snapshot.artifacts)}\n")
    _append_text(packet, f"EXCLUSION_COUNT: {len(snapshot.exclusions)}\n")
    _append_text(packet, f"TOTAL_CONTENT_BYTES: {snapshot.total_content_bytes}\n")
    _append_text(packet, "OBJECTIVE:\n")
    _append_text(packet, scope.objective)
    _append_text(packet, "\nEXCLUSIONS:\n")

    exclusions = sorted(
        snapshot.exclusions,
        key=lambda item: (item.logical_path, item.reason),
    )
    if exclusions:
        for exclusion in exclusions:
            _append_text(packet, f"- {exclusion.logical_path} :: {exclusion.reason}\n")
    else:
        _append_text(packet, "- none\n")

    _append_text(packet, "\nFROZEN_ARTIFACTS:\n")
    for artifact in sorted(snapshot.artifacts, key=lambda item: item.logical_path):
        try:
            artifact.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise OXBundleError("OX packet contains a non-text artifact.") from exc

        _append_text(packet, f"\n--- FILE: {artifact.logical_path} ---\n")
        _append_text(packet, f"BYTE_LENGTH: {artifact.byte_length}\n")
        _append_text(packet, f"CONTENT_SHA256: {artifact.content_sha256}\n")
        _append_text(packet, f"CLASSIFICATION: {artifact.classification}\n")
        git_state = artifact.git_state if artifact.git_state is not None else "none"
        _append_text(packet, f"GIT_STATE: {git_state}\n")
        _append_text(packet, "CONTENT:\n")
        _append_bounded(packet, artifact.content)
        if not artifact.content.endswith(b"\n"):
            _append_text(packet, "\n")
        _append_text(packet, "--- END FILE ---\n")

    return bytes(packet)


def prepare_ox_request(packet_bytes: bytes) -> PreparedProviderRequest:
    """Freeze the exact canonical provider request authority for one OX packet."""
    if not isinstance(packet_bytes, bytes) or not packet_bytes:
        raise OXBundleError("OX review packet is invalid.")
    if len(packet_bytes) > OX_MAX_PACKET_BYTES:
        raise OXBundleError("OX review packet exceeds the configured hard limit.")
    try:
        packet_text = packet_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise OXBundleError("OX review packet is not valid UTF-8.") from exc

    body = {
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
    try:
        return prepare_provider_request(
            provider_id="ox",
            method="POST",
            target_origin=_TARGET_ORIGIN,
            endpoint_path=_ENDPOINT_PATH,
            model_id=OX_MODEL_ID,
            body=body,
        )
    except ValueError as exc:
        raise OXBundleError("OX provider request could not be prepared safely.") from exc
