from typing import Any

from byte_mcp import server


def test_main_initializes_service_before_binding_server(monkeypatch: Any) -> None:
    events: list[str] = []

    def fake_service() -> None:
        events.append("service")

    def fake_run(*, transport: str) -> None:
        assert transport == server.SETTINGS.transport
        events.append("run")

    def fail_if_wolfram_loaded():
        raise AssertionError("Wolfram runtime must remain lazy during core startup")

    monkeypatch.setattr(server, "service", fake_service)
    monkeypatch.setattr(server, "wolfram_runtime", fail_if_wolfram_loaded)
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert events == ["service", "run"]
