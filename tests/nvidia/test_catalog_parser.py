import pytest

from byte_mcp.nvidia.catalog import NvidiaCatalogSnapshot, parse_catalog_payload
from byte_mcp.nvidia.errors import NvidiaCatalogError, NvidiaCatalogFailureKind

OBSERVED_AT = "2026-09-08T00:00:00+00:00"


def test_parser_returns_only_bounded_model_ids():
    payload = {
        "object": "list",
        "data": [
            {
                "id": "nvidia/nemotron-3.5-lightning-30b-a3b",
                "object": "model",
                "owned_by": "ignored",
                "arbitrary": {"nested": "ignored"},
            },
            {"id": "deepseek-ai/deepseek-v4-pro-0813", "object": "model"},
        ],
        "secret-looking-field": "must-not-propagate",
    }
    snapshot = parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert snapshot == NvidiaCatalogSnapshot(
        model_ids=(
            "deepseek-ai/deepseek-v4-pro-0813",
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        ),
        observed_at=OBSERVED_AT,
    )
    assert "owned_by" not in repr(snapshot)
    assert "secret-looking-field" not in repr(snapshot)


def test_parser_deduplicates_model_ids_deterministically():
    payload = {
        "data": [
            {"id": "nvidia/example-model"},
            {"id": "nvidia/example-model"},
        ]
    }
    snapshot = parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert snapshot.model_ids == ("nvidia/example-model",)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"data": "not-a-list"},
        {"data": ["not-an-object"]},
        {"data": [{}]},
        {"data": [{"id": "bad model id"}]},
    ],
)
def test_parser_fails_closed_on_malformed_envelopes(payload):
    with pytest.raises(NvidiaCatalogError) as excinfo:
        parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL


def test_parser_rejects_more_than_1000_models():
    payload = {"data": [{"id": f"nvidia/model-{index}"} for index in range(1001)]}
    with pytest.raises(NvidiaCatalogError) as excinfo:
        parse_catalog_payload(payload, observed_at=OBSERVED_AT)
    assert excinfo.value.kind is NvidiaCatalogFailureKind.PROTOCOL
