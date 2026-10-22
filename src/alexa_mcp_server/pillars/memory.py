"""Memory pillar (spec §5.1): facts, people, preferences, commitments, open loops, profile."""

from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from alexa_mcp_server import profile as profile_schema
from alexa_mcp_server import semantic, speech
from alexa_mcp_server.ids import new_ulid
from alexa_mcp_server.llm import Embedder
from alexa_mcp_server.matching import DEDUP_THRESHOLD, normalize, similarity, tiered_match
from alexa_mcp_server.refine import Refiner
from alexa_mcp_server.safety import crisis
from alexa_mcp_server.store.base import Item, Store, user_pk
from alexa_mcp_server.timeutil import local, minutes_between, parse, utc_iso

Kind = Literal["fact", "person", "preference", "commitment"]
Result = dict[str, Any]

MAX_TEXT = 2000
MAX_DUE_MINUTES = 30 * 24 * 60
CLOSE_LOOP_MARGIN = 0.1
"""Fuzzy candidates closer than this to the best one make ``close_loop`` ask instead of guess."""


def error(code: str, message: str, speak: str) -> Result:
    return {"error": {"code": code, "message": message}, "speak": speak}


# --- profile ------------------------------------------------------------------------------


def _stored_profile(store: Store, user_id: str) -> dict[str, Any]:
    item = store.get(user_pk(user_id), "PROFILE")
    return item["doc"] if item else {}


def _people(store: Store, user_id: str) -> list[Item]:
    return store.query(user_pk(user_id), "PERSON#")


def _person_view(person: Item) -> dict[str, Any]:
    return {
        "role": person.get("role"),
        "notes": "; ".join(person.get("notes", [])),
        "aliases": person.get("aliases", []),
    }


def load_profile(store: Store, user_id: str) -> dict[str, Any]:
    """Full profile: defaults ← stored document, with ``people`` mirrored from ``PERSON#`` items."""
    doc = profile_schema.merge(profile_schema.DEFAULT_PROFILE, _stored_profile(store, user_id))
    doc["people"] = {p["name"]: _person_view(p) for p in _people(store, user_id)}
    return doc


