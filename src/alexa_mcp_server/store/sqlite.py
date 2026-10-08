"""SQLite backend for local dev and tests."""

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alexa_mcp_server.store.base import Item, Store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    pk TEXT NOT NULL,
    sk TEXT NOT NULL,
    type TEXT NOT NULL,
    doc TEXT NOT NULL,
    embedding BLOB,
    ttl INTEGER,
    PRIMARY KEY (pk, sk)
)
"""


def _row_to_item(pk: str, sk: str, doc: str) -> Item:
    return {**json.loads(doc), "pk": pk, "sk": sk}


class SQLiteStore(Store):
    def __init__(self, path: str = ":memory:", clock: Callable[[], float] = time.time):
        """``clock`` gives epoch seconds for TTL checks; tests pass their fixed clock."""
        self._clock = clock
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_SCHEMA)

    def get(self, pk: str, sk: str) -> Item | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM items WHERE pk = ? AND sk = ? AND (ttl IS NULL OR ttl > ?)",
                (pk, sk, int(self._clock())),
            ).fetchone()
        return _row_to_item(pk, sk, row[0]) if row else None

    def put(self, pk: str, sk: str, doc: dict[str, Any], *, ttl: int | None = None) -> Item:
        body = {k: v for k, v in doc.items() if k not in ("pk", "sk")}
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO items (pk, sk, type, doc, ttl) VALUES (?, ?, ?, ?, ?)",
                (pk, sk, sk.split("#", 1)[0], json.dumps(body), ttl),
            )
        return {**body, "pk": pk, "sk": sk}

    def query(self, pk: str, prefix: str = "") -> list[Item]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT sk, doc FROM items WHERE pk = ? AND substr(sk, 1, ?) = ? AND (ttl IS NULL OR ttl > ?)"
                " ORDER BY sk",
                (pk, len(prefix), prefix, int(self._clock())),
            ).fetchall()
        return [_row_to_item(pk, sk, doc) for sk, doc in rows]

    def delete(self, pk: str, sk: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM items WHERE pk = ? AND sk = ?", (pk, sk))

    def delete_partition(self, pk: str) -> int:
        with self._lock:
            return self._conn.execute("DELETE FROM items WHERE pk = ?", (pk,)).rowcount
