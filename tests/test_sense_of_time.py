from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import NOW, USER

from alexa_mcp_server.pillars import memory, sense_of_time
from alexa_mcp_server.profile import DEFAULT_PROFILE
from alexa_mcp_server.store.base import user_pk
from alexa_mcp_server.timeutil import utc_iso

EVENING = datetime(2026, 10, 5, 23, 0, tzinfo=UTC)  # 7 PM New York, after the seed's 18:00 end of day


def _block_running(store, minutes, now=NOW, task="the slides"):
    sense_of_time.start_block(store, USER, task, now - timedelta(minutes=minutes))


def _commitment(store, text, due_in, travel=None):
    store.put(
        user_pk(USER),
        f"MEM#{text}",
        {
            "kind": "commitment",
            "text": text,
            "due_at": utc_iso(NOW + timedelta(minutes=due_in)),
            "travel_minutes": travel,
            "status": "open",
            "created_at": utc_iso(NOW),
        },
    )


@pytest.mark.parametrize(
    ("minutes", "level"),
    [(0, "none"), (59, "none"), (60, "gentle"), (89, "gentle"), (90, "nudge"), (119, "nudge"), (120, "hard")],
)
def test_check_in_levels_during_the_day(seeded, minutes, level):
    _block_running(seeded, minutes)
    result = sense_of_time.check_in(seeded, USER, NOW)
    assert result["level"] == level
    assert result["elapsed_minutes"] == minutes
    assert result["task"] == "the slides"


@pytest.mark.parametrize(
    ("minutes", "level"),
    [(0, "gentle"), (59, "gentle"), (60, "nudge"), (89, "nudge"), (90, "hard"), (119, "hard"), (120, "hard")],
)
def test_check_in_levels_after_end_of_day(seeded, minutes, level):
    _block_running(seeded, minutes, now=EVENING)
    result = sense_of_time.check_in(seeded, USER, EVENING)
    assert result["level"] == level
    assert "It's after your end of day." in result["speak"]


@pytest.mark.parametrize(
    ("local_hour", "late"),
    [(17, False), (18, True), (23, True), (1, True), (4, True), (5, False), (9, False)],
)
def test_after_end_of_day_wraps_past_midnight(local_hour, late):
    now_local = datetime(2026, 10, 5, local_hour, 30, tzinfo=ZoneInfo("America/New_York"))
    assert sense_of_time.after_end_of_day(now_local, "18:00") is late
    assert sense_of_time.after_end_of_day(now_local, None) is False


def test_check_in_uses_profile_thresholds(seeded):
    for level, minutes in (("gentle", 20), ("nudge", 40), ("hard", 60)):
        assert "error" not in memory.set_preference(seeded, USER, f"time.checkin_thresholds.{level}", minutes, NOW)
    _block_running(seeded, 45)
    assert sense_of_time.check_in(seeded, USER, NOW)["level"] == "nudge"


def test_check_in_speak_and_offers(seeded):
    _block_running(seeded, 30, task="my budget email")
    calm = sense_of_time.check_in(seeded, USER, NOW)
    assert calm["speak"] == "You started your budget email about 30 minutes ago."
    assert calm["override_options"] == [] and "suggest_reminder_minutes" not in calm

    gentle = sense_of_time.check_in(seeded, USER, NOW + timedelta(minutes=35))
    assert gentle["suggest_reminder_minutes"] == 25
    assert gentle["speak"].endswith("Want a reminder in 25 minutes?")
    assert gentle["override_options"] == sense_of_time.OVERRIDE_OPTIONS

    nudge = sense_of_time.check_in(seeded, USER, NOW + timedelta(minutes=60))
    assert (
        nudge["speak"]
        == "You started your budget email about an hour and a half ago. Want a 5-minute break, or keep going?"
    )
    assert "suggest_reminder_minutes" not in nudge


def test_check_in_reminder_uses_shifted_threshold_after_end_of_day(seeded):
    _block_running(seeded, 40, now=EVENING)
    result = sense_of_time.check_in(seeded, USER, EVENING)
    assert result["level"] == "gentle"
    assert result["suggest_reminder_minutes"] == 20  # nudge starts at the gentle threshold (60) after end of day


def test_check_in_without_block(store):
    result = sense_of_time.check_in(store, USER, NOW)
    assert result == {
        "level": "none",
        "elapsed_minutes": None,
        "task": None,
        "override_options": [],
        "speak": "Nothing is running right now.",
    }


def test_start_block_auto_closes_previous(seeded):
    result = sense_of_time.start_block(seeded, USER, "the slides", NOW)
    assert result["auto_closed"] == {"task": "the budget email", "minutes": 40}
    assert result["started_at"] == "2026-10-05T14:10:00-04:00"
    assert result["speak"] == "Started the slides. I stopped the budget email after about 40 minutes."

    now = sense_of_time.now_context(seeded, USER, NOW + timedelta(minutes=10))
    assert now["current_block"]["task"] == "the slides"
    doing = memory.what_was_i_doing(seeded, USER, NOW + timedelta(minutes=10))
    assert doing["last_block"]["task"] == "the budget email"


