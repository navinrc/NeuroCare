"""Guardrail pillar (spec §5.5): rumination detection, hyperfocus with body needs, need logging.

The crisis precheck lives in ``safety.crisis``; overrides in ``pillars.overrides``.
"""

import re
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from alexa_mcp_server import semantic, speech, vectors
from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.llm import Embedder, LLMError, within
from alexa_mcp_server.matching import tokens
from alexa_mcp_server.pillars import overrides, sense_of_time
from alexa_mcp_server.pillars.memory import Result, error, load_profile
from alexa_mcp_server.refine import Refiner
from alexa_mcp_server.safety import crisis
from alexa_mcp_server.store.base import Item, Store, user_pk
from alexa_mcp_server.timeutil import local, minutes_between, utc_iso

_WORRY_LEAD_IN = re.compile(
    r"^(i'?m |i am )?(really |so |a bit |kind of )?"
    r"(worried|worrying|anxious|nervous|stressed|scared|concerned)( about| that)?\s+",
    re.IGNORECASE,
)
"""Dropped from the topic when it is spoken back: "worried about the presentation" → "the presentation"."""

Need = Literal["water", "food", "break"]
NEEDS: tuple[Need, ...] = ("water", "food", "break")
MAX_TOPIC = 500
TTL = timedelta(days=7)
JACCARD_MIN = 0.5
COSINE_MIN = 0.40  # Titan v2: same worry reworded 0.44–0.70, unrelated <= 0.22 (FINDINGS #29)
NEED_OFFERS = {"water": "Want to get some water?", "food": "Want to eat something?", "break": "Want a short break?"}
_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


def _ttl(now: datetime) -> int:
    return int((now + TTL).timestamp())


