"""Pure date rules for recurring payment obligations."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from enum import StrEnum


class RecurrenceCadence(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"


def period_at(start: date, cadence: RecurrenceCadence, interval: int = 1, index: int = 0) -> date:
    """Return a zero-based occurrence date while preserving the original calendar-day anchor."""
    if interval < 1 or index < 0:
        raise ValueError("recurrence interval must be positive and index nonnegative")
    if cadence is RecurrenceCadence.WEEKLY:
        return start + timedelta(weeks=interval * index)
    months = {
        RecurrenceCadence.MONTHLY: interval * index,
        RecurrenceCadence.QUARTERLY: 3 * interval * index,
        RecurrenceCadence.YEARLY: 12 * interval * index,
    }.get(cadence)
    if months is None:
        raise ValueError("unsupported recurrence cadence")
    month_index = start.year * 12 + start.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def next_period(period: date, cadence: RecurrenceCadence, interval: int = 1) -> date:
    """Advance one occurrence (use `period_at` with the original start for anchored series)."""
    return period_at(period, cadence, interval, 1)


def period_invoice_number(template: str, period: date) -> str:
    """Render the required `{period}` token as an ISO date, without format-string evaluation."""
    if template.count("{period}") != 1:
        raise ValueError("invoice number template must contain exactly one {period} token")
    rendered = template.replace("{period}", period.isoformat())
    if len(rendered) > 200 or "{" in rendered or "}" in rendered:
        raise ValueError("invoice number template contains unsupported placeholders")
    return rendered
