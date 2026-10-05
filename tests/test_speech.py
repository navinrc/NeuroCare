from datetime import datetime

import pytest

from alexa_mcp_server.speech import clock_time, day_phrase, duration, join_spoken, second_person


@pytest.mark.parametrize(
    ("minutes", "spoken"),
    [
        (0.2, "less than a minute"),
        (1, "about 1 minute"),
        (7, "about 7 minutes"),
        (41, "about 40 minutes"),
        (60, "about an hour"),
        (70, "about an hour and ten minutes"),
        (90, "about an hour and a half"),
        (125, "about two hours and five minutes"),
        (210, "about three and a half hours"),
    ],
)
def test_duration(minutes, spoken):
    assert duration(minutes) == spoken


def test_second_person():
    assert second_person("Priya is my manager and I'm nervous.") == "Priya is your manager and you're nervous"
    assert second_person("I am tired") == "you are tired"
    assert second_person("Send Priya the deck") == "Send Priya the deck"


def test_join_spoken():
    assert join_spoken(["a"]) == "a"
    assert join_spoken(["a", "b", "c"]) == "a, b, and c"


def test_day_and_clock():
    now = datetime(2026, 10, 5, 14, 10)  # Monday
    assert day_phrase(datetime(2026, 10, 5, 9), now) == "today"
    assert day_phrase(datetime(2026, 10, 4, 9), now) == "yesterday"
    assert day_phrase(datetime(2026, 10, 9, 9), now) == "on Friday"
    assert day_phrase(datetime(2026, 11, 20, 9), now) == "on November 20"
    assert clock_time(datetime(2026, 10, 5, 15, 0)) == "3 PM"
    assert clock_time(datetime(2026, 10, 5, 0, 30)) == "12:30 AM"
