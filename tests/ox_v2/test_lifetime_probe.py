import asyncio

from byte_mcp.ox_v2 import lifetime_probe


def test_probe_waits_exact_duration(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    result = asyncio.run(lifetime_probe.run_probe())
    assert waits == [930.0]
    assert result["status"] == "PASS"
    assert result["requested_seconds"] == 930
