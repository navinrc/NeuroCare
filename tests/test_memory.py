from datetime import timedelta

from conftest import NOW, USER

from alexa_mcp_server.pillars import memory


def test_remember_and_recall(store):
    saved = memory.remember(store, USER, "The report is due Friday", NOW)
    assert saved["kind"] == "fact" and not saved["deduplicated"]
    assert saved["speak"] == "Got it. I'll remember The report is due Friday."

    result = memory.recall(store, USER, "report", NOW)
    assert result["matches"][0]["id"] == saved["id"]
    assert result["matches"][0]["resolution"] == "exact"
    assert result["speak"] == "You told me today that The report is due Friday."


def test_remember_deduplicates_similar_text(store):
    first = memory.remember(store, USER, "The report is due Friday", NOW)
    second = memory.remember(store, USER, "The report is due on Friday", NOW)
    assert second["deduplicated"] and second["id"] == first["id"]
    other_kind = memory.remember(store, USER, "The report is due Friday", NOW, kind="preference")
    assert not other_kind["deduplicated"]


def test_remember_validation(store):
    assert memory.remember(store, USER, "  ", NOW)["error"]["code"] == "INVALID_ARGUMENT"
    assert memory.remember(store, USER, "x" * 2001, NOW)["error"]["code"] == "INVALID_ARGUMENT"
    assert memory.remember(store, USER, "my manager", NOW, kind="person")["error"]["code"] == "INVALID_ARGUMENT"
    bad_due = memory.remember(store, USER, "fact", NOW, due_at="2026-10-06T10:00")
    assert bad_due["error"]["code"] == "INVALID_ARGUMENT"
    bad_date = memory.remember(store, USER, "call", NOW, kind="commitment", due_at="soon")
    assert bad_date["error"]["code"] == "INVALID_ARGUMENT"


def test_remember_person_and_recall_by_alias(seeded):
    result = memory.remember(
        seeded, USER, "Priya is my manager and tends to be blunt", NOW, kind="person", subject="priya"
    )
    assert result["id"] == "PERSON#priya"
    assert result["speak"] == "Got it. I'll remember Priya is your manager and tends to be blunt."
    profile = memory.get_profile(seeded, USER)
    assert "tends to be blunt" in profile["people"]["Priya"]["notes"]

    found = memory.recall(seeded, USER, "what did I promise my boss", NOW)
    assert found["matches"][0]["resolution"] == "alias"
    assert any(m["subject"] == "Priya" for m in found["matches"])


def test_commitment_due_at_uses_profile_timezone(seeded):
    result = memory.remember(seeded, USER, "Call the bank", NOW, kind="commitment", due_at="2026-10-06T09:30")
    assert result["speak"].endswith("Due tomorrow at 9:30 AM.")
    loops = memory.open_loops(seeded, USER, NOW)["loops"]
    assert {"id": result["id"], "text": "Call the bank", "due_at": "2026-10-06T09:30:00-04:00"} in loops


def test_recall_empty_and_kind_filter(seeded):
    assert memory.recall(seeded, USER, "volcano", NOW) == {
        "matches": [],
        "speak": "I don't have anything saved about volcano.",
    }
    prefs = memory.recall(seeded, USER, "written instructions", NOW, kind="preference")
    assert [m["kind"] for m in prefs["matches"]] == ["preference"]
    assert memory.recall(seeded, USER, "written instructions", NOW, kind="fact")["matches"] == []


def test_open_loops_soonest_due_first(seeded):
    result = memory.open_loops(seeded, USER, NOW)
    assert [loop["text"] for loop in result["loops"]] == [
        "Send Priya the Q3 deck",
        "Book the dentist",
        "Reply to Jordan about the venue",
    ]
    assert result["speak"].startswith("Three things are open:")
    assert len(memory.open_loops(seeded, USER, NOW, limit=1)["loops"]) == 1


def test_close_loop(seeded):
    result = memory.close_loop(seeded, USER, "dentist", NOW)
    assert result["closed"]["text"] == "Book the dentist"
    assert "Book the dentist" not in [loop["text"] for loop in memory.open_loops(seeded, USER, NOW)["loops"]]
    assert memory.close_loop(seeded, USER, "dentist", NOW)["closed"] is None


