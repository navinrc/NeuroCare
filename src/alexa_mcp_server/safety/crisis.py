"""Crisis path (spec §6).

Step 1 is a deterministic phrase list (offline, always on). Step 2 is Bedrock Guardrails
``ApplyGuardrail`` with a 250 ms budget; on timeout the tool goes on and the check re-runs in the
background. An async hit sets ``STATE.crisis_flag_at``: the next tool call of any kind returns the
crisis result first, and the items stored from that text are deleted.

On a hit nothing about the text is stored — only a boolean event (count and time) on ``STATE``.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.llm import LLMError, within
from alexa_mcp_server.refine import Deps, Refiner, job
from alexa_mcp_server.store.base import Store, user_pk
from alexa_mcp_server.timeutil import utc_iso

GUARD_BUDGET = 0.25
"""Seconds ``ApplyGuardrail`` may take on the Alexa path."""
CHECK_TTL = timedelta(days=1)
"""How long the text of a pending background re-check is kept."""

PHRASES = [
    "kill myself",
    "killing myself",
    "end my life",
    "ending my life",
    "take my own life",
    "taking my own life",
    "suicide",
    "suicidal",
    "want to die",
    "wanna die",
    "wish i was dead",
    "wish i were dead",
    "dont want to live",
    "dont want to be alive",
    "dont want to be here anymore",
    "cant go on",
    "cant do this anymore",
    "no reason to live",
    "nothing to live for",
    "better off dead",
    "better off without me",
    "end it all",
    "not worth living",
    "self harm",
    "selfharm",
    "hurt myself",
    "harm myself",
    "cut myself",
    "cutting myself",
    "overdose",
]

RESOURCES: dict[str, list[dict[str, str]]] = {
    "US": [
        {"name": "988 Suicide & Crisis Lifeline", "contact": "Call or text 988"},
        {"name": "Emergency services", "contact": "Call 911"},
    ],
    "CA": [
        {"name": "9-8-8 Suicide Crisis Helpline", "contact": "Call or text 988"},
        {"name": "Emergency services", "contact": "Call 911"},
    ],
    "GB": [
        {"name": "Samaritans", "contact": "Call 116 123"},
        {"name": "Emergency services", "contact": "Call 999"},
    ],
    "AU": [
        {"name": "Lifeline", "contact": "Call 13 11 14"},
        {"name": "Emergency services", "contact": "Call 000"},
    ],
    "IN": [
        {"name": "Tele-MANAS", "contact": "Call 14416"},
        {"name": "Emergency services", "contact": "Call 112"},
    ],
}
FALLBACK = [
    {"name": "Emergency services", "contact": "Call your local emergency number"},
    {"name": "Find a Helpline", "contact": "findahelpline.com lists free, confidential helplines in your country"},
]
SPEAK = {
    "US": "You can call or text 988 any time to talk to someone right now. If you're in danger, call 911.",
    "CA": "You can call or text 988 any time to talk to someone right now. If you're in danger, call 911.",
    "GB": "You can call Samaritans on 116 123 any time to talk to someone right now. If you're in danger, call 999.",
    "AU": "You can call Lifeline on 13 11 14 any time to talk to someone right now. If you're in danger, call 000.",
    "IN": "You can call Tele-MANAS on 14416 any time to talk to someone right now. If you're in danger, call 112.",
}
FALLBACK_SPEAK = (
    "Please reach out to someone right now. If you're in danger, call your local emergency number. "
    "findahelpline.com lists free helplines in your country."
)


def _normalize(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())


_PATTERN = re.compile(r"\b(" + "|".join(re.escape(_normalize(p)) for p in PHRASES) + r")\b")


def phrase_hit(text: str) -> bool:
    return _PATTERN.search(_normalize(text)) is not None


class Guard(Protocol):
    def intervenes(self, text: str) -> bool:
        """True when the model-based guard flags self-harm or violence. Raises ``LLMError``."""
        ...


def crisis_result(locale: str) -> dict[str, Any]:
    region = locale.rsplit("-", 1)[-1].upper() if "-" in locale else ""
    return {
        "crisis": True,
        "resources": RESOURCES.get(region, FALLBACK),
        "speak": SPEAK.get(region, FALLBACK_SPEAK),
    }


def _locale(store: Store, user_id: str) -> str:
    profile = store.get(user_pk(user_id), "PROFILE")
    return ((profile or {}).get("doc") or {}).get("locale") or "en-US"


def record_event(store: Store, user_id: str, now: datetime) -> None:
    pk = user_pk(user_id)
    state = store.get(pk, "STATE") or {}
    store.put(
        pk, "STATE", {**state, "crisis_events": state.get("crisis_events", 0) + 1, "last_crisis_at": utc_iso(now)}
    )


def pending_flag(store: Store, user_id: str, now: datetime) -> dict[str, Any] | None:
    """If a background check hit since the last call, clear the flag and return the crisis result."""
    pk = user_pk(user_id)
    state = store.get(pk, "STATE") or {}
    if not state.get("crisis_flag_at"):
        return None
    store.put(pk, "STATE", {**state, "crisis_flag_at": None, "crisis_flag_delivered_at": utc_iso(now)})
    return crisis_result(_locale(store, user_id))


@dataclass
class Precheck:
    crisis: dict[str, Any] | None = None
    check_ref: str | None = None
    """Set when the guard timed out and re-runs in the background; pass to ``attach``."""


def precheck(
    store: Store,
    user_id: str,
    text: str,
    now: datetime,
    guard: Guard | None = None,
    refiner: Refiner | None = None,
    budget: float = GUARD_BUDGET,
) -> Precheck:
    if phrase_hit(text):
        record_event(store, user_id, now)
        return Precheck(crisis_result(_locale(store, user_id)))
    if guard is None:
        return Precheck()
    try:
        hit = within(budget, guard.intervenes, text)
    except TimeoutError:
        if refiner is None:
            return Precheck()
        ref = f"CHECK#{new_ulid()}"
        ttl = int((now + CHECK_TTL).timestamp())
        store.put(user_pk(user_id), ref, {"text": text, "items": [], "ttl": ttl}, ttl=ttl)
        refiner.submit("crisis_recheck", user_id, ref)
        return Precheck(check_ref=ref)
    except LLMError:
        return Precheck()  # a guard failure never blocks step 1
    if hit:
        record_event(store, user_id, now)
        return Precheck(crisis_result(_locale(store, user_id)))
    return Precheck()


def attach(store: Store, user_id: str, check: Precheck, item_sk: str) -> None:
    """Link an item stored from the checked text, so an async hit can delete it."""
    if not check.check_ref:
        return
    pk = user_pk(user_id)
    pending = store.get(pk, check.check_ref)
    if pending is None:  # re-checked and clear
        return
    if pending.get("hit"):  # re-checked and hit before the item was stored
        store.delete(pk, item_sk)
        return
    store.put(pk, check.check_ref, {**pending, "items": [*pending["items"], item_sk]}, ttl=pending.get("ttl"))


@job("crisis_recheck")
def recheck(deps: Deps, user_id: str, ref: str) -> None:
    pk = user_pk(user_id)
    pending = deps.store.get(pk, ref)
    if pending is None:
        return
    try:
        hit = deps.guard.intervenes(pending["text"]) if deps.guard else False
    except LLMError:
        hit = False
    if not hit:
        deps.store.delete(pk, ref)
        return
    # Re-read: the tool may have attached its stored item while the guard was running.
    pending = deps.store.get(pk, ref) or pending
    for sk in pending["items"]:
        deps.store.delete(pk, sk)
    # Keep a text-free marker so an item attached after this point is deleted too.
    deps.store.put(pk, ref, {"hit": True, "items": [], "ttl": pending.get("ttl")}, ttl=pending.get("ttl"))
    record_event(deps.store, user_id, deps.clock())
    state = deps.store.get(pk, "STATE") or {}
    deps.store.put(pk, "STATE", {**state, "crisis_flag_at": utc_iso(deps.clock())})
