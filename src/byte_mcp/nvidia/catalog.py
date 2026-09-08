"""Bounded NVIDIA hosted model-catalog parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from byte_mcp.providers.models import validate_model_id

from .errors import NvidiaCatalogError, NvidiaCatalogFailureKind

_MAX_CATALOG_BYTES = 1_000_000
_MAX_CATALOG_MODELS = 1_000


@dataclass(frozen=True, slots=True)
class NvidiaCatalogSnapshot:
    model_ids: tuple[str, ...]
    observed_at: str


def _protocol_error() -> NvidiaCatalogError:
    return NvidiaCatalogError(NvidiaCatalogFailureKind.PROTOCOL)


def parse_catalog_payload(
    payload: object,
    *,
    observed_at: str,
) -> NvidiaCatalogSnapshot:
    if not isinstance(payload, Mapping):
        raise _protocol_error()
    data = payload.get("data")
    if not isinstance(data, list) or len(data) > _MAX_CATALOG_MODELS:
        raise _protocol_error()

    model_ids: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            raise _protocol_error()
        try:
            model_id = validate_model_id(item.get("id"))
        except ValueError:
            raise _protocol_error() from None
        model_ids.add(model_id)

    try:
        parsed_time = datetime.fromisoformat(observed_at)
    except (TypeError, ValueError):
        raise _protocol_error() from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise _protocol_error()

    return NvidiaCatalogSnapshot(
        model_ids=tuple(sorted(model_ids)),
        observed_at=observed_at,
    )
