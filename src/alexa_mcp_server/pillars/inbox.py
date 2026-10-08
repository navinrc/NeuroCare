"""Personal inbox tokens for ``POST /inbox`` (spec §5.3).

The token is shown once; only its SHA-256 is stored, as ``TOKEN#<hash>`` / ``INBOX`` outside the user
partition (the caller knows only the token). The user's ``STATE`` lists their hashes so ``delete_all``
and ``/token revoke`` can find them.
"""

import hashlib
import secrets
from datetime import datetime

from alexa_mcp_server.store.base import Store, user_pk
from alexa_mcp_server.timeutil import utc_iso

TOKEN_SK = "INBOX"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_inbox_token(store: Store, user_id: str, now: datetime) -> str:
    token = "nc_" + secrets.token_urlsafe(32)
    digest = _hash(token)
    store.put(f"TOKEN#{digest}", TOKEN_SK, {"user_id": user_id, "created_at": utc_iso(now)})
    state = store.get(user_pk(user_id), "STATE") or {}
    store.put(user_pk(user_id), "STATE", {**state, "inbox_tokens": [*state.get("inbox_tokens", []), digest]})
    return token


def revoke_inbox_tokens(store: Store, user_id: str) -> int:
    state = store.get(user_pk(user_id), "STATE") or {}
    digests = state.get("inbox_tokens", [])
    for digest in digests:
        store.delete(f"TOKEN#{digest}", TOKEN_SK)
    if state:
        store.put(user_pk(user_id), "STATE", {**state, "inbox_tokens": []})
    return len(digests)


def user_for_inbox_token(store: Store, token: str) -> str | None:
    if not token:
        return None
    item = store.get(f"TOKEN#{_hash(token)}", TOKEN_SK)
    return item["user_id"] if item else None
