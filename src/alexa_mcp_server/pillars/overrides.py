"""User overrides for guardrail prompts (spec §5.5 ``override``). Never applies to the crisis path.

Each override is logged as an ``OVERRIDE#`` item. The prompts it can suppress are the drift
check-in (``check_in``, ``check_hyperfocus``) and rumination detection (``log_topic``). Suppression
hides the prompt, not the level: results still report the level and say ``suppressed: true``.
"""

from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from alexa_mcp_server import profile as profile_schema
from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.pillars.memory import Result, _stored_profile, error, load_profile
from alexa_mcp_server.store.base import Item, Store, user_pk
from alexa_mcp_server.timeutil import local, utc_iso

Token = Literal["snooze_15m", "keep_going_once", "pause_for_session", "lower_sensitivity"]
TOKENS: tuple[Token, ...] = ("snooze_15m", "keep_going_once", "pause_for_session", "lower_sensitivity")
Prompt = Literal["checkin", "rumination"]

SNOOZE = timedelta(minutes=15)
SESSION_MAX = timedelta(hours=4)
"""``pause_for_session`` ends with the current block, or after this long if no block is open."""
CHECKIN_STEP = 15
"""``lower_sensitivity`` on check-ins moves every threshold up this many minutes."""


def _open_block_id(store: Store, pk: str) -> str | None:
    state = store.get(pk, "STATE") or {}
    block_id = state.get("open_block_id")
    block = store.get(pk, block_id) if block_id else None
    return block_id if block and not block.get("ended_at") else None


def _is_active(store: Store, pk: str, item: Item, now: datetime) -> bool:
    if item.get("consumed_at"):
        return False
    if item.get("active_until") and datetime.fromisoformat(item["active_until"]) <= now:
        return False
    if item["token"] == "pause_for_session" and item.get("block_id"):
        return _open_block_id(store, pk) == item["block_id"]
    return item["token"] in ("snooze_15m", "keep_going_once", "pause_for_session")


def active(store: Store, user_id: str, now: datetime) -> list[Item]:
    pk = user_pk(user_id)
    return [o for o in store.query(pk, "OVERRIDE#") if _is_active(store, pk, o, now)]


def suppress(store: Store, user_id: str, prompt: Prompt, now: datetime) -> bool:
    """Whether a guardrail prompt that is about to be shown should be suppressed.

    Records which prompt was due (for ``lower_sensitivity``) and uses up a ``keep_going_once``.
    """
    pk = user_pk(user_id)
    state = store.get(pk, "STATE") or {}
    store.put(pk, "STATE", {**state, "last_guardrail": prompt})
    overrides = active(store, user_id, now)
    if not overrides:
        return False
    once = next((o for o in overrides if o["token"] == "keep_going_once"), None)
    if once and len(overrides) == 1:
        store.put(pk, once["sk"], {**once, "consumed_at": utc_iso(now)})
    return True


def _lower_sensitivity(store: Store, user_id: str, now: datetime) -> tuple[str, Any, Any]:
    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    state = store.get(pk, "STATE") or {}
    stored = _stored_profile(store, user_id)
    if state.get("last_guardrail") == "rumination":
        key = "guardrail.rumination_threshold"
        old = profile["guardrail"]["rumination_threshold"]
        new = min(old + 1, 20)
        profile_schema.set_path(stored, key, new)
    else:
        key = "time.checkin_thresholds"
        old = dict(profile["time"]["checkin_thresholds"])
        new = {level: min(minutes + CHECKIN_STEP, 480) for level, minutes in old.items()}
        if not new["gentle"] < new["nudge"] < new["hard"]:  # at the cap; keep the order
            new = old
        profile_schema.set_path(stored, key, new)
    store.put(pk, "PROFILE", {"doc": stored, "updated_at": utc_iso(now)})
    return key, old, new


def override(store: Store, user_id: str, token: str, now: datetime) -> Result:
    if token not in TOKENS:
        return error(
            "INVALID_ARGUMENT",
            f"token must be one of: {', '.join(TOKENS)}",
            "I can snooze for 15 minutes, skip the next check, pause for this session, or check in less often.",
        )
    pk = user_pk(user_id)
    tz = ZoneInfo(load_profile(store, user_id)["timezone"])
    doc: dict[str, Any] = {"token": token, "created_at": utc_iso(now), "active_until": None}
    result: Result = {"token": token}

    if token == "snooze_15m":
        doc["active_until"] = utc_iso(now + SNOOZE)
        speak = "Okay. No check-ins for 15 minutes."
    elif token == "keep_going_once":
        speak = "Okay. I'll skip the next check-in."
    elif token == "pause_for_session":
        block_id = _open_block_id(store, pk)
        doc["block_id"] = block_id
        if block_id is None:
            doc["active_until"] = utc_iso(now + SESSION_MAX)
            speak = "Okay. No check-ins for the next four hours."
        else:
            speak = "Okay. No more check-ins until you stop this piece of work."
    else:
        key, old, new = _lower_sensitivity(store, user_id, now)
        doc.update({"key": key, "old_value": old, "new_value": new})
        result.update({"key": key, "old_value": old, "new_value": new})
        if key == "guardrail.rumination_threshold":
            speak = f"Okay. I'll mention a repeated worry only after {new} times."
        elif new == old:
            speak = "Check-ins are already as far apart as they go."
        else:
            speak = f"Okay. The first check-in now comes after {new['gentle']} minutes."

    store.put(pk, f"OVERRIDE#{new_ulid()}", doc)
    if doc["active_until"]:
        result["active_until"] = local(doc["active_until"], tz)
    return {**result, "speak": speak}