def jaccard(a: str, b: str) -> float:
    left, right = set(tokens(a)), set(tokens(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _ordinal(n: int) -> str:
    return _ORDINALS[n - 1] if 1 <= n <= len(_ORDINALS) else f"{n}th"


def _as_question(redirect: str) -> str:
    text = redirect.strip().rstrip(".")
    return f"Want to {text[0].lower()}{text[1:]}?"


def _embed_now(embedder: Embedder | None, text: str) -> list[float] | None:
    if embedder is None:
        return None
    try:
        return within(semantic.EMBED_BUDGET, embedder.embed, text)
    except (TimeoutError, LLMError):
        return None


def log_topic(
    store: Store,
    user_id: str,
    topic: str,
    now: datetime,
    embedder: Embedder | None = None,
    guard: crisis.Guard | None = None,
    refiner: Refiner | None = None,
) -> Result:
    topic = topic.strip()
    if not topic or len(topic) > MAX_TOPIC:
        return error("INVALID_ARGUMENT", f"topic must be 1 to {MAX_TOPIC} characters", "What's on your mind?")
    check = crisis.precheck(store, user_id, topic, now, guard=guard, refiner=refiner)
    if check.crisis:
        return check.crisis  # topic not stored

    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    if not profile["consent"]["embeddings"]:
        embedder = None
    window = profile["guardrail"]["rumination_window_minutes"]
    threshold = profile["guardrail"]["rumination_threshold"]
    since = utc_iso(now - timedelta(minutes=window))

    vector = _embed_now(embedder, topic)
    earlier = [t for t in store.query(pk, "TOPIC#") if t["created_at"] >= since]
    similar: list[Item] = []
    for item in earlier:
        other = semantic.item_vector(item)
        close = vector is not None and other is not None and vectors.cosine(vector, other) >= COSINE_MIN
        if close or jaccard(topic, item["text"]) >= JACCARD_MIN:
            similar.append(item)

    sk = f"TOPIC#{new_ulid()}"
    doc = {
        "text": topic,
        "created_at": utc_iso(now),
        "embedding": vectors.pack(vector) if vector else None,
        "ttl": _ttl(now),
    }
    store.put(pk, sk, doc, ttl=doc["ttl"])
    crisis.attach(store, user_id, check, sk)
    if vector is None and embedder is not None and refiner is not None:
        refiner.submit("embed", user_id, sk)

    count = len(similar) + 1
    result: Result = {"detected": False, "count": count, "window_minutes": window, "override_options": []}
    said = speech.second_person(_WORRY_LEAD_IN.sub("", topic.strip()) or topic)
    if count < threshold:
        result["speak"] = f"Okay, noted: {said}."
        return result
    if overrides.suppress(store, user_id, "rumination", now):
        result.update(suppressed=True, speak=f"Okay, noted: {said}.")
        return result

    redirects = profile["guardrail"]["preferred_redirects"]
    redirect = redirects[(count - threshold) % len(redirects)]
    span = minutes_between(min(s["created_at"] for s in similar), now)
    result.update(detected=True, redirect=redirect, override_options=list(overrides.TOKENS))
    result["speak"] = (
        f"This is the {_ordinal(count)} time in {speech.duration(span).removeprefix('about ')} "
        f"that we've come back to {said}. {_as_question(redirect)}"
    )
    return result


def log_need(store: Store, user_id: str, kind: str, now: datetime) -> Result:
    if kind not in NEEDS:
        return error("INVALID_ARGUMENT", "kind must be water, food, or break", "Was that water, food, or a break?")
    pk = user_pk(user_id)
    tz = ZoneInfo(load_profile(store, user_id)["timezone"])
    stamp = utc_iso(now)
    store.put(pk, f"NEED#{new_ulid()}", {"kind": kind, "logged_at": stamp, "ttl": _ttl(now)}, ttl=_ttl(now))
    said = {"water": "water", "food": "food", "break": "a break"}[kind]
    return {
        "kind": kind,
        "logged_at": local(stamp, tz),
        "speak": f"Noted: {said} at {speech.clock_time(now.astimezone(tz))}.",
    }


def _last_logged(store: Store, pk: str) -> dict[str, str]:
    last: dict[str, str] = {}
    for item in store.query(pk, "NEED#"):
        last[item["kind"]] = max(last.get(item["kind"], ""), item["logged_at"])
    return last


def check_hyperfocus(store: Store, user_id: str, now: datetime) -> Result:
    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    tz = ZoneInfo(profile["timezone"])
    now_local = now.astimezone(tz)
    base = sense_of_time.check_in(store, user_id, now)
    intervals = profile["guardrail"]["need_intervals"]
    last = _last_logged(store, pk)

    # Without a log, count from the start of the current block (or the start of the day).
    block = store.get(pk, (store.get(pk, "STATE") or {}).get("open_block_id") or "-")
    day_start = datetime.combine(now_local.date(), time(5, 0), tzinfo=tz)
    fallback = block["started_at"] if block and not block.get("ended_at") else utc_iso(min(day_start, now))

    unmet: list[dict[str, Any]] = []
    for need in NEEDS:
        since = last.get(need)
        minutes = minutes_between(since or fallback, now)
        if minutes >= intervals[need]:
            unmet.append({"kind": need, "since": local(since, tz) if since else None, "minutes": round(minutes)})

    result: Result = {
        "level": base["level"],
        "elapsed_minutes": base["elapsed_minutes"],
        "task": base["task"],
        "unmet_needs": unmet,
        "override_options": base["override_options"],
    }
    if base.get("suppressed"):
        result.update(suppressed=True, override_options=[])
    parts: list[str] = []
    if base["task"]:
        parts.append(
            f"You've been on {speech.second_person(base['task'])} for {speech.duration(base['elapsed_minutes'])}."
        )
    else:
        parts.append("Nothing is running right now.")
    if unmet and not base.get("suppressed"):
        phrases = []
        for need in unmet:
            label = {"water": "No water", "food": "No food", "break": "No break"}[need["kind"]]
            if need["since"]:
                at = datetime.fromisoformat(need["since"])
                phrases.append(f"{label} logged since {speech.clock_time(at)}")
            else:
                phrases.append(f"{label} logged today")
        parts.append(". ".join(phrases) + ".")
    # At most one offer: a break at nudge/hard, else the first unmet need, else a reminder (gentle).
    if base.get("suppressed"):
        pass
    elif base["level"] in ("nudge", "hard"):
        parts.append("Want a 5-minute break, or keep going?")
    elif unmet:
        parts.append(NEED_OFFERS[unmet[0]["kind"]])
    elif base.get("suggest_reminder_minutes"):
        remind = base["suggest_reminder_minutes"]
        result["suggest_reminder_minutes"] = remind
        parts.append(f"Want a reminder in {speech.number_word(remind)} minute{'' if remind == 1 else 's'}?")
    result["speak"] = " ".join(parts)
    return result