def test_close_loop_asks_when_ambiguous(store):
    memory.remember(store, USER, "Reply to Sam", NOW, kind="commitment")
    memory.remember(store, USER, "Reply to Sara about lunch", NOW, kind="commitment")
    result = memory.close_loop(store, USER, "reply", NOW)
    assert result["closed"] is None
    assert len(result["candidates"]) == 2
    assert result["speak"].startswith("Which one:")
    assert len(memory.open_loops(store, USER, NOW)["loops"]) == 2


def test_what_was_i_doing_seeded(seeded):
    result = memory.what_was_i_doing(seeded, USER, NOW)
    assert result["current_block"]["task"] == "the budget email"
    assert result["current_block"]["elapsed_minutes"] == 40
    assert len(result["open_loops"]) == 3
    assert result["recent_memories"][0]["text"] == "I prefer written instructions over calls"
    assert result["speak"] == (
        "You were working on the budget email. You started about 40 minutes ago. "
        "Three things are still open: Send Priya the Q3 deck, Book the dentist, and Reply to Jordan about the venue."
    )


def test_what_was_i_doing_empty_and_last_block(store):
    assert memory.what_was_i_doing(store, USER, NOW)["speak"] == "I don't have anything recent saved yet."
    memory.seed(
        store, USER, {"blocks": [{"task": "the slides", "started_minutes_ago": 90, "ended_minutes_ago": 30}]}, NOW
    )
    result = memory.what_was_i_doing(store, USER, NOW)
    assert "current_block" not in result
    assert result["speak"] == "The last thing you worked on was the slides. You stopped about 30 minutes ago."


def test_get_profile_defaults_and_seed(store, seeded):
    profile = memory.get_profile(seeded, USER)
    assert profile["display_name"] == "Sam"
    assert profile["time"]["end_of_day"] == "18:00"
    assert profile["time"]["leave_buffer_minutes"] == 15
    assert profile["people"]["Priya"]["aliases"] == ["P", "my boss"]
    assert profile["speak"] == "You're set up as Sam, in the America/New_York time zone. I know about two people."


def test_set_preference(seeded):
    result = memory.set_preference(seeded, USER, "time.end_of_day", "17:30", NOW)
    assert (result["old_value"], result["new_value"]) == ("18:00", "17:30")
    assert result["speak"] == "Done. End of day is now 17:30."
    assert memory.get_profile(seeded, USER)["time"]["end_of_day"] == "17:30"
    assert memory.get_profile(seeded, USER)["display_name"] == "Sam"

    assert memory.set_preference(seeded, USER, "guardrail.rumination_threshold", "4", NOW)["new_value"] == 4
    assert memory.set_preference(seeded, USER, "style.literal", "no", NOW)["speak"] == "Done. Literal is now off."


def test_set_preference_rejects_bad_input(seeded):
    for key, value in [
        ("nope", 1),
        ("people", {}),
        ("guardrail.rumination_threshold", 1),
        ("timezone", "Mars/Olympus"),
        ("time.checkin_thresholds.gentle", 100),  # would exceed nudge (90)
        ("plan.max_priorities", True),
    ]:
        assert memory.set_preference(seeded, USER, key, value, NOW)["error"]["code"] == "INVALID_ARGUMENT", key


def test_export_and_delete_all(seeded):
    exported = memory.export_all(seeded, USER)
    assert exported["count"] == len(exported["items"]) == 10  # profile + 2 people + 5 memories + block + state

    refused = memory.delete_all(seeded, USER)
    assert refused["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert memory.export_all(seeded, USER)["count"] == 10

    assert memory.delete_all(seeded, USER, confirm=True)["deleted"] == 10
    assert memory.export_all(seeded, USER)["count"] == 0


def test_users_are_isolated(seeded):
    assert memory.recall(seeded, "someone-else", "dentist", NOW)["matches"] == []
    assert memory.open_loops(seeded, "someone-else", NOW + timedelta(days=1))["loops"] == []


def test_recall_person_speaks_naturally(seeded):
    result = memory.recall(seeded, USER, "Jordan", NOW, kind="person")
    assert result["speak"] == "Jordan is your teammate. Owns the Q3 deck design."