def _tz(profile: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(profile["timezone"])


def _semantic(store: Store, profile: dict[str, Any], embedder: Embedder | None):
    """The embedding tier, unless the user turned embeddings off (``consent.embeddings``)."""
    return semantic.matcher(store, embedder if profile["consent"]["embeddings"] else None, _text_of)


def _people_aliases(store: Store, user_id: str) -> dict[str, list[str]]:
    return {p["name"]: p.get("aliases", []) for p in _people(store, user_id)}


# --- item shaping ---------------------------------------------------------------------------


def _person_text(person: Item) -> str:
    head = f"{person['name']}: {person['role']}" if person.get("role") else person["name"]
    return ". ".join([head, *person.get("notes", [])])


def _person_speak(person: Item) -> str:
    head = f"{person['name']} is your {person['role']}." if person.get("role") else f"About {person['name']}:"
    notes = " ".join(speech.second_person(n) + "." for n in person.get("notes", []))
    return f"{head} {notes}".strip()


def _text_of(item: Item) -> str:
    return _person_text(item) if item["sk"].startswith("PERSON#") else item["text"]


def _kind_of(item: Item) -> str:
    return "person" if item["sk"].startswith("PERSON#") else item["kind"]


def _memory_view(item: Item, tz: ZoneInfo) -> dict[str, Any]:
    view = {
        "id": item["sk"],
        "text": _text_of(item),
        "kind": _kind_of(item),
        "subject": item.get("name") if item["sk"].startswith("PERSON#") else item.get("subject"),
        "created_at": local(item.get("created_at"), tz),
    }
    if item.get("kind") == "commitment":
        view["due_at"] = local(item.get("due_at"), tz)
        view["status"] = item.get("status")
    return view


def _open_messages(store: Store, user_id: str) -> list[Item]:
    """Decoded inbox messages not yet handled; ``close_loop`` can mark them handled."""
    return [i for i in store.query(user_pk(user_id), "INBOX#") if i.get("decoded_at") and not i.get("resolved_at")]


def _loop_text(item: Item) -> str:
    if item["sk"].startswith("INBOX#"):
        return f"the message from {item.get('sender') or 'someone'}"
    return item["text"]


def _loop_match_text(item: Item) -> str:
    """What ``close_loop`` matches against: for a message, its label, sender and opening words."""
    if item["sk"].startswith("INBOX#"):
        return f"{_loop_text(item)} email message {item['text'][:300]}"
    return item["text"]


def _loop_view(item: Item, tz: ZoneInfo) -> dict[str, Any]:
    view = {"id": item["sk"], "text": _loop_text(item)}
    if item.get("due_at"):
        view["due_at"] = local(item["due_at"], tz)
    return view


def _open_loop_items(store: Store, user_id: str) -> list[Item]:
    loops = [
        m for m in store.query(user_pk(user_id), "MEM#") if m.get("kind") == "commitment" and m.get("status") == "open"
    ]
    # Soonest due first; undated loops after dated ones, oldest first.
    return sorted(loops, key=lambda m: (m.get("due_at") is None, m.get("due_at") or "", m.get("created_at") or ""))


# --- tools ----------------------------------------------------------------------------------


def remember(
    store: Store,
    user_id: str,
    text: str,
    now: datetime,
    kind: Kind = "fact",
    subject: str | None = None,
    due_at: str | None = None,
    refiner: Refiner | None = None,
    guard: Any = None,
    inbox_id: str | None = None,
    due_in_minutes: int | None = None,
) -> Result:
    """``guard`` is the model-based crisis check (``safety.crisis.Guard``); ``inbox_id`` links a
    "remind me to reply" commitment to its message (Telegram button). ``due_in_minutes`` is resolved
    with the server clock, so "in 30 minutes" needs no time zone from the caller."""
    text = text.strip()
    subject = subject.strip() if subject and subject.strip() else None
    if not text or len(text) > MAX_TEXT:
        return error("INVALID_ARGUMENT", f"text must be 1 to {MAX_TEXT} characters", "I didn't catch what to remember.")
    if kind == "person" and not subject:
        return error("INVALID_ARGUMENT", "subject (the person's name) is required", "Who is this about?")
    if due_at and due_in_minutes is not None:
        return error("INVALID_ARGUMENT", "pass due_at or due_in_minutes, not both", "When is that due?")
    if (due_at or due_in_minutes is not None) and kind != "commitment":
        return error("INVALID_ARGUMENT", "due_at is only for commitments", "I can only set a due time on a commitment.")
    if due_in_minutes is not None and not 1 <= due_in_minutes <= MAX_DUE_MINUTES:
        return error(
            "INVALID_ARGUMENT", f"due_in_minutes must be 1 to {MAX_DUE_MINUTES}", "I didn't understand when that's due."
        )

    check = crisis.precheck(store, user_id, text, now, guard=guard, refiner=refiner)
    if check.crisis:
        return check.crisis

    pk = user_pk(user_id)
    profile = load_profile(store, user_id)
    tz = _tz(profile)
    due_utc = None
    if due_at:
        try:
            due_utc = utc_iso(parse(due_at, tz))
        except ValueError:
            return error("INVALID_ARGUMENT", "due_at must be ISO 8601", "I didn't understand when that's due.")
    elif due_in_minutes is not None:
        due_utc = utc_iso(now + timedelta(minutes=due_in_minutes))
    stamp = utc_iso(now)
    said = speech.second_person(text)

    if kind == "person":
        sk = f"PERSON#{normalize(subject)}"
        person = store.get(pk, sk) or {"name": subject, "role": None, "notes": [], "aliases": [], "created_at": stamp}
        notes = person.get("notes", [])
        deduplicated = any(similarity(text, note) >= DEDUP_THRESHOLD for note in notes)
        if not deduplicated:
            notes.append(text)
        store.put(pk, sk, {**person, "notes": notes, "updated_at": stamp, "embedding": None})
        crisis.attach(store, user_id, check, sk)
        if refiner and profile["consent"]["embeddings"]:
            refiner.submit("embed", user_id, sk)
        return {"id": sk, "kind": kind, "deduplicated": deduplicated, "speak": f"Got it. I'll remember {said}."}

    existing = next(
        (
            m
            for m in store.query(pk, "MEM#")
            if m.get("kind") == kind
            and normalize(m.get("subject") or "") == normalize(subject or "")
            and m.get("status") != "done"
            and similarity(text, m["text"]) >= DEDUP_THRESHOLD
        ),
        None,
    )
    if existing:
        sk = existing["sk"]
        doc = {**existing, "text": text, "updated_at": stamp, "embedding": None}
        if due_utc:
            doc["due_at"] = due_utc
    else:
        sk = f"MEM#{new_ulid()}"
        doc = {
            "kind": kind,
            "text": text,
            "subject": subject,
            "due_at": due_utc,
            "status": "open" if kind == "commitment" else None,
            "embedding": None,  # filled by the "embed" refine job, or backfilled on first scan
            "created_at": stamp,
            "updated_at": stamp,
        }
        if inbox_id:
            doc["inbox_id"] = inbox_id
    store.put(pk, sk, doc)
    crisis.attach(store, user_id, check, sk)
    if refiner and profile["consent"]["embeddings"]:
        refiner.submit("embed", user_id, sk)

    result: Result = {"id": sk, "kind": kind, "deduplicated": existing is not None}
    speak = f"Got it. I'll remember {said}."
    if doc.get("due_at"):
        result["due_at"] = local(doc["due_at"], tz)
        speak += f" Due {speech.when(datetime.fromisoformat(doc['due_at']).astimezone(tz), now.astimezone(tz))}."
    return {**result, "speak": speak}


def recall(
    store: Store,
    user_id: str,
    query: str,
    now: datetime,
    kind: Kind | None = None,
    limit: int = 5,
    embedder: Embedder | None = None,
) -> Result:
    limit = max(1, min(limit, 20))
    profile = load_profile(store, user_id)
    tz = _tz(profile)
    pk = user_pk(user_id)
    items = [m for m in store.query(pk, "MEM#") if kind is None or m.get("kind") == kind]
    if kind in (None, "person"):
        items += _people(store, user_id)

    resolution, hits = tiered_match(
        query, items, _people_aliases(store, user_id), text_of=_text_of, semantic=_semantic(store, profile, embedder)
    )
    matches = [{**_memory_view(h.item, tz), "resolution": resolution} for h in hits[:limit]]
    if not matches:
        return {"matches": [], "speak": f"I don't have anything saved about {speech.second_person(query)}."}

    top = hits[0].item
    if top["sk"].startswith("PERSON#"):
        speak = _person_speak(top)
    else:
        created = datetime.fromisoformat(top["created_at"]).astimezone(tz)
        speak = (
            f"You told me {speech.day_phrase(created, now.astimezone(tz))} that {speech.second_person(top['text'])}."
        )
    if len(matches) > 1:
        more = len(matches) - 1
        speak += f" I have {speech.number_word(more)} more {'thing' if more == 1 else 'things'} about that too."
    return {"matches": matches, "speak": speak}


def open_loops(store: Store, user_id: str, now: datetime, limit: int = 5) -> Result:
    limit = max(1, min(limit, 20))
    tz = _tz(load_profile(store, user_id))
    loops = _open_loop_items(store, user_id)
    shown = loops[:limit]
    if not shown:
        return {"loops": [], "speak": "Nothing is open right now."}
    spoken = speech.join_spoken([speech.second_person(m["text"]) for m in shown])
    count = len(loops)
    speak = f"{speech.number_word(count).capitalize()} {'thing is' if count == 1 else 'things are'} open: {spoken}."
    return {"loops": [_loop_view(m, tz) for m in shown], "speak": speak}


def close_loop(store: Store, user_id: str, text: str, now: datetime, embedder: Embedder | None = None) -> Result:
    profile = load_profile(store, user_id)
    tz = _tz(profile)
    loops = _open_loop_items(store, user_id) + _open_messages(store, user_id)
    resolution, hits = tiered_match(
        text,
        loops,
        _people_aliases(store, user_id),
        text_of=_loop_match_text,
        semantic=_semantic(store, profile, embedder),
    )
    if not hits:
        return {"closed": None, "speak": "I couldn't find an open item like that."}

    ambiguous = len(hits) > 1 and (
        resolution in ("exact", "alias") or hits[1].score >= hits[0].score - CLOSE_LOOP_MARGIN
    )
    if ambiguous:
        candidates = [_loop_view(h.item, tz) for h in hits[:3]]
        options = " or ".join(speech.second_person(c["text"]) for c in candidates)
        return {"closed": None, "candidates": candidates, "speak": f"Which one: {options}?"}

    item = hits[0].item
    pk = user_pk(user_id)
    if item["sk"].startswith("INBOX#"):
        store.put(pk, item["sk"], {**item, "resolved_at": utc_iso(now)}, ttl=item.get("ttl"))
        label = _loop_text(item)
        return {"closed": {"id": item["sk"], "text": label}, "speak": f"Done. I marked {label} as handled."}
    store.put(pk, item["sk"], {**item, "status": "done", "closed_at": utc_iso(now)})
    if item.get("inbox_id"):  # a "remind me to reply" commitment resolves its message
        message = store.get(pk, item["inbox_id"])
        if message:
            store.put(pk, message["sk"], {**message, "resolved_at": utc_iso(now)}, ttl=message.get("ttl"))
    return {
        "closed": {"id": item["sk"], "text": item["text"]},
        "speak": f"Done. I closed {speech.second_person(item['text'])}.",
    }


def what_was_i_doing(store: Store, user_id: str, now: datetime) -> Result:
    pk = user_pk(user_id)
    tz = _tz(load_profile(store, user_id))
    state = store.get(pk, "STATE") or {}
    blocks = store.query(pk, "BLOCK#")

    current = store.get(pk, state["open_block_id"]) if state.get("open_block_id") else None
    if current and current.get("ended_at"):
        current = None
    finished = sorted((b for b in blocks if b.get("ended_at")), key=lambda b: b["ended_at"])
    last = finished[-1] if finished else None

    memories = sorted(
        (m for m in store.query(pk, "MEM#") if m.get("kind") != "commitment"),
        key=lambda m: m.get("created_at") or "",
        reverse=True,
    )[:3]
    loops = _open_loop_items(store, user_id)

    result: Result = {
        "recent_memories": [_memory_view(m, tz) for m in memories],
        "open_loops": [_loop_view(m, tz) for m in loops[:3]],
    }
    parts: list[str] = []
    if current:
        elapsed = minutes_between(current["started_at"], now)
        result["current_block"] = {
            "id": current["sk"],
            "task": current["task"],
            "started_at": local(current["started_at"], tz),
            "elapsed_minutes": round(elapsed),
        }
        parts.append(f"You were working on {speech.second_person(current['task'])}.")
        parts.append(f"You started {speech.duration(elapsed)} ago.")
    if last:
        result["last_block"] = {
            "id": last["sk"],
            "task": last["task"],
            "started_at": local(last["started_at"], tz),
            "ended_at": local(last["ended_at"], tz),
        }
        if not current:
            task = speech.second_person(last["task"])
            ago = speech.duration(minutes_between(last["ended_at"], now))
            parts.append(f"The last thing you worked on was {task}. You stopped {ago} ago.")
    if loops:
        shown = [speech.second_person(m["text"]) for m in loops[:3]]
        count = len(loops)
        lead = "One thing is" if count == 1 else f"{speech.number_word(count).capitalize()} things are"
        lead += " still open"
        parts.append(f"{lead}: {speech.join_spoken(shown)}.")
    if not parts:
        parts.append("I don't have anything recent saved yet.")
    result["speak"] = " ".join(parts)
    return result


def get_profile(store: Store, user_id: str) -> Result:
    profile = load_profile(store, user_id)
    name = profile.get("display_name")
    people = len(profile["people"])
    speak = f"You're set up as {name}" if name else "Your profile has no name yet"
    speak += f", in the {profile['timezone']} time zone. I know about {speech.number_word(people)} "
    speak += "person." if people == 1 else "people."
    return {**profile, "speak": speak}


def set_preference(store: Store, user_id: str, key: str, value: Any, now: datetime) -> Result:
    key = key.strip()
    if key == "people" or key.startswith("people."):
        return error("INVALID_ARGUMENT", "people are saved with remember(kind=person)", "Tell me about them instead.")
    current = load_profile(store, user_id)
    try:
        clean = profile_schema.validate(key, value, current)
    except KeyError:
        return error("INVALID_ARGUMENT", f"unknown preference {key!r}", "I don't have a setting with that name.")
    except profile_schema.InvalidValue as exc:
        return error("INVALID_ARGUMENT", f"{key} {exc}", f"That value doesn't work. It {exc}.")

    stored = _stored_profile(store, user_id)
    profile_schema.set_path(stored, key, clean)
    store.put(user_pk(user_id), "PROFILE", {"doc": stored, "updated_at": utc_iso(now)})
    label = key.rsplit(".", 1)[-1].replace("_", " ")
    spoken = "off" if clean is False else "on" if clean is True else "not set" if clean is None else clean
    if isinstance(spoken, list):
        spoken = speech.join_spoken(spoken) or "empty"
    return {
        "key": key,
        "old_value": profile_schema.get_path(current, key),
        "new_value": clean,
        "speak": f"Done. {label.capitalize()} is now {spoken}.",
    }


def export_all(store: Store, user_id: str) -> Result:
    items = store.query(user_pk(user_id))
    count = len(items)
    return {"items": items, "count": count, "speak": f"Exported {count} item{'' if count == 1 else 's'}."}


def delete_all(store: Store, user_id: str, confirm: bool = False) -> Result:
    if not confirm:
        return error(
            "CONFIRMATION_REQUIRED",
            "call again with confirm=true to delete everything",
            "This deletes everything I've saved for you, and it can't be undone. Are you sure?",
        )
    from alexa_mcp_server.pillars.inbox import revoke_inbox_tokens

    revoke_inbox_tokens(store, user_id)
    count = store.delete_partition(user_pk(user_id))
    return {"deleted": count, "speak": "Done. Everything I had saved for you is deleted."}


# --- seed -----------------------------------------------------------------------------------


def seed(store: Store, user_id: str, data: dict[str, Any], now: datetime) -> dict[str, int]:
    """Load a demo seed (see ``profile_seed.yaml``). Times are relative to ``now`` so the demo stays fresh."""
    pk = user_pk(user_id)
    stamp = utc_iso(now)
    store.put(pk, "PROFILE", {"doc": profile_schema.validate_document(data.get("profile", {})), "updated_at": stamp})

    for name, info in (data.get("people") or {}).items():
        notes = info.get("notes") or []
        store.put(
            pk,
            f"PERSON#{normalize(name)}",
            {
                "name": name,
                "role": info.get("role"),
                "notes": [notes] if isinstance(notes, str) else list(notes),
                "aliases": list(info.get("aliases") or []),
                "created_at": stamp,
                "updated_at": stamp,
            },
        )

    memories = data.get("memories") or []
    for mem in memories:
        created = utc_iso(now - timedelta(minutes=mem.get("ago_minutes", 0)))
        due = mem.get("due_in_minutes")
        kind = mem.get("kind", "fact")
        store.put(
            pk,
            f"MEM#{new_ulid()}",
            {
                "kind": kind,
                "text": mem["text"],
                "subject": mem.get("subject"),
                "due_at": utc_iso(now + timedelta(minutes=due)) if due is not None else None,
                "travel_minutes": mem.get("travel_minutes"),
                "status": "open" if kind == "commitment" else None,
                "embedding": None,
                "created_at": created,
                "updated_at": created,
            },
        )

    blocks = data.get("blocks") or []
    state: dict[str, Any] = {}
    for block in blocks:
        sk = f"BLOCK#{new_ulid()}"
        ended = block.get("ended_minutes_ago")
        store.put(
            pk,
            sk,
            {
                "task": block["task"],
                "started_at": utc_iso(now - timedelta(minutes=block["started_minutes_ago"])),
                "ended_at": utc_iso(now - timedelta(minutes=ended)) if ended is not None else None,
                "summary": block.get("summary"),
            },
        )
        if ended is None:
            state["open_block_id"] = sk
    if state:
        store.put(pk, "STATE", state)
    return {"people": len(data.get("people") or {}), "memories": len(memories), "blocks": len(blocks)}
