from typing import Any

from byte_mcp import server
from byte_mcp.ox.models import OXAvailability


def test_main_initializes_core_then_ox_before_binding_server(monkeypatch: Any) -> None:
    events: list[str] = []

    def fake_service() -> None:
        events.append("service")

    def fake_ox_runtime() -> None:
        events.append("ox_runtime")

    def fake_run(*, transport: str) -> None:
        assert transport == server.SETTINGS.transport
        events.append("run")

    monkeypatch.setattr(server, "service", fake_service)
    monkeypatch.setattr(server, "ox_runtime", fake_ox_runtime, raising=False)
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert events == ["service", "ox_runtime", "run"]


def test_main_still_binds_when_optional_ox_settings_are_invalid(monkeypatch: Any) -> None:
    events: list[str] = []
    core_service = object()

    def fake_service() -> object:
        events.append("service")
        return core_service

    def invalid_ox_settings(repo_root):
        raise ValueError("synthetic optional OX configuration failure")

    def fake_run(*, transport: str) -> None:
        assert transport == server.SETTINGS.transport
        events.append("run")

    monkeypatch.setattr(server, "_ox_runtime_instance", None)
    monkeypatch.setattr(server, "service", fake_service)
    monkeypatch.setattr(server.OXSettings, "load", invalid_ox_settings)
    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert events == ["service", "run"]
    assert server.ox_runtime().state is OXAvailability.MISCONFIGURED
