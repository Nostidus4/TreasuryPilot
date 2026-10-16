"""Operator-managed recurring templates and their payment request drafts."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import (
    RecurringPaymentPeriod,
    RecurringPaymentSchedule,
)
from treasurypilot_api.invoices.requests import (
    _amount,
    _bound_fields,
    _validate_dates,
)
from treasurypilot_api.treasury.models import Asset
from treasurypilot_core.recurrence import RecurrenceCadence, period_at, period_invoice_number

router = APIRouter(
    prefix="/v1/orgs/{organization_id}/recurring-payment-schedules",
    tags=["recurring payment schedules"],
)
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)


class RecurringScheduleCreate(ApiModel):
    treasury_id: uuid.UUID
    vendor_id: uuid.UUID
    payee_id: uuid.UUID
    asset_id: uuid.UUID
    paying_wallet_id: uuid.UUID | None = None
    invoice_no_template: str = Field(min_length=8, max_length=180)
    amount: str = Field(min_length=1, max_length=80)
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)
    cadence: RecurrenceCadence
    interval: int = Field(default=1, ge=1, le=120)
    start_date: date
    end_date: date | None = None
    due_days_after_issue: int = Field(default=30, ge=0, le=365)

    @model_validator(mode="after")
    def validate_template(self) -> RecurringScheduleCreate:
        period_invoice_number(self.invoice_no_template, self.start_date)
        if self.start_date < datetime.now(UTC).date():
            raise ValueError("startDate must be today or later")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("endDate must be on or after startDate")
        _validate_dates(
            self.start_date, self.start_date + timedelta(days=self.due_days_after_issue)
        )
        return self


class RecurringSchedulePatch(ApiModel):
    payee_id: uuid.UUID | None = None
    paying_wallet_id: uuid.UUID | None = None
    invoice_no_template: str | None = Field(default=None, min_length=8, max_length=180)
    amount: str | None = Field(default=None, min_length=1, max_length=80)
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)
    end_date: date | None = None
    status: str | None = Field(default=None, pattern="^(Active|Paused)$")

    @model_validator(mode="after")
    def reject_required_nulls(self) -> RecurringSchedulePatch:
        nullable = {"paying_wallet_id", "terms", "note", "cost_center", "end_date"}
        for name in self.model_fields_set - nullable:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.invoice_no_template is not None:
            period_invoice_number(self.invoice_no_template, date(2000, 1, 1))
        return self


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "request_sessions", None)
    if factory is None:
        raise AuthFailure(
            status=503,
            code="RECURRING_SCHEDULES_UNAVAILABLE",
            title="Recurring schedules unavailable",
            detail="Request storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], factory)


def _view(row: RecurringPaymentSchedule) -> dict[str, object]:
    return {
        "id": str(row.id),
        "orgId": str(row.org_id),
        "treasuryId": str(row.treasury_id),
        "vendorId": str(row.vendor_id),
        "payeeId": str(row.payee_id),
        "assetId": str(row.asset_id),
        "payingWalletId": str(row.paying_wallet_id) if row.paying_wallet_id else None,
        "invoiceNoTemplate": row.invoice_no_template,
        "amount": str(int(row.amount)),
        "terms": row.terms,
        "note": row.note,
        "tags": row.tags,
        "costCenter": row.cost_center,
        "cadence": row.cadence,
        "interval": row.interval,
        "startDate": row.start_date.isoformat(),
        "nextPeriod": row.next_period.isoformat(),
        "endDate": row.end_date.isoformat() if row.end_date else None,
        "dueDaysAfterIssue": row.due_days_after_issue,
        "status": row.status,
        "pauseReason": row.pause_reason,
        "createdBy": str(row.created_by) if row.created_by else None,
        "lastEditedBy": str(row.last_edited_by) if row.last_edited_by else None,
        "version": row.version,
    }


def _resume(row: RecurringPaymentSchedule, today: date) -> None:
    """Resume from today: do not backfill drafts for the periods missed while paused."""
    cadence = RecurrenceCadence(row.cadence)
    while row.next_period < today:
        row.period_index += 1
        row.next_period = period_at(row.start_date, cadence, row.interval, row.period_index)
    if row.end_date is not None and row.next_period > row.end_date:
        row.status = "Completed"
    row.pause_reason = None


@router.post("", status_code=201, openapi_extra={"x-organization-scoped": True})
async def create_schedule(
    organization_id: uuid.UUID,
    payload: RecurringScheduleCreate,
    request: Request,
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    factory = _sessions(request)
    async with factory() as session, session.begin():
        treasury, _vendor, _payee, asset = await _bound_fields(
            session,
            organization_id=member.organization_id,
            treasury_id=payload.treasury_id,
            vendor_id=payload.vendor_id,
            payee_id=payload.payee_id,
            asset_id=payload.asset_id,
            paying_wallet_id=payload.paying_wallet_id,
        )
        amount = _amount(payload.amount, asset.decimals)
        row = RecurringPaymentSchedule(
            id=uuid7(),
            org_id=member.organization_id,
            treasury_id=treasury.id,
            chain_id=treasury.chain_id,
            vendor_id=payload.vendor_id,
            payee_id=payload.payee_id,
            asset_id=asset.id,
            paying_wallet_id=payload.paying_wallet_id,
            invoice_no_template=payload.invoice_no_template,
            amount=amount,
            terms=payload.terms,
            note=payload.note,
            tags=payload.tags,
            cost_center=payload.cost_center,
            cadence=payload.cadence.value,
            interval=payload.interval,
            period_index=0,
            start_date=payload.start_date,
            next_period=payload.start_date,
            end_date=payload.end_date,
            due_days_after_issue=payload.due_days_after_issue,
            status="Active",
            created_by=member.user_id,
            last_edited_by=member.user_id,
        )
        session.add(row)
        await session.flush()
    return {"schedule": _view(row)}


@router.get("", openapi_extra={"x-organization-scoped": True})
async def list_schedules(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    factory = _sessions(request)
    async with factory() as session:
        rows = await session.scalars(
            select(RecurringPaymentSchedule)
            .where(RecurringPaymentSchedule.org_id == member.organization_id)
            .order_by(RecurringPaymentSchedule.created_at.desc(), RecurringPaymentSchedule.id)
        )
        return {"schedules": [_view(row) for row in rows]}


@router.patch("/{schedule_id}", openapi_extra={"x-organization-scoped": True})
async def edit_schedule(
    organization_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: RecurringSchedulePatch,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    if if_match is None:
        raise AuthFailure(
            status=428,
            code="PRECONDITION_REQUIRED",
            title="If-Match required",
            detail="Provide the current schedule version.",
        )
    factory = _sessions(request)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(RecurringPaymentSchedule)
            .where(
                RecurringPaymentSchedule.id == schedule_id,
                RecurringPaymentSchedule.org_id == member.organization_id,
            )
            .with_for_update()
        )
        if row is None:
            raise AuthFailure(
                status=404,
                code="SCHEDULE_NOT_FOUND",
                title="Schedule not found",
                detail="The recurring schedule is not available to this user.",
            )
        if if_match != f'"{row.version}"':
            raise AuthFailure(
                status=412,
                code="VERSION_CONFLICT",
                title="Version conflict",
                detail="The schedule changed. Reload it and try again.",
            )
        if row.status == "Completed":
            raise AuthFailure(
                status=409,
                code="SCHEDULE_COMPLETED",
                title="Schedule completed",
                detail="Completed schedules cannot be changed.",
            )
        was_paused = row.status == "Paused"
        fields = payload.model_dump(exclude_unset=True)
        if "payee_id" in fields:
            row.payee_id = fields["payee_id"]
        if "paying_wallet_id" in fields:
            row.paying_wallet_id = fields["paying_wallet_id"]
        if "invoice_no_template" in fields:
            period_invoice_number(fields["invoice_no_template"], row.next_period)
            row.invoice_no_template = fields["invoice_no_template"]
        if "amount" in fields:
            asset = await session.scalar(
                select(Asset).where(Asset.id == row.asset_id, Asset.chain_id == row.chain_id)
            )
            if asset is None:
                raise AuthFailure(
                    status=422,
                    code="ASSET_NOT_PAYMENT_STABLECOIN",
                    title="Payment asset invalid",
                    detail="The treasury payment asset is unavailable.",
                )
            row.amount = _amount(fields["amount"], asset.decimals)
        for field in ("terms", "note", "tags", "cost_center", "end_date", "status"):
            if field in fields:
                setattr(row, field, fields[field])
        if row.end_date is not None and row.end_date < row.next_period:
            raise AuthFailure(
                status=422,
                code="DATE_INVALID",
                title="Dates invalid",
                detail="The end date cannot be before the next period.",
            )
        if was_paused and row.status == "Active":
            _resume(row, datetime.now(UTC).date())
        await _bound_fields(
            session,
            organization_id=member.organization_id,
            treasury_id=row.treasury_id,
            vendor_id=row.vendor_id,
            payee_id=row.payee_id,
            asset_id=row.asset_id,
            paying_wallet_id=row.paying_wallet_id,
        )
        row.version += 1
        row.last_edited_by = member.user_id
        await session.flush()
    return {"schedule": _view(row)}


@router.post(
    "/{schedule_id}/periods/{period_date}/skip",
    status_code=201,
    openapi_extra={"x-organization-scoped": True},
)
async def skip_period(
    organization_id: uuid.UUID,
    schedule_id: uuid.UUID,
    period_date: date,
    request: Request,
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    factory = _sessions(request)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(RecurringPaymentSchedule)
            .where(
                RecurringPaymentSchedule.id == schedule_id,
                RecurringPaymentSchedule.org_id == member.organization_id,
            )
            .with_for_update()
        )
        if row is None:
            raise AuthFailure(
                status=404,
                code="SCHEDULE_NOT_FOUND",
                title="Schedule not found",
                detail="The recurring schedule is not available to this user.",
            )
        if row.status != "Active" or row.next_period != period_date:
            raise AuthFailure(
                status=409,
                code="PERIOD_NOT_CURRENT",
                title="Period cannot be skipped",
                detail="Only the next active period can be skipped.",
            )
        if row.end_date is not None and period_date > row.end_date:
            raise AuthFailure(
                status=409,
                code="SCHEDULE_COMPLETED",
                title="Schedule completed",
                detail="This schedule has no period on or before its end date.",
            )
        recorded = await session.scalar(
            select(RecurringPaymentPeriod.id).where(
                RecurringPaymentPeriod.schedule_id == row.id,
                RecurringPaymentPeriod.period_date == period_date,
            )
        )
        if recorded is not None:
            raise AuthFailure(
                status=409,
                code="PERIOD_NOT_CURRENT",
                title="Period cannot be skipped",
                detail="This period already has a recorded outcome.",
            )
        period = RecurringPaymentPeriod(
            id=uuid7(),
            schedule_id=row.id,
            period_date=period_date,
            request_id=None,
            status="Skipped",
            skipped_by=member.user_id,
            skipped_at=datetime.now(UTC),
        )
        session.add(period)
        row.period_index += 1
        row.next_period = period_at(
            row.start_date, RecurrenceCadence(row.cadence), row.interval, row.period_index
        )
        if row.end_date is not None and row.next_period > row.end_date:
            row.status = "Completed"
        row.version += 1
        await session.flush()
    return {
        "period": {"date": period_date.isoformat(), "status": "Skipped"},
        "schedule": _view(row),
    }
