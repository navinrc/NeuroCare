"""Timestamp helpers. Stored times are UTC ISO 8601; results use the user's profile time zone."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse(value: str, tz: ZoneInfo) -> datetime:
    """Parse ISO 8601; a value without an offset is read in ``tz``."""
    dt = datetime.fromisoformat(value.strip())
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


def local(value: str | None, tz: ZoneInfo) -> str | None:
    return datetime.fromisoformat(value).astimezone(tz).isoformat(timespec="seconds") if value else None


def minutes_between(start: str, end: datetime) -> float:
    return (end - datetime.fromisoformat(start)).total_seconds() / 60
