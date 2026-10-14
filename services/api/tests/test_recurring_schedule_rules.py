from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from treasurypilot_api.invoices.recurring import (
    RecurringScheduleCreate,
    RecurringSchedulePatch,
    _resume,
)


def test_recurring_schedule_requires_a_period_invoice_token() -> None:
    values = {
        "treasuryId": uuid.uuid4(),
        "vendorId": uuid.uuid4(),
        "payeeId": uuid.uuid4(),
        "assetId": uuid.uuid4(),
        "invoiceNoTemplate": "RENT-{period}",
        "amount": "123.45",
        "cadence": "MONTHLY",
        "startDate": "2099-01-31",
    }
    schedule = RecurringScheduleCreate.model_validate(values)
    assert schedule.start_date == date(2099, 1, 31)
    assert schedule.interval == 1
    assert schedule.due_days_after_issue == 30

    with pytest.raises(ValidationError, match="exactly one"):
        RecurringScheduleCreate.model_validate(
            {**values, "invoiceNoTemplate": "RENT-{period}-{period}"}
        )
    with pytest.raises(ValidationError, match="endDate"):
        RecurringScheduleCreate.model_validate({**values, "endDate": "2099-01-30"})


def test_schedule_patch_rejects_required_nulls_and_invalid_template_tokens() -> None:
    with pytest.raises(ValidationError, match="payee_id cannot be null"):
        RecurringSchedulePatch.model_validate({"payeeId": None})
    with pytest.raises(ValidationError, match="unsupported placeholders"):
        RecurringSchedulePatch.model_validate({"invoiceNoTemplate": "RENT-{period}-{extra}"})
    assert RecurringSchedulePatch.model_validate({"terms": None, "note": None}).note is None


def test_recurring_schedule_rejects_a_start_date_in_the_past() -> None:
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    values = {
        "treasuryId": uuid.uuid4(),
        "vendorId": uuid.uuid4(),
        "payeeId": uuid.uuid4(),
        "assetId": uuid.uuid4(),
        "invoiceNoTemplate": "RENT-{period}",
        "amount": "1",
        "cadence": "MONTHLY",
        "startDate": yesterday.isoformat(),
    }
    with pytest.raises(ValidationError, match="today or later"):
        RecurringScheduleCreate.model_validate(values)
    values["startDate"] = datetime.now(UTC).date().isoformat()
    RecurringScheduleCreate.model_validate(values)


def _paused(next_period: date, index: int, end_date: date | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        cadence="MONTHLY",
        interval=1,
        start_date=date(2026, 1, 15),
        period_index=index,
        next_period=next_period,
        end_date=end_date,
        status="Active",
        pause_reason="boom",
    )


def test_resume_moves_next_period_to_first_period_on_or_after_today() -> None:
    row = _paused(date(2026, 3, 15), 2)
    _resume(row, date(2026, 10, 14))  # type: ignore[arg-type]
    assert (row.next_period, row.period_index, row.status) == (date(2026, 10, 15), 9, "Active")
    assert row.pause_reason is None

    due_today = _paused(date(2026, 10, 15), 9)
    _resume(due_today, date(2026, 10, 15))  # type: ignore[arg-type]
    assert due_today.next_period == date(2026, 10, 15)


def test_resume_completes_a_schedule_whose_remaining_periods_have_passed() -> None:
    row = _paused(date(2026, 3, 15), 2, end_date=date(2026, 6, 1))
    _resume(row, date(2026, 10, 14))  # type: ignore[arg-type]
    assert row.status == "Completed"
