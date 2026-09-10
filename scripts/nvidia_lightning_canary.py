"""Narrow operator CLI for the governed NVIDIA Nemotron Lightning canary."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence

from byte_mcp.nvidia.canary import (
    NvidiaCanaryInspection,
    NvidiaCanaryPrepareReceipt,
    NvidiaCanaryTransmissionResult,
    inspect_lightning_canary,
    prepare_lightning_canary,
    transmit_lightning_canary,
)
from byte_mcp.nvidia.canary_evidence import (
    NVIDIA_CANARY_ID_PATTERN,
    NvidiaCanaryEvidenceStore,
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _canary_id(value: str) -> str:
    if re.fullmatch(NVIDIA_CANARY_ID_PATTERN, value) is None:
        raise argparse.ArgumentTypeError("expected canary ID NVC-000000")
    return value


def _sha256(value: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected lowercase 64-hex SHA-256")
    return value


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


def _prepare_payload(receipt: NvidiaCanaryPrepareReceipt) -> dict[str, object]:
    return {
        "canary_id": receipt.canary_id,
        "provider_id": receipt.provider_id,
        "model_id": receipt.model_id,
        "payload_sha256": receipt.payload_sha256,
        "request_sha256": receipt.request_sha256,
        "body_bytes": receipt.body_bytes,
        "prepared_at": receipt.prepared_at,
        "evidence_root": receipt.evidence_root,
    }


def _inspection_payload(inspection: NvidiaCanaryInspection) -> dict[str, object]:
    return {
        "canary_id": inspection.canary_id,
        "provider_id": inspection.provider_id,
        "model_id": inspection.model_id,
        "payload_sha256": inspection.payload_sha256,
        "request_sha256": inspection.request_sha256,
        "body_bytes": inspection.body_bytes,
        "prepared_at": inspection.prepared_at,
        "probe_text": inspection.probe_text,
        "provider_started_at": inspection.provider_started_at,
        "has_terminal_event": inspection.has_terminal_event,
    }


def _transmission_payload(result: NvidiaCanaryTransmissionResult) -> dict[str, object]:
    return {
        "canary_id": result.canary_id,
        "request_sha256": result.request_sha256,
        "attempt_outcome": result.attempt_outcome.value,
        "model_id": result.model_id,
        "semantic_probe_match": result.semantic_probe_match,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the fixed governed NVIDIA Nemotron Lightning canary."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("prepare")

    inspect = subcommands.add_parser("inspect")
    inspect.add_argument("--canary-id", type=_canary_id, required=True)

    transmit = subcommands.add_parser("transmit")
    transmit.add_argument("--canary-id", type=_canary_id, required=True)
    transmit.add_argument(
        "--expected-request-sha256",
        type=_sha256,
        required=True,
    )
    transmit.add_argument("--approve", action="store_true", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        store = NvidiaCanaryEvidenceStore.from_environment()
        if args.command == "prepare":
            payload = _prepare_payload(prepare_lightning_canary(store))
        elif args.command == "inspect":
            payload = _inspection_payload(inspect_lightning_canary(store, args.canary_id))
        else:
            result = asyncio.run(
                transmit_lightning_canary(
                    store,
                    canary_id=args.canary_id,
                    expected_request_sha256=args.expected_request_sha256,
                    approve=args.approve,
                )
            )
            payload = _transmission_payload(result)
    except Exception as exc:
        _emit({"error_type": type(exc).__name__}, error=True)
        return 1

    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
