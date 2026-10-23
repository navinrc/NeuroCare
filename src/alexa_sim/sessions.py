"""Simulator sessions: tokens, short history, reminders, pending OAuth state (spec §5.9).

Kept in the simulator's own table (``neurocare-sim``), never in the server's. One JSON document per
session, so DynamoDB number types never leak into it.
"""

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import boto3

SESSION_TTL = 30 * 24 * 3600
HISTORY_TURNS = 10


@dataclass
class Session:
    id: str
    tokens: dict[str, Any] = field(default_factory=dict)
    """``access_token``, ``refresh_token``, ``expires_at`` (epoch seconds)."""
    history: list[dict[str, str]] = field(default_factory=list)
    """``{"role": "user" | "assistant", "text": ...}``, oldest first."""
    reminders: list[dict[str, Any]] = field(default_factory=list)
    """``{"id", "text", "due_at" (epoch), "acked"}``."""
    oauth: dict[str, str] = field(default_factory=dict)
    """Pending link: ``state`` and PKCE ``verifier``; cleared once used."""

    @property
    def linked(self) -> bool:
        return bool(self.tokens.get("refresh_token") or self.tokens.get("access_token"))

    def remember_turn(self, user: str, assistant: str) -> None:
        self.history += [{"role": "user", "text": user}, {"role": "assistant", "text": assistant}]
        self.history = self.history[-2 * HISTORY_TURNS :]

    def due_reminders(self, now: float) -> list[dict[str, Any]]:
        return [r for r in self.reminders if not r.get("acked") and r["due_at"] <= now]


def new_session() -> Session:
    return Session(id=secrets.token_urlsafe(32))


class SessionStore(Protocol):
    def get(self, session_id: str) -> Session | None: ...
    def save(self, session: Session) -> None: ...


class MemorySessions:
    def __init__(self) -> None:
        self._docs: dict[str, str] = {}

    def get(self, session_id: str) -> Session | None:
        doc = self._docs.get(session_id)
        return Session(**json.loads(doc)) if doc else None

    def save(self, session: Session) -> None:
        self._docs[session.id] = json.dumps(asdict(session))


class DynamoSessions:
    def __init__(self, table: str, region: str):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table)

    def get(self, session_id: str) -> Session | None:
        row = self._table.get_item(Key={"PK": f"SESSION#{session_id}"}).get("Item")
        if not row or int(row.get("ttl", 0)) < time.time():
            return None
        return Session(**json.loads(row["doc"]))

    def save(self, session: Session) -> None:
        self._table.put_item(
            Item={
                "PK": f"SESSION#{session.id}",
                "doc": json.dumps(asdict(session)),
                "ttl": int(time.time()) + SESSION_TTL,
            }
        )
