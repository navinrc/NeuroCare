"""Profile schema, defaults, and validation (spec §7)."""

import copy
import re
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_PROFILE: dict[str, Any] = {
    "display_name": None,
    "timezone": "America/New_York",
    "locale": "en-US",
    "style": {"register": "plain", "max_steps_spoken": 1, "literal": True},
    "time": {
        "end_of_day": None,
        "leave_buffer_minutes": 15,
        "checkin_thresholds": {"gentle": 60, "nudge": 90, "hard": 120},
        "energy_zones": {
            "early": "05:00-08:00",
            "morning": "08:00-12:00",
            "midday": "12:00-14:00",
            "afternoon_dip": "14:00-17:00",
            "evening": "17:00-21:00",
            "late_night": "21:00-05:00",
        },
    },
    "guardrail": {
        "rumination_threshold": 3,
        "rumination_window_minutes": 90,
        "need_intervals": {"water": 120, "food": 300, "break": 90},
        "preferred_redirects": [
            "Write down the one thing you're worried about and set it aside until tomorrow",
            "Do the next small physical step",
            "Switch to something else on purpose for 15 minutes",
        ],
    },
    "people": {},
    "consent": {"embeddings": True},
    "plan": {"max_priorities": 3, "rollover": True},
    "telegram": {
        "pushes": {"morning": False, "reply_nudge": False, "wrap_up": False},
        "max_push_per_day": 3,
        "quiet_hours": "21:00-08:00",
        "morning_at": "08:30",
    },
    "email": {"allowed_senders": []},
}


class InvalidValue(ValueError):
    pass


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _int(lo: int, hi: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool):
            raise InvalidValue("must be a whole number")
        try:
            number = int(str(value).strip())
        except ValueError:
            raise InvalidValue("must be a whole number") from None
        if not lo <= number <= hi:
            raise InvalidValue(f"must be between {lo} and {hi}")
        return number

    return check


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "on", "1"}:
        return True
    if text in {"false", "no", "off", "0"}:
        return False
    raise InvalidValue("must be true or false")


def _enum(*choices: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        text = str(value).strip().lower()
        if text not in choices:
            raise InvalidValue(f"must be one of: {', '.join(choices)}")
        return text

    return check


def _hhmm(value: Any) -> str:
    text = str(value).strip()
    if not _HHMM.match(text):
        raise InvalidValue("must be a time like 18:00")
    return text


def _optional_hhmm(value: Any) -> str | None:
    if value is None or str(value).strip().lower() in {"", "none", "null"}:
        return None
    return _hhmm(value)


def _hhmm_range(value: Any) -> str:
    parts = str(value).replace(" ", "").split("-")
    if len(parts) != 2:
        raise InvalidValue("must be a range like 21:00-08:00")
    return f"{_hhmm(parts[0])}-{_hhmm(parts[1])}"


def _timezone(value: Any) -> str:
    try:
        ZoneInfo(str(value).strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidValue("must be an IANA time zone like America/New_York") from None
    return str(value).strip()


def _locale(value: Any) -> str:
    text = str(value).strip()
    if not re.match(r"^[a-z]{2}-[A-Z]{2}$", text):
        raise InvalidValue("must be a locale like en-US")
    return text


def _text(max_len: int) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        text = str(value).strip()
        if not text or len(text) > max_len:
            raise InvalidValue(f"must be 1 to {max_len} characters")
        return text

    return check


def _str_list(item: Callable[[Any], str]) -> Callable[[Any], list[str]]:
    def check(value: Any) -> list[str]:
        if isinstance(value, str):
            value = [part for part in value.split(",") if part.strip()]
        if not isinstance(value, list):
            raise InvalidValue("must be a list")
        return [item(v) for v in value]

    return check


def _email(value: Any) -> str:
    text = str(value).strip().lower()
    if not _EMAIL.match(text):
        raise InvalidValue(f"{text!r} is not an email address")
    return text


VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "display_name": _text(80),
    "timezone": _timezone,
    "locale": _locale,
    "style.register": _enum("plain", "warm", "formal"),
    "style.max_steps_spoken": _int(1, 5),
    "style.literal": _bool,
    "time.end_of_day": _optional_hhmm,
    "time.leave_buffer_minutes": _int(0, 120),
    **{f"time.checkin_thresholds.{level}": _int(15, 480) for level in ("gentle", "nudge", "hard")},
    **{f"time.energy_zones.{zone}": _hhmm_range for zone in DEFAULT_PROFILE["time"]["energy_zones"]},
    "guardrail.rumination_threshold": _int(2, 20),
    "guardrail.rumination_window_minutes": _int(5, 1440),
    **{f"guardrail.need_intervals.{need}": _int(15, 1440) for need in ("water", "food", "break")},
    "guardrail.preferred_redirects": _str_list(_text(200)),
    "consent.embeddings": _bool,
    "plan.max_priorities": _int(1, 3),
    "plan.rollover": _bool,
    **{f"telegram.pushes.{kind}": _bool for kind in ("morning", "reply_nudge", "wrap_up")},
    "telegram.max_push_per_day": _int(0, 5),
    "telegram.quiet_hours": _hhmm_range,
    "telegram.morning_at": _hhmm,
    "email.allowed_senders": _str_list(_email),
}


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge; ``override`` wins. Neither input is modified."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def get_path(doc: dict[str, Any], path: str) -> Any:
    node: Any = doc
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def set_path(doc: dict[str, Any], path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    node = doc
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def validate(path: str, value: Any, profile: dict[str, Any]) -> Any:
    """Validated value for ``path`` given the current full ``profile``. Raises ``KeyError`` or ``InvalidValue``."""
    if path not in VALIDATORS:
        raise KeyError(path)
    clean = VALIDATORS[path](value)
    if path.startswith("time.checkin_thresholds."):
        thresholds = {**profile["time"]["checkin_thresholds"], path.rsplit(".", 1)[1]: clean}
        if not thresholds["gentle"] < thresholds["nudge"] < thresholds["hard"]:
            raise InvalidValue("check-in thresholds must go gentle < nudge < hard")
    return clean


def validate_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate every leaf of a (partial) profile document, e.g. a seed file. ``people`` passes through."""
    out: dict[str, Any] = {}
    merged = merge(DEFAULT_PROFILE, {k: v for k, v in doc.items() if k != "people"})

    def walk(node: dict[str, Any], prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}{key}"
            if path in VALIDATORS:
                set_path(out, path, validate(path, value, merged))
            elif isinstance(value, dict):
                walk(value, f"{path}.")
            else:
                raise KeyError(path)

    walk({k: v for k, v in doc.items() if k != "people"}, "")
    return out
