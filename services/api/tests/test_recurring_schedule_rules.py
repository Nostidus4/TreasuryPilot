from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from treasurypilot_api.invoices.recurring import RecurringScheduleCreate, RecurringSchedulePatch


def test_recurring_schedule_requires_a_period_invoice_token() -> None:
    values = {
        "treasuryId": uuid.uuid4(),
        "vendorId": uuid.uuid4(),
        "payeeId": uuid.uuid4(),
        "assetId": uuid.uuid4(),
        "invoiceNoTemplate": "RENT-{period}",
        "amount": "123.45",
        "cadence": "MONTHLY",
        "startDate": "2026-01-31",
    }
    schedule = RecurringScheduleCreate.model_validate(values)
    assert schedule.start_date == date(2026, 1, 31)
    assert schedule.interval == 1
    assert schedule.due_days_after_issue == 30

    with pytest.raises(ValidationError, match="exactly one"):
        RecurringScheduleCreate.model_validate(
            {**values, "invoiceNoTemplate": "RENT-{period}-{period}"}
        )
    with pytest.raises(ValidationError, match="endDate"):
        RecurringScheduleCreate.model_validate({**values, "endDate": "2026-01-30"})


def test_schedule_patch_rejects_required_nulls_and_invalid_template_tokens() -> None:
    with pytest.raises(ValidationError, match="payee_id cannot be null"):
        RecurringSchedulePatch.model_validate({"payeeId": None})
    with pytest.raises(ValidationError, match="unsupported placeholders"):
        RecurringSchedulePatch.model_validate({"invoiceNoTemplate": "RENT-{period}-{extra}"})
    assert RecurringSchedulePatch.model_validate({"terms": None, "note": None}).note is None
