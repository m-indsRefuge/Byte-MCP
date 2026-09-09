import hashlib
import json

import pytest

from byte_mcp.providers import (
    MAX_PREPARED_BODY_BYTES,
    PreparedProviderRequest,
    prepare_provider_request,
)


def _prepare(**overrides: object) -> PreparedProviderRequest:
    values: dict[str, object] = {
        "provider_id": "nvidia",
        "method": "POST",
        "target_origin": "https://api.example.com",
        "endpoint_path": "/v1/chat/completions",
        "model_id": "nvidia/llama-3.1",
        "body": {"z": 1, "a": "é"},
    }
    values.update(overrides)
    return prepare_provider_request(**values)


def test_body_is_canonical_utf8_json_with_sorted_keys() -> None:
    prepared = _prepare()
    expected = json.dumps(
        {"z": 1, "a": "é"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert prepared.body_bytes == expected
    assert prepared.payload_sha256 == hashlib.sha256(expected).hexdigest()


def test_request_identity_is_stable_and_changes_for_body_or_destination() -> None:
    first = _prepare()
    second = _prepare()
    assert first == second
    assert first.request_sha256 == second.request_sha256
    assert _prepare(body={"z": 2, "a": "é"}).request_sha256 != first.request_sha256
    assert _prepare(endpoint_path="/v1/other").request_sha256 != first.request_sha256


def test_request_is_immutable_and_repr_does_not_include_body_bytes() -> None:
    prepared = _prepare()
    with pytest.raises(AttributeError):
        prepared.method = "GET"  # type: ignore[misc]
    assert "body_bytes" not in repr(prepared)
    assert repr(prepared.body_bytes) not in repr(prepared)


@pytest.mark.parametrize("body", [float("nan"), float("inf"), float("-inf")])
def test_invalid_json_numbers_are_rejected(body: object) -> None:
    with pytest.raises(ValueError):
        _prepare(body=body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "NVIDIA"),
        ("provider_id", ""),
        ("model_id", "llama-3.1"),
        ("target_origin", "http://api.example.com"),
        ("target_origin", "https://api.example.com/v1"),
        ("target_origin", "https://api.example.com?x=1"),
        ("endpoint_path", "v1/chat"),
        ("endpoint_path", "/v1/chat?x=1"),
        ("endpoint_path", "/v1/chat\nmore"),
        ("endpoint_path", "/v1/chat more"),
        ("method", "GET"),
    ],
)
def test_invalid_request_metadata_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _prepare(**{field: value})


def test_prepared_body_size_is_bounded() -> None:
    with pytest.raises(ValueError):
        _prepare(body="x" * MAX_PREPARED_BODY_BYTES)
