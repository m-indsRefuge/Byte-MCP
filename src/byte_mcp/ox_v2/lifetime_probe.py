"""Provider-free deployed MCP lifetime qualification probe for OX V2."""

import asyncio
from datetime import UTC, datetime

_PROBE_SECONDS = 930.0


async def run_probe() -> dict[str, object]:
    """Wait for the qualification interval and return an observed completion receipt."""
    started_at = datetime.now(UTC).isoformat()
    await asyncio.sleep(_PROBE_SECONDS)
    return {
        "status": "PASS",
        "requested_seconds": 930,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
    }
