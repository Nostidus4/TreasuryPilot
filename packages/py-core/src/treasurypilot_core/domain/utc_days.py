"""UTC calendar-day helpers used by the rolling planning horizon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SECONDS_PER_DAY = 86_400
MIDNIGHT_CUTOVER_SECONDS = 30 * 60
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_SECOND = timedelta(seconds=1)


def _unix_seconds(value: int | datetime) -> int:
    if isinstance(value, bool):
        raise TypeError("timestamp must be an integer or timezone-aware datetime")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("timestamp cannot be negative")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        seconds = (value - _EPOCH) // _ONE_SECOND
        if seconds < 0:
            raise ValueError("timestamp cannot be negative")
        return seconds
    raise TypeError("timestamp must be an integer or timezone-aware datetime")


def utc_day_number(value: int | datetime) -> int:
    """Return the UTC calendar day number ``unix_seconds // 86400``."""

    return _unix_seconds(value) // SECONDS_PER_DAY


def planning_day(value: int | datetime) -> int:
    """Return the effective UTC day with M07's 30-minute midnight cut-over."""

    return (_unix_seconds(value) + MIDNIGHT_CUTOVER_SECONDS) // SECONDS_PER_DAY
