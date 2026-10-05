"""Helpers for short, literal spoken text (spec §4: ``speak`` field)."""

import re
from datetime import datetime

_NUMBER_WORDS = "zero one two three four five six seven eight nine ten".split()

_PERSON_SWAP = {
    "i'm": "you're",
    "im": "you're",
    "i've": "you've",
    "i'll": "you'll",
    "i'd": "you'd",
    "i": "you",
    "me": "you",
    "my": "your",
    "mine": "yours",
    "myself": "yourself",
    "am": "are",
}


def number_word(n: int) -> str:
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def second_person(text: str) -> str:
    """Turn the user's own words ("my manager") into how Alexa says them back ("your manager")."""
    text = text.strip().rstrip(".")

    def swap(match: re.Match[str]) -> str:
        word = match.group(0)
        return _PERSON_SWAP.get(word.lower(), word)

    swapped = re.sub(r"\b(?:i'm|i've|i'll|i'd|im|i|me|my|mine|myself)\b", swap, text, flags=re.IGNORECASE)
    # "am" only follows "I", which is now "you".
    return re.sub(r"\byou am\b", "you are", swapped, flags=re.IGNORECASE)


def join_spoken(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def duration(minutes: float) -> str:
    """Rounded spoken duration: "about 40 minutes", "about an hour and ten minutes"."""
    m = round(minutes)
    if m < 1:
        return "less than a minute"
    if m < 60:
        if m >= 10:
            m = round(m / 5) * 5
        return f"about {m} minute{'s' if m != 1 else ''}"
    hours, rest = divmod(round(m / 5) * 5, 60)
    hour_part = "an hour" if hours == 1 else f"{number_word(hours)} hours"
    if rest == 0:
        return f"about {hour_part}"
    if rest == 30:
        return f"about {'an hour and a half' if hours == 1 else f'{number_word(hours)} and a half hours'}"
    return f"about {hour_part} and {number_word(rest) if rest <= 10 else rest} minutes"


def clock_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour} {suffix}" if dt.minute == 0 else f"{hour}:{dt.minute:02d} {suffix}"


def day_phrase(dt: datetime, now: datetime) -> str:
    """Relative day: today, yesterday, tomorrow, "on Monday", "on March 3" (both datetimes in the user's tz)."""
    days = (dt.date() - now.date()).days
    if days == 0:
        return "today"
    if days == -1:
        return "yesterday"
    if days == 1:
        return "tomorrow"
    if -6 <= days <= 6:
        return f"on {dt:%A}"
    return f"on {dt:%B} {dt.day}"


def when(dt: datetime, now: datetime) -> str:
    """Day plus clock time: "today at 3 PM", "on Friday at 9:30 AM"."""
    return f"{day_phrase(dt, now)} at {clock_time(dt)}"
