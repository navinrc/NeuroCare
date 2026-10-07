"""Sense-of-time pillar (spec §5.2): current context, work blocks, and drift check-ins."""

from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from alexa_mcp_server import speech
from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.matching import normalize
from alexa_mcp_server.pillars.memory import Result, error, load_profile
from alexa_mcp_server.store.base import Item, Store, user_pk
from alexa_mcp_server.timeutil import local, minutes_between, utc_iso

Level = Literal["none", "gentle", "nudge", "hard"]
LEVELS: tuple[Level, ...] = ("none", "gentle", "nudge", "hard")

MAX_TASK = 200
DAY_START = time(5, 0)
"""Local time the working day starts; from ``time.end_of_day`` until here counts as after end of day."""
SOON_MINUTES = 180
"""``now_context`` speaks "in about N minutes" only for commitments due within this window."""
OVERRIDE_OPTIONS = ["snooze_15m", "keep_going_once", "pause_for_session", "lower_sensitivity"]
"""Override tokens (spec §5.5); the ``override`` tool itself arrives with the guardrail in phase 4."""


# --- helpers --------------------------------------------------------------------------------


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _in_range(t: time, start: time, end: time) -> bool:
    """Half-open ``[start, end)``; wraps past midnight when ``end <= start``."""
    return start <= t < end if start < end else t >= start or t < end


def energy_zone(now_local: datetime, zones: dict[str, str]) -> str | None:
    t = now_local.time()
    for zone, span in zones.items():
        start, end = span.split("-")
        if _in_range(t, _hhmm(start), _hhmm(end)):
            return zone
    return None


def after_end_of_day(now_local: datetime, end_of_day: str | None) -> bool:
    return end_of_day is not None and _in_range(now_local.time(), _hhmm(end_of_day), DAY_START)


def triggers(thresholds: dict[str, int], late: bool) -> dict[Level, int]:
    """Minutes at which each level starts. After end of day each level triggers one step earlier:
    ``gentle`` at once, ``nudge`` at the gentle threshold, ``hard`` at the nudge threshold."""
    base: dict[Level, int] = {"none": 0, **{level: thresholds[level] for level in LEVELS[1:]}}
    if not late:
        return base
    return {level: base[LEVELS[max(i - 1, 0)]] for i, level in enumerate(LEVELS)}


def level_for(elapsed: float, starts: dict[Level, int]) -> Level:
    return max((level for level in LEVELS if elapsed >= starts[level]), key=LEVELS.index)


def _open_block(store: Store, pk: str) -> Item | None:
    state = store.get(pk, "STATE") or {}
    block = store.get(pk, state["open_block_id"]) if state.get("open_block_id") else None
    return block if block and not block.get("ended_at") else None


def _set_open_block(store: Store, pk: str, block_id: str | None) -> None:
    store.put(pk, "STATE", {**(store.get(pk, "STATE") or {}), "open_block_id": block_id})


def _close(store: Store, pk: str, block: Item, now: datetime, summary: str | None = None) -> float:
    minutes = minutes_between(block["started_at"], now)
    store.put(pk, block["sk"], {**block, "ended_at": utc_iso(now), "summary": summary or block.get("summary")})
    return minutes


def _next_commitment(store: Store, pk: str, now: datetime) -> Item | None:
    stamp = utc_iso(now)
    upcoming = [
        m
        for m in store.query(pk, "MEM#")
        if m.get("kind") == "commitment" and m.get("status") == "open" and (m.get("due_at") or "") > stamp
    ]
    return min(upcoming, key=lambda m: m["due_at"], default=None)


# --- tools ----------------------------------------------------------------------------------


