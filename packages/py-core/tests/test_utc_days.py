from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from treasurypilot_core.domain import planning_day, utc_day_number


def test_utc_day_number_uses_calendar_day_not_rolling_window() -> None:
    assert utc_day_number(0) == 0
    assert utc_day_number(86_399) == 0
    assert utc_day_number(86_400) == 1


def test_utc_day_number_normalizes_an_aware_datetime_to_utc() -> None:
    vietnam = timezone(timedelta(hours=7))
    instant = datetime(1970, 1, 2, 6, 0, tzinfo=vietnam)

    assert utc_day_number(instant) == 0


def test_planning_day_cuts_over_exactly_thirty_minutes_before_midnight() -> None:
    day = 20_000
    start = day * 86_400

    assert planning_day(start + 23 * 3_600 + 29 * 60 + 59) == day
    assert planning_day(start + 23 * 3_600 + 30 * 60) == day + 1
    assert planning_day(start + 86_399) == day + 1


def test_planning_day_accepts_utc_datetime() -> None:
    before_cutover = datetime(2026, 10, 11, 23, 29, 59, tzinfo=UTC)
    at_cutover = datetime(2026, 10, 11, 23, 30, tzinfo=UTC)

    assert planning_day(at_cutover) == utc_day_number(before_cutover) + 1


def test_day_helpers_reject_naive_datetimes_and_negative_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_day_number(datetime(2026, 10, 11))
    with pytest.raises(ValueError, match="negative"):
        utc_day_number(-1)


def test_fractional_pre_epoch_datetime_is_rejected_not_truncated_to_day_zero() -> None:
    half_second_before_epoch = datetime(1970, 1, 1, tzinfo=UTC) - timedelta(milliseconds=500)

    with pytest.raises(ValueError, match="negative"):
        utc_day_number(half_second_before_epoch)
