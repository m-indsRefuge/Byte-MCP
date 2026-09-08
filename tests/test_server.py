from typing import Any

from byte_mcp import server


def test_main_initializes_core_and_binds_without_ox_or_wolfram(monkeypatch: Any) -> None:
    events: list[str] = []
    core_service = object()

    def fake_file_service(settings):
        assert settings is server.SETTINGS
        events.append("service")
        return core_service

    def fail_if_ox_loaded() -> None:
        raise AssertionError("V1 OX must not initialize during startup")

    def fail_if_wolfram_loaded() -> None:
        raise AssertionError("Wolfram runtime must remain lazy during core startup")

    def fake_run(*, transport: str) -> None:
        assert transport == server.SETTINGS.transport
        assert server._service is core_service
        events.append("run")

    monkeypatch.setattr(server, "_service", None)
    monkeypatch.setattr(server, "FileService", fake_file_service)
    monkeypatch.setattr(server, "ox_runtime", fail_if_ox_loaded, raising=False)
    monkeypatch.setattr(server, "wolfram_runtime", fail_if_wolfram_loaded)
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert events == ["service", "run"]
