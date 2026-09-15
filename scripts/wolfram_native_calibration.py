"""Live MCP-only calibration for Byte-mediated Wolfram-native queries."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from byte_mcp.wolfram.native_calibration import (
    NATIVE_CALIBRATION_CASES,
    assess_native_result,
    native_call_arguments,
)


def _payload(result: Any) -> dict[str, Any]:
    is_error = bool(
        getattr(result, "isError", False)
        or getattr(result, "is_error", False)
    )
    if is_error:
        raise RuntimeError("MCP wolfram_query returned an error.")

    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured

    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if not text:
            continue
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError("MCP wolfram_query returned no structured JSON object.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed Byte-mediated Wolfram-native MCP calibration.",
    )
    parser.add_argument(
        "--url",
        default=os.getenv(
            "BYTE_MCP_URL",
            "http://127.0.0.1:8000/mcp",
        ),
    )
    parser.add_argument("--max-chars", type=int, default=3000)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "classification": "successful_validation",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "endpoint": args.url,
        "case_count": len(NATIVE_CALIBRATION_CASES),
        "checks": [],
    }

    async with (
        streamable_http_client(args.url) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        tools_result = await session.list_tools()
        tool_names = {tool.name for tool in tools_result.tools}
        if "wolfram_query" not in tool_names:
            raise RuntimeError("MCP discovery did not contain wolfram_query.")

        for case in NATIVE_CALIBRATION_CASES:
            result = await session.call_tool(
                "wolfram_query",
                arguments=native_call_arguments(
                    case,
                    max_chars=args.max_chars,
                ),
            )
            payload = _payload(result)
            evidence["checks"].append(
                assess_native_result(case, payload),
            )

    return evidence


def main() -> None:
    args = _parse_args()
    try:
        evidence = asyncio.run(_run(args))
    except Exception as exc:
        failure = {
            "classification": "failed_validation",
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "endpoint": args.url,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(failure, indent=2, sort_keys=True))
        raise SystemExit(1) from exc

    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