def now_context(store: Store, user_id: str, now: datetime) -> Result:
    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    tz = ZoneInfo(profile["timezone"])
    now_local = now.astimezone(tz)

    result: Result = {
        "now": now_local.isoformat(timespec="seconds"),
        "day_of_week": f"{now_local:%A}",
        "energy_zone": energy_zone(now_local, profile["time"]["energy_zones"]),
    }
    parts = [f"It's {speech.clock_time(now_local)} on {now_local:%A}."]

    block = _open_block(store, pk)
    if block:
        elapsed = minutes_between(block["started_at"], now)
        result["current_block"] = {
            "task": block["task"],
            "started_at": local(block["started_at"], tz),
            "elapsed_minutes": round(elapsed),
        }
        parts.append(f"You've been on {speech.second_person(block['task'])} for {speech.duration(elapsed)}.")

    commitment = _next_commitment(store, pk, now)
    if commitment:
        due = datetime.fromisoformat(commitment["due_at"])
        until = (due - now).total_seconds() / 60
        nxt: dict[str, Any] = {
            "text": commitment["text"],
            "due_at": local(commitment["due_at"], tz),
            "minutes_until": round(until),
        }
        parts.append(f"Next: {speech.second_person(commitment['text'])}, {speech.when(due.astimezone(tz), now_local)}.")
        travel = commitment.get("travel_minutes")
        if travel is not None:
            leave = due - timedelta(minutes=travel + profile["time"]["leave_buffer_minutes"])
            nxt["leave_by"] = local(utc_iso(leave), tz)
            if leave > now:
                parts.append(f"Leave by {speech.clock_time(leave.astimezone(tz))}.")
            else:
                parts.append(f"You planned to leave by {speech.clock_time(leave.astimezone(tz))}.")
        elif until <= SOON_MINUTES:
            parts.append(f"That's in {speech.duration(until)}.")
        result["next_commitment"] = nxt

    result["speak"] = " ".join(parts)
    return result


def start_block(store: Store, user_id: str, task: str, now: datetime) -> Result:
    task = task.strip()
    if not task or len(task) > MAX_TASK:
        return error("INVALID_ARGUMENT", f"task must be 1 to {MAX_TASK} characters", "What are you starting?")
    pk = user_pk(user_id)
    tz = ZoneInfo(load_profile(store, user_id)["timezone"])

    current = _open_block(store, pk)
    if current and normalize(current["task"]) == normalize(task):
        elapsed = minutes_between(current["started_at"], now)
        return {
            "block_id": current["sk"],
            "started_at": local(current["started_at"], tz),
            "already_open": True,
            "speak": f"You're already on {speech.second_person(task)}. You started {speech.duration(elapsed)} ago.",
        }

    result: Result = {}
    parts = [f"Started {speech.second_person(task)}."]
    if current:
        minutes = _close(store, pk, current, now)
        result["auto_closed"] = {"task": current["task"], "minutes": round(minutes)}
        parts.append(f"I stopped {speech.second_person(current['task'])} after {speech.duration(minutes)}.")

    sk = f"BLOCK#{new_ulid()}"
    stamp = utc_iso(now)
    store.put(pk, sk, {"task": task, "started_at": stamp, "ended_at": None, "summary": None})
    _set_open_block(store, pk, sk)
    return {"block_id": sk, "started_at": local(stamp, tz), **result, "speak": " ".join(parts)}


def end_block(store: Store, user_id: str, now: datetime, summary: str | None = None) -> Result:
    pk = user_pk(user_id)
    current = _open_block(store, pk)
    if not current:
        return error("NOT_FOUND", "no block is open", "Nothing is running right now.")
    summary = summary.strip() if summary and summary.strip() else None
    minutes = _close(store, pk, current, now, summary)
    _set_open_block(store, pk, None)
    return {
        "task": current["task"],
        "minutes": round(minutes),
        "speak": f"Stopped {speech.second_person(current['task'])} after {speech.duration(minutes)}.",
    }


def check_in(store: Store, user_id: str, now: datetime) -> Result:
    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    tz = ZoneInfo(profile["timezone"])
    current = _open_block(store, pk)
    if not current:
        return {
            "level": "none",
            "elapsed_minutes": None,
            "task": None,
            "override_options": [],
            "speak": "Nothing is running right now.",
        }

    elapsed = minutes_between(current["started_at"], now)
    late = after_end_of_day(now.astimezone(tz), profile["time"]["end_of_day"])
    starts = triggers(profile["time"]["checkin_thresholds"], late)
    level = level_for(elapsed, starts)
    task = speech.second_person(current["task"])

    result: Result = {
        "level": level,
        "elapsed_minutes": round(elapsed),
        "task": current["task"],
        "override_options": OVERRIDE_OPTIONS if level != "none" else [],
    }
    speak = f"You started {task} {speech.duration(elapsed)} ago."
    if late:
        speak += " It's after your end of day."
    if level in ("nudge", "hard"):
        speak += " Want a 5-minute break, or keep going?"
    elif level == "gentle":
        # One offer per result: a reminder at the next level's threshold.
        remind = max(1, round(starts["nudge"] - elapsed))
        result["suggest_reminder_minutes"] = remind
        speak += f" Want a reminder in {speech.number_word(remind)} minute{'' if remind == 1 else 's'}?"
    result["speak"] = speak
    return result
