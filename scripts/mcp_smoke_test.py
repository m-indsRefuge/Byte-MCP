"""Repeatable Byte-MCP Streamable HTTP client smoke test."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = frozenset(
    {
        "list_roots",
        "list_directory",
        "search",
        "fetch",
    }
)


def _payload(result: Any) -> dict[str, Any]:
    is_error = bool(
        getattr(result, "isError", False)
        or getattr(result, "is_error", False)
    )
    if is_error:
        raise RuntimeError(f"MCP tool returned an error: {result}")

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

    raise RuntimeError("MCP tool result contained no structured JSON object.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Byte-MCP discovery and optional search/fetch flow."
    )
    parser.add_argument(
        "--url",
        default=os.getenv(
            "BYTE_MCP_URL",
            "http://127.0.0.1:8000/mcp",
        ),
    )
    parser.add_argument("--root", default="downloads")
    parser.add_argument("--query")
    parser.add_argument("--expect-name")
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=5000)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "classification": "successful_validation",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "endpoint": args.url,
        "checks": {},
    }

    async with streamable_http_client(args.url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tool_names = {tool.name for tool in tools_result.tools}
            missing = sorted(EXPECTED_TOOLS - tool_names)
            if missing:
                raise RuntimeError(f"Missing expected MCP tools: {missing}")

            evidence["checks"]["tool_discovery"] = {
                "status": "pass",
                "tools": sorted(tool_names),
            }

            roots_result = await session.call_tool(
                "list_roots",
                arguments={},
            )
            roots_payload = _payload(roots_result)
            root_aliases = {
                root["alias"]
                for root in roots_payload.get("roots", [])
                if isinstance(root, dict) and "alias" in root
            }
            if args.root not in root_aliases:
                raise RuntimeError(
                    f"Requested smoke-test root is not approved: {args.root}"
                )

            evidence["checks"]["list_roots"] = {
                "status": "pass",
                "mode": roots_payload.get("mode"),
                "root_aliases": sorted(root_aliases),
            }

            if args.query:
                search_result = await session.call_tool(
                    "search",
                    arguments={
                        "query": args.query,
                        "root": args.root,
                        "max_results": args.max_results,
                        "search_contents": False,
                    },
                )
                search_payload = _payload(search_result)
                results = search_payload.get("results", [])
                if not results:
                    raise RuntimeError(
                        f"Search returned no results for query: {args.query!r}"
                    )

                selected = None
                if args.expect_name:
                    selected = next(
                        (
                            item
                            for item in results
                            if item.get("name") == args.expect_name
                        ),
                        None,
                    )
                    if selected is None:
                        raise RuntimeError(
                            "Search did not return the expected file: "
                            f"{args.expect_name}"
                        )
                else:
                    selected = results[0]

                reference = selected.get("ref")
                if not isinstance(reference, str) or not reference:
                    raise RuntimeError("Search result did not contain a valid ref.")

                evidence["checks"]["search"] = {
                    "status": "pass",
                    "result_count": len(results),
                    "selected_name": selected.get("name"),
                    "scanned_files": search_payload.get("scanned_files"),
                }

                fetch_result = await session.call_tool(
                    "fetch",
                    arguments={
                        "reference": reference,
                        "max_chars": args.max_chars,
                    },
                )
                fetch_payload = _payload(fetch_result)
                sha256 = fetch_payload.get("sha256")
                if not isinstance(sha256, str) or len(sha256) != 64:
                    raise RuntimeError("Fetch result did not contain a SHA-256.")

                evidence["checks"]["fetch"] = {
                    "status": "pass",
                    "name": fetch_payload.get("name"),
                    "size_bytes": fetch_payload.get("size_bytes"),
                    "sha256": sha256,
                    "extractor": fetch_payload.get("extractor"),
                    "content_truncated": fetch_payload.get(
                        "content_truncated"
                    ),
                }

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