def test_start_block_same_task_keeps_timer(seeded):
    result = sense_of_time.start_block(seeded, USER, "The budget email", NOW)
    assert result["already_open"] is True
    assert result["speak"] == "You're already on The budget email. You started about 40 minutes ago."
    assert sense_of_time.check_in(seeded, USER, NOW)["elapsed_minutes"] == 40


def test_start_block_validation(store):
    assert sense_of_time.start_block(store, USER, "   ", NOW)["error"]["code"] == "INVALID_ARGUMENT"
    assert sense_of_time.start_block(store, USER, "x" * 201, NOW)["error"]["code"] == "INVALID_ARGUMENT"


def test_end_block(seeded):
    result = sense_of_time.end_block(seeded, USER, NOW, summary="sent the draft")
    assert result == {
        "task": "the budget email",
        "minutes": 40,
        "speak": "Stopped the budget email after about 40 minutes.",
    }
    block = seeded.query(user_pk(USER), "BLOCK#")[0]
    assert block["summary"] == "sent the draft" and block["ended_at"] == utc_iso(NOW)

    assert sense_of_time.end_block(seeded, USER, NOW)["error"]["code"] == "NOT_FOUND"
    assert sense_of_time.check_in(seeded, USER, NOW)["level"] == "none"
    assert "current_block" not in sense_of_time.now_context(seeded, USER, NOW)


def test_now_context_with_leave_by(seeded):
    _commitment(seeded, "Call with Alex at the studio", due_in=50, travel=20)
    result = sense_of_time.now_context(seeded, USER, NOW)
    assert result["now"] == "2026-10-05T14:10:00-04:00"
    assert result["day_of_week"] == "Monday"
    assert result["energy_zone"] == "afternoon_dip"
    assert result["current_block"] == {
        "task": "the budget email",
        "started_at": "2026-10-05T13:30:00-04:00",
        "elapsed_minutes": 40,
    }
    # leave_by = due (15:00) − travel (20) − leave buffer (15)
    assert result["next_commitment"] == {
        "text": "Call with Alex at the studio",
        "due_at": "2026-10-05T15:00:00-04:00",
        "minutes_until": 50,
        "leave_by": "2026-10-05T14:25:00-04:00",
    }
    assert result["speak"] == (
        "It's 2:10 PM on Monday. You've been on the budget email for about 40 minutes. "
        "Next: Call with Alex at the studio, today at 3 PM. Leave by 2:25 PM."
    )


def test_now_context_leave_by_uses_profile_buffer_and_past_time(seeded):
    memory.set_preference(seeded, USER, "time.leave_buffer_minutes", 0, NOW)
    _commitment(seeded, "Dentist", due_in=10, travel=30)
    result = sense_of_time.now_context(seeded, USER, NOW)
    assert result["next_commitment"]["leave_by"] == "2026-10-05T13:50:00-04:00"
    assert result["speak"].endswith("You planned to leave by 1:50 PM.")


def test_now_context_without_travel_has_no_leave_by(seeded):
    _commitment(seeded, "Call with Alex", due_in=35)
    result = sense_of_time.now_context(seeded, USER, NOW)
    assert "leave_by" not in result["next_commitment"]
    assert result["speak"].endswith("Next: Call with Alex, today at 2:45 PM. That's in about 35 minutes.")


def test_now_context_skips_overdue_and_done(seeded):
    _commitment(seeded, "Overdue thing", due_in=-5)
    result = sense_of_time.now_context(seeded, USER, NOW)
    assert result["next_commitment"]["text"] == "Send Priya the Q3 deck"  # seeded, due tomorrow
    assert result["speak"].endswith("Next: Send Priya the Q3 deck, tomorrow at 2:10 PM.")

    memory.close_loop(seeded, USER, "Q3 deck", NOW)
    assert "next_commitment" not in sense_of_time.now_context(seeded, USER, NOW)


def test_now_context_empty(store):
    result = sense_of_time.now_context(store, USER, NOW)
    assert result == {
        "now": "2026-10-05T14:10:00-04:00",
        "day_of_week": "Monday",
        "energy_zone": "afternoon_dip",
        "speak": "It's 2:10 PM on Monday.",
    }


@pytest.mark.parametrize(
    ("hour", "minute", "zone"),
    [
        (5, 0, "early"),
        (7, 59, "early"),
        (8, 0, "morning"),
        (13, 0, "midday"),
        (20, 59, "evening"),
        (21, 0, "late_night"),
        (2, 0, "late_night"),
        (4, 59, "late_night"),
    ],
)
def test_energy_zone_boundaries(hour, minute, zone):
    now_local = datetime(2026, 10, 5, hour, minute)
    assert sense_of_time.energy_zone(now_local, DEFAULT_PROFILE["time"]["energy_zones"]) == zone
