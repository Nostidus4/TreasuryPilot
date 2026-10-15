"""Usage metering (ADM-L02): paid requests and paid volume per org per UTC month."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.admin.models import UsageMonthly
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus, RequestStatusEvent

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def parse_month(value: str) -> date:
    if not _MONTH.fullmatch(value):
        raise ValueError("month must be YYYY-MM")
    return date(int(value[:4]), int(value[5:]), 1)


async def recompute_month(session: AsyncSession, month: date) -> list[UsageMonthly]:
    """Rebuild the month from events inside the caller's transaction; safe to repeat.

    A request counts once, in the UTC month of its first Paid event, at its approved amount.
    """
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    end = datetime(month.year + month.month // 12, month.month % 12 + 1, 1, tzinfo=UTC)
    first_paid = (
        select(RequestStatusEvent.request_id, func.min(RequestStatusEvent.at).label("at"))
        .where(RequestStatusEvent.to_status == RequestStatus.PAID)
        .group_by(RequestStatusEvent.request_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                PaymentRequest.org_id,
                func.count(PaymentRequest.id),
                func.coalesce(func.sum(PaymentRequest.amount), 0),
            )
            .join(first_paid, first_paid.c.request_id == PaymentRequest.id)
            .where(first_paid.c.at >= start, first_paid.c.at < end)
            .group_by(PaymentRequest.org_id)
            .order_by(PaymentRequest.org_id)
        )
    ).all()
    await session.execute(delete(UsageMonthly).where(UsageMonthly.month == month))
    usage = [
        UsageMonthly(org_id=org, month=month, paid_count=count, paid_volume=int(volume or 0))
        for org, count, volume in rows
    ]
    session.add_all(usage)
    await session.flush()
    return usage
