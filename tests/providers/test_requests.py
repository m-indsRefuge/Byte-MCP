import hashlib
import json

import pytest

from byte_mcp.providers.requests import (
    MAX_PREPARED_BODY_BYTES,
    prepare_provider_request,
)


def _make_request(body: object, **overrides: object):
    values = {
        "provider_id": "nvidia-api-catalog",
        "method": "POST",
        "target_origin": "https://integrate.api.nvidia.com",
        "endpoint_path": "/v1/chat/completions",
        "model_id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "body": body,
    }
    values.update(overrides)
    return prepare_provider_request(**values)


def test_preparation_canonicalizes_exact_wire_bytes_and_hashes_them():
    prepared = _make_request({"z": 1, "a": "é"})
    expected = json.dumps(
        {"z": 1, "a": "é"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    assert prepared.body_bytes == expected
    assert prepared.payload_sha256 == hashlib.sha256(expected).hexdigest()


def test_request_hash_is_stable_for_equivalent_mapping_order():
    first = _make_request({"b": 2, "a": 1})
    second = _make_request({"a": 1, "b": 2})

    assert first.body_bytes == second.body_bytes
    assert first.request_sha256 == second.request_sha256


def test_request_hash_changes_when_body_or_destination_changes():
    original = _make_request({"value": 1})
    changed_body = _make_request({"value": 2})
    changed_path = _make_request({"value": 1}, endpoint_path="/v1/other")

    assert original.request_sha256 != changed_body.request_sha256
    assert original.request_sha256 != changed_path.request_sha256


def test_repr_omits_request_body_content():
    prepared = _make_request({"messages": [{"content": "TOP SECRET"}]})

    text = repr(prepared)
    assert "TOP SECRET" not in text
    assert prepared.request_sha256 in text
    assert prepared.payload_sha256 in text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "NVIDIA"),
        ("method", "GET"),
        ("target_origin", "http://integrate.api.nvidia.com"),
        ("target_origin", "https://integrate.api.nvidia.com/v1"),
        ("endpoint_path", "v1/chat/completions"),
        ("endpoint_path", "/v1/chat/completions?x=1"),
        ("endpoint_path", "/v1/chat completions"),
        ("model_id", "not-a-model-id"),
    ],
)
def test_invalid_request_identity_fields_fail_closed(field: str, value: object):
    with pytest.raises(ValueError):
        _make_request({"value": 1}, **{field: value})


def test_invalid_json_values_fail_before_request_creation():
    with pytest.raises(ValueError, match="canonical JSON"):
        _make_request({"temperature": float("nan")})

    with pytest.raises(ValueError, match="canonical JSON"):
        _make_request({"value": object()})


def test_body_bound_is_enforced_before_transport():
    with pytest.raises(ValueError, match="prepared request body exceeds limit"):
        _make_request({"content": "x" * MAX_PREPARED_BODY_BYTES})
