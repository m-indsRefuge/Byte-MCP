from __future__ import annotations

from dataclasses import replace

import pytest

from byte_mcp.errors import OXBundleError
from byte_mcp.ox.packet import prepare_ox_request, validate_provider_bound_safety
from byte_mcp.providers.requests import validate_prepared_provider_request_integrity

_PRIVATE_KEY_MARKERS = (
    b"BEGIN PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN EC PRIVATE KEY",
    b"BEGIN OPENSSH PRIVATE KEY",
)


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
