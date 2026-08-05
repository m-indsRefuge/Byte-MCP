from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from byte_mcp.chess_service import ChessService
from byte_mcp.chess_settings import ChessSettings
from byte_mcp.errors import ByteMCPError

POSITION_HASH = "a" * 64
NEXT_POSITION_HASH = "b" * 64


class FakeArenaClient:
    def __init__(self, match: dict[str, Any]) -> None:
        self.match = deepcopy(match)
        self.events: list[dict[str, Any]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, path: str) -> Any:
        if path.endswith("/events"):
            return deepcopy(self.events)
        return deepcopy(self.match)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        self.post_calls.append((path, deepcopy(payload)))
        accepted = (
            payload["actor"] == self.match["black_actor"]
            and payload["expected_state_version"] == self.match["state_version"]
            and payload["expected_position_hash"] == self.match["position_hash"]
            and payload["move_uci"] == "e7e5"
        )
        if accepted:
            previous_version = self.match["state_version"]
            self.match["state_version"] = previous_version + 1
            self.match["position_hash"] = NEXT_POSITION_HASH
            self.match["status"] = "white_turn"
            return {
                "accepted": True,
                "match": deepcopy(self.match),
                "move_uci": payload["move_uci"],
                "move_san": "e5",
                "rejection_code": None,
                "event_sequence": 3,
            }
        return {
            "accepted": False,
            "match": deepcopy(self.match),
            "move_uci": payload["move_uci"],
            "move_san": None,
            "rejection_code": "stale_state",
            "event_sequence": 3,
        }


def _settings(tmp_path: Path, match_id: UUID, actor: str = "byte") -> ChessSettings:
    return ChessSettings(
        repo_root=tmp_path,
        arena_base_url="http://127.0.0.1:8787/api/v1",
        match_id=match_id,
        actor=actor,
        audit_file=tmp_path / "chess-audit.jsonl",
        idempotency_file=tmp_path / "chess-idempotency.json",
        request_timeout_seconds=5,
    )


def _match(match_id: UUID) -> dict[str, Any]:
    return {
        "match_id": str(match_id),
        "white_actor": "candidate-model",
        "black_actor": "byte",
        "status": "black_turn",
        "state_version": 1,
        "initial_fen": "start",
        "fen": "current",
        "position_hash": POSITION_HASH,
        "result": None,
        "termination": None,
        "created_at": "2026-08-05T00:00:00Z",
        "updated_at": "2026-08-05T00:00:01Z",
    }


def test_get_turn_reports_bound_byte_actor(tmp_path: Path) -> None:
    match_id = uuid4()
    service = ChessService(
        _settings(tmp_path, match_id),
        FakeArenaClient(_match(match_id)),
    )

    turn = service.get_turn()

    assert turn["is_byte_turn"] is True
    assert turn["actor_to_move"] == "byte"
    assert turn["side_to_move"] == "black"
    assert turn["state_version"] == 1
    assert turn["position_hash"] == POSITION_HASH


def test_match_binding_rejects_unassigned_actor(tmp_path: Path) -> None:
    match_id = uuid4()
    service = ChessService(
        _settings(tmp_path, match_id, actor="intruder"),
        FakeArenaClient(_match(match_id)),
    )

    with pytest.raises(ByteMCPError, match="not assigned"):
        service.get_match()


def test_match_binding_rejects_different_match_identity(tmp_path: Path) -> None:
    bound_match_id = uuid4()
    other_match_id = uuid4()
    service = ChessService(
        _settings(tmp_path, bound_match_id),
        FakeArenaClient(_match(other_match_id)),
    )

    with pytest.raises(ByteMCPError, match="different match"):
        service.get_turn()


def test_submit_move_forwards_exact_referee_preconditions(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    service = ChessService(_settings(tmp_path, match_id), client)

    result = service.submit_move(
        expected_state_version=1,
        expected_position_hash=POSITION_HASH,
        move_uci="e7e5",
        idempotency_key="turn-0001-byte",
    )

    assert result["accepted"] is True
    assert result["idempotent_replay"] is False
    assert client.post_calls == [
        (
            f"/matches/{match_id}/moves",
            {
                "actor": "byte",
                "expected_state_version": 1,
                "expected_position_hash": POSITION_HASH,
                "move_uci": "e7e5",
            },
        )
    ]


def test_idempotent_replay_does_not_submit_twice(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    service = ChessService(_settings(tmp_path, match_id), client)

    first = service.submit_move(
        1,
        POSITION_HASH,
        "e7e5",
        "turn-0001-byte",
    )
    second = service.submit_move(
        1,
        POSITION_HASH,
        "e7e5",
        "turn-0001-byte",
    )

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(client.post_calls) == 1


def test_idempotency_survives_service_restart(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    settings = _settings(tmp_path, match_id)
    ChessService(settings, client).submit_move(
        1,
        POSITION_HASH,
        "e7e5",
        "turn-0001-byte",
    )

    restarted = ChessService(settings, client)
    replay = restarted.submit_move(
        1,
        POSITION_HASH,
        "e7e5",
        "turn-0001-byte",
    )

    assert replay["idempotent_replay"] is True
    assert len(client.post_calls) == 1


def test_idempotency_key_cannot_be_reused_for_different_move(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    service = ChessService(_settings(tmp_path, match_id), client)
    service.submit_move(1, POSITION_HASH, "e7e5", "turn-0001-byte")

    with pytest.raises(ByteMCPError, match="different submission"):
        service.submit_move(1, POSITION_HASH, "g8f6", "turn-0001-byte")


def test_invalid_uci_is_denied_before_arena_submission(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    service = ChessService(_settings(tmp_path, match_id), client)

    with pytest.raises(ByteMCPError, match="coordinate UCI"):
        service.submit_move(1, POSITION_HASH, "e5", "turn-0001-byte")

    assert client.post_calls == []


def test_events_are_bounded_after_sequence(tmp_path: Path) -> None:
    match_id = uuid4()
    client = FakeArenaClient(_match(match_id))
    client.events = [
        {"sequence": 0, "event_type": "match_created"},
        {"sequence": 1, "event_type": "move_accepted"},
        {"sequence": 2, "event_type": "move_accepted"},
    ]
    service = ChessService(_settings(tmp_path, match_id), client)

    result = service.get_events(after_sequence=0, max_events=1)

    assert result["events"] == [{"sequence": 1, "event_type": "move_accepted"}]
