from datetime import date

import pytest

from treasurypilot_core.recurrence import (
    RecurrenceCadence,
    next_period,
    period_at,
    period_invoice_number,
)


def test_monthly_occurrences_keep_the_original_day_after_a_short_month() -> None:
    start = date(2026, 1, 31)
    assert period_at(start, RecurrenceCadence.MONTHLY, index=0) == date(2026, 1, 31)
    assert period_at(start, RecurrenceCadence.MONTHLY, index=1) == date(2026, 2, 28)
    assert period_at(start, RecurrenceCadence.MONTHLY, index=2) == date(2026, 3, 31)


def test_weekly_and_interval_cadences_advance_from_the_anchor() -> None:
    start = date(2026, 1, 1)
    assert period_at(start, RecurrenceCadence.WEEKLY, interval=2, index=3) == date(2026, 2, 12)
    assert period_at(start, RecurrenceCadence.QUARTERLY, index=2) == date(2026, 7, 1)
    assert next_period(start, RecurrenceCadence.YEARLY) == date(2027, 1, 1)


def test_invoice_number_uses_only_the_period_token() -> None:
    assert period_invoice_number("RENT-{period}", date(2026, 10, 14)) == "RENT-2026-10-14"
    with pytest.raises(ValueError, match="exactly one"):
        period_invoice_number("RENT-2026", date(2026, 10, 14))
    with pytest.raises(ValueError, match="unsupported placeholders"):
        period_invoice_number("RENT-{period}-{vendor}", date(2026, 10, 14))
