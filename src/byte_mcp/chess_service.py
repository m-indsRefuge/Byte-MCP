"""Match-scoped service for Byte's Chess Arena capability."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .chess_client import ArenaClient
from .chess_settings import ChessSettings
from .errors import ByteMCPError

_UCI_RE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_ACTIVE_STATUSES = frozenset({"white_turn", "black_turn"})


class ChessService:
    def __init__(
        self,
        settings: ChessSettings,
        client: ArenaClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or ArenaClient(
            settings.arena_base_url,
            settings.request_timeout_seconds,
        )
        self.audit = AuditLog(settings.audit_file)
        self._submission_lock = threading.Lock()

    def get_match(self) -> dict[str, Any]:
        try:
            match = self._fetch_bound_match()
        except ByteMCPError:
            self.audit.record("chess_get_match", outcome="denied")
            raise

        self.audit.record(
            "chess_get_match",
            match_id=str(self.settings.match_id),
            state_version=match.get("state_version"),
            status=match.get("status"),
        )
        return match

    def get_turn(self) -> dict[str, Any]:
        try:
            match = self._fetch_bound_match()
        except ByteMCPError:
            self.audit.record("chess_get_turn", outcome="denied")
            raise

        status = match.get("status")
        actor_to_move: str | None = None
        side_to_move: str | None = None
        if status == "white_turn":
            side_to_move = "white"
            actor_to_move = self._required_text(match, "white_actor")
        elif status == "black_turn":
            side_to_move = "black"
            actor_to_move = self._required_text(match, "black_actor")

        result = {
            "match_id": str(self.settings.match_id),
            "status": status,
            "side_to_move": side_to_move,
            "actor_to_move": actor_to_move,
            "is_byte_turn": actor_to_move == self.settings.actor,
            "byte_actor": self.settings.actor,
            "state_version": match.get("state_version"),
            "position_hash": match.get("position_hash"),
            "fen": match.get("fen"),
            "result": match.get("result"),
            "termination": match.get("termination"),
        }
        self.audit.record(
            "chess_get_turn",
            match_id=str(self.settings.match_id),
            state_version=result["state_version"],
            status=status,
            is_byte_turn=result["is_byte_turn"],
        )
        return result

    def get_events(self, after_sequence: int = -1, max_events: int = 200) -> dict[str, Any]:
        if after_sequence < -1:
            raise ByteMCPError("after_sequence must be -1 or greater.")
        if not 1 <= max_events <= 500:
            raise ByteMCPError("max_events must be between 1 and 500.")

        self._fetch_bound_match()
        payload = self.client.get_json(f"/matches/{self.settings.match_id}/events")
        if not isinstance(payload, list):
            raise ByteMCPError("Arena events response must be a list.")

        events = [
            event
            for event in payload
            if isinstance(event, dict)
            and isinstance(event.get("sequence"), int)
            and event["sequence"] > after_sequence
        ][:max_events]
        self.audit.record(
            "chess_get_events",
            match_id=str(self.settings.match_id),
            after_sequence=after_sequence,
            returned_events=len(events),
        )
        return {
            "match_id": str(self.settings.match_id),
            "after_sequence": after_sequence,
            "events": events,
        }

    def submit_move(
        self,
        expected_state_version: int,
        expected_position_hash: str,
        move_uci: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_submission(
            expected_state_version,
            expected_position_hash,
            move_uci,
            idempotency_key,
        )
        key_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        fingerprint = self._submission_fingerprint(
            expected_state_version,
            expected_position_hash,
            move_uci,
        )

        with self._submission_lock:
            receipts = self._load_receipts()
            existing = receipts.get(key_id)
            if existing is not None:
                if existing.get("fingerprint") != fingerprint:
                    self.audit.record(
                        "chess_submit_move",
                        outcome="denied",
                        match_id=str(self.settings.match_id),
                        idempotency_key_hash=key_id,
                        reason="idempotency_conflict",
                    )
                    raise ByteMCPError(
                        "idempotency_key was already used for a different submission."
                    )
                response = existing.get("response")
                if not isinstance(response, dict):
                    raise ByteMCPError("Stored idempotency receipt is malformed.")
                replayed = dict(response)
                replayed["idempotent_replay"] = True
                return replayed

            self._fetch_bound_match()
            response = self.client.post_json(
                f"/matches/{self.settings.match_id}/moves",
                {
                    "actor": self.settings.actor,
                    "expected_state_version": expected_state_version,
                    "expected_position_hash": expected_position_hash,
                    "move_uci": move_uci,
                },
            )
            if not isinstance(response, dict) or not isinstance(
                response.get("accepted"), bool
            ):
                raise ByteMCPError("Arena move response is malformed.")

            result = dict(response)
            result["idempotent_replay"] = False
            receipts[key_id] = {
                "fingerprint": fingerprint,
                "response": result,
            }
            self._write_receipts(receipts)
            self.audit.record(
                "chess_submit_move",
                outcome="allowed" if result["accepted"] else "rejected",
                match_id=str(self.settings.match_id),
                actor=self.settings.actor,
                expected_state_version=expected_state_version,
                move_uci=move_uci,
                accepted=result["accepted"],
                rejection_code=result.get("rejection_code"),
                idempotency_key_hash=key_id,
            )
            return result

    def _fetch_bound_match(self) -> dict[str, Any]:
        payload = self.client.get_json(f"/matches/{self.settings.match_id}")
        if not isinstance(payload, dict):
            raise ByteMCPError("Arena match response must be an object.")
        if payload.get("match_id") != str(self.settings.match_id):
            raise ByteMCPError("Arena returned a different match identity.")

        white_actor = self._required_text(payload, "white_actor")
        black_actor = self._required_text(payload, "black_actor")
        if self.settings.actor not in {white_actor, black_actor}:
            raise ByteMCPError(
                "Configured Byte actor is not assigned to the bound Arena match."
            )
        return payload

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ByteMCPError(f"Arena match response is missing {key}.")
        return value

    @staticmethod
    def _validate_submission(
        expected_state_version: int,
        expected_position_hash: str,
        move_uci: str,
        idempotency_key: str,
    ) -> None:
        if expected_state_version < 0:
            raise ByteMCPError("expected_state_version must be non-negative.")
        if not _HASH_RE.fullmatch(expected_position_hash):
            raise ByteMCPError("expected_position_hash must be 64 lowercase hex characters.")
        if not _UCI_RE.fullmatch(move_uci):
            raise ByteMCPError("move_uci must use coordinate UCI notation.")
        if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise ByteMCPError(
                "idempotency_key must be 8-128 safe identity characters."
            )

    def _submission_fingerprint(
        self,
        expected_state_version: int,
        expected_position_hash: str,
        move_uci: str,
    ) -> str:
        canonical = json.dumps(
            {
                "match_id": str(self.settings.match_id),
                "actor": self.settings.actor,
                "expected_state_version": expected_state_version,
                "expected_position_hash": expected_position_hash,
                "move_uci": move_uci,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_receipts(self) -> dict[str, dict[str, Any]]:
        path = self.settings.idempotency_file
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ByteMCPError(f"Invalid chess idempotency file: {path}") from exc
        if not isinstance(payload, dict):
            raise ByteMCPError(f"Invalid chess idempotency file: {path}")
        return payload

    def _write_receipts(self, receipts: dict[str, dict[str, Any]]) -> None:
        path = self.settings.idempotency_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(f"{path}.tmp")
        temporary.write_text(
            json.dumps(receipts, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
