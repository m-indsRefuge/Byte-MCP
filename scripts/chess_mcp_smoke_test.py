"""Repeatable live smoke test for the isolated Byte-MCP chess server."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = frozenset(
    {
        "chess_get_turn",
        "chess_get_match",
        "chess_get_events",
        "chess_submit_move",
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
        description=(
            "Validate isolated chess tool discovery, bound-match reads, and an "
            "optional idempotent live move submission."
        )
    )
    parser.add_argument(
        "--url",
        default=os.getenv(
            "BYTE_MCP_CHESS_URL",
            "http://127.0.0.1:8001/mcp",
        ),
    )
    parser.add_argument("--expected-match-id")
    parser.add_argument("--after-sequence", type=int, default=-1)
    parser.add_argument("--move-uci")
    parser.add_argument("--expected-state-version", type=int)
    parser.add_argument("--expected-position-hash")
    parser.add_argument("--idempotency-key")
    return parser.parse_args()


def _submission_requested(args: argparse.Namespace) -> bool:
    values = (
        args.move_uci,
        args.expected_state_version,
        args.expected_position_hash,
        args.idempotency_key,
    )
    populated = [value is not None for value in values]
    if any(populated) and not all(populated):
        raise RuntimeError(
            "Live submission requires --move-uci, --expected-state-version, "
            "--expected-position-hash, and --idempotency-key together."
        )
    return all(populated)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    submit = _submission_requested(args)
    evidence: dict[str, Any] = {
        "classification": "successful_validation",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "endpoint": args.url,
        "checks": {},
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
        missing = sorted(EXPECTED_TOOLS - tool_names)
        unexpected = sorted(tool_names - EXPECTED_TOOLS)
        if missing or unexpected:
            raise RuntimeError(
                f"Chess tool boundary mismatch; missing={missing}, unexpected={unexpected}"
            )
        evidence["checks"]["tool_discovery"] = {
            "status": "pass",
            "tools": sorted(tool_names),
        }

        turn = _payload(await session.call_tool("chess_get_turn", arguments={}))
        match = _payload(await session.call_tool("chess_get_match", arguments={}))
        match_id = match.get("match_id")
        if not isinstance(match_id, str) or not match_id:
            raise RuntimeError("Bound match response contained no match_id.")
        if turn.get("match_id") != match_id:
            raise RuntimeError("Turn and match tools returned different match identities.")
        if args.expected_match_id and match_id != args.expected_match_id:
            raise RuntimeError(
                f"Chess server is bound to {match_id}, expected {args.expected_match_id}."
            )
        evidence["checks"]["match_binding"] = {
            "status": "pass",
            "match_id": match_id,
            "byte_actor": turn.get("byte_actor"),
            "actor_to_move": turn.get("actor_to_move"),
            "is_byte_turn": turn.get("is_byte_turn"),
            "state_version": turn.get("state_version"),
            "position_hash": turn.get("position_hash"),
        }

        events = _payload(
            await session.call_tool(
                "chess_get_events",
                arguments={
                    "after_sequence": args.after_sequence,
                    "max_events": 200,
                },
            )
        )
        returned_events = events.get("events")
        if not isinstance(returned_events, list):
            raise RuntimeError("Events tool did not return an events list.")
        evidence["checks"]["events"] = {
            "status": "pass",
            "returned_events": len(returned_events),
        }

        if submit:
            arguments = {
                "expected_state_version": args.expected_state_version,
                "expected_position_hash": args.expected_position_hash,
                "move_uci": args.move_uci,
                "idempotency_key": args.idempotency_key,
            }
            first = _payload(
                await session.call_tool("chess_submit_move", arguments=arguments)
            )
            second = _payload(
                await session.call_tool("chess_submit_move", arguments=arguments)
            )
            if first.get("idempotent_replay") is not False:
                raise RuntimeError("First move submission was not recorded as original.")
            if second.get("idempotent_replay") is not True:
                raise RuntimeError("Repeated submission was not served from receipt.")
            if first.get("accepted") != second.get("accepted"):
                raise RuntimeError("Idempotent replay changed the referee result.")
            evidence["checks"]["move_submission"] = {
                "status": "pass",
                "move_uci": args.move_uci,
                "accepted": first.get("accepted"),
                "rejection_code": first.get("rejection_code"),
                "event_sequence": first.get("event_sequence"),
                "duplicate_arena_submission_prevented": True,
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
