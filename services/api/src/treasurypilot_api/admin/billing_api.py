"""Organization-scoped billing reads and invoice payment (ADM-L03)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.admin.billing import BillingError, PaymentProvider, collect_invoice
from treasurypilot_api.admin.billing_models import (
    BillingInvoice,
    BillingInvoiceLine,
    BillingPlan,
    BillingSubscription,
)
from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role


class PlanView(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    currency: str = Field(description="ISO 4217 code; fees are integer minor units of it.")
    base_fee_minor: int
    per_request_fee_minor: int


class SubscriptionView(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    plan: PlanView
    status: Literal["active", "cancelled"]
    payment_method: Literal["card", "bank_transfer"]
    started_at: AwareDatetime


class InvoiceLineView(ApiModel):
    kind: str
    description: str
    quantity: int
    unit_amount_minor: int
    amount_minor: int


class InvoiceView(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_month: str
    currency: str
    total_minor: int
    status: Literal["open", "paid", "payment_failed", "void"]
    created_at: AwareDatetime
    due_at: AwareDatetime
    paid_at: AwareDatetime | None
    lines: list[InvoiceLineView]


class BillingOverview(ApiModel):
    subscription: SubscriptionView | None


def plan_view(plan: BillingPlan) -> PlanView:
    return PlanView.model_validate(plan, from_attributes=True)


def subscription_view(subscription: BillingSubscription, plan: BillingPlan) -> SubscriptionView:
    return SubscriptionView(
        id=subscription.id,
        org_id=subscription.org_id,
        plan=plan_view(plan),
        status=subscription.status,  # type: ignore[arg-type]
        payment_method=subscription.payment_method,  # type: ignore[arg-type]
        started_at=subscription.started_at,
    )


def invoice_view(invoice: BillingInvoice, lines: list[BillingInvoiceLine]) -> InvoiceView:
    month: date = invoice.period_month
    return InvoiceView(
        id=invoice.id,
        org_id=invoice.org_id,
        period_month=month.strftime("%Y-%m"),
        currency=invoice.currency,
        total_minor=invoice.total_minor,
        status=invoice.status,  # type: ignore[arg-type]
        created_at=invoice.created_at,
        due_at=invoice.due_at,
        paid_at=invoice.paid_at,
        lines=[InvoiceLineView.model_validate(line, from_attributes=True) for line in lines],
    )


async def _lines(
    session: AsyncSession, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[BillingInvoiceLine]]:
    grouped: dict[uuid.UUID, list[BillingInvoiceLine]] = {i: [] for i in invoice_ids}
    rows = await session.scalars(
        select(BillingInvoiceLine)
        .where(BillingInvoiceLine.invoice_id.in_(invoice_ids))
        .order_by(BillingInvoiceLine.kind)
    )
    for row in rows:
        grouped[row.invoice_id].append(row)
    return grouped


def create_billing_router(
    sessions: async_sessionmaker[AsyncSession] | None,
    provider: PaymentProvider | None,
) -> APIRouter:
    """Tenant billing: reads for admins/owners/auditors, payment for admins/owners only."""

    router = APIRouter(prefix="/v1/orgs/{organization_id}/billing", tags=["billing"])
    reader = Depends(
        require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER, OrganizationRole.AUDITOR)
    )
    payer = Depends(require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER))

    def require_sessions() -> async_sessionmaker[AsyncSession]:
        if sessions is None:
            raise HTTPException(status_code=503, detail="Billing storage is unavailable")
        return sessions

    sessions_dependency = Depends(require_sessions)
    scoped = {"x-organization-scoped": True}

    @router.get("", response_model=BillingOverview, openapi_extra=scoped)
    async def overview(
        member: MemberAccess = reader,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> BillingOverview:
        async with db_sessions() as session:
            row = (
                await session.execute(
                    select(BillingSubscription, BillingPlan)
                    .join(BillingPlan, BillingPlan.id == BillingSubscription.plan_id)
                    .where(
                        BillingSubscription.org_id == member.organization_id,
                        BillingSubscription.status == "active",
                    )
                )
            ).first()
        return BillingOverview(
            subscription=subscription_view(row[0], row[1]) if row is not None else None
        )

    @router.get("/invoices", response_model=list[InvoiceView], openapi_extra=scoped)
    async def list_invoices(
        limit: int = Query(default=24, ge=1, le=100),  # noqa: B008
        member: MemberAccess = reader,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> list[InvoiceView]:
        async with db_sessions() as session:
            invoices = list(
                await session.scalars(
                    select(BillingInvoice)
                    .where(BillingInvoice.org_id == member.organization_id)
                    .order_by(BillingInvoice.period_month.desc(), BillingInvoice.id)
                    .limit(limit)
                )
            )
            lines = await _lines(session, [i.id for i in invoices])
        return [invoice_view(i, lines[i.id]) for i in invoices]

    @router.get("/invoices/{invoice_id}", response_model=InvoiceView, openapi_extra=scoped)
    async def get_invoice(
        invoice_id: uuid.UUID,
        member: MemberAccess = reader,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> InvoiceView:
        async with db_sessions() as session:
            invoice = await session.scalar(
                select(BillingInvoice).where(
                    BillingInvoice.id == invoice_id,
                    BillingInvoice.org_id == member.organization_id,
                )
            )
            if invoice is None:
                raise HTTPException(status_code=404, detail="Invoice not found")
            lines = await _lines(session, [invoice.id])
        return invoice_view(invoice, lines[invoice.id])

    @router.post("/invoices/{invoice_id}/pay", response_model=InvoiceView, openapi_extra=scoped)
    async def pay_invoice(
        invoice_id: uuid.UUID,
        member: MemberAccess = payer,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> InvoiceView:
        """Collect by card or bank transfer through the provider; never from a treasury."""
        if provider is None:
            raise HTTPException(status_code=503, detail="Payment collection is not configured")
        now = datetime.now(UTC)
        try:
            async with db_sessions() as session, session.begin():
                before = await session.scalar(
                    select(BillingInvoice.status).where(
                        BillingInvoice.id == invoice_id,
                        BillingInvoice.org_id == member.organization_id,
                    )
                )
                invoice = await collect_invoice(
                    session,
                    provider,
                    org_id=member.organization_id,
                    invoice_id=invoice_id,
                    now=now,
                )
                if before != "paid":
                    await write_audit(
                        session,
                        org_id=member.organization_id,
                        actor=AuditActor(AuditActorType.USER, member.user_id),
                        action="billing.invoice.collection_attempted",
                        entity=AuditEntity("billing_invoice", invoice.id),
                        data={
                            "status": invoice.status,
                            "total_minor": invoice.total_minor,
                            "currency": invoice.currency,
                            "provider": invoice.provider,
                        },
                    )
                lines = await _lines(session, [invoice.id])
        except BillingError as error:
            status = 404 if error.code == "INVOICE_NOT_FOUND" else 409
            raise HTTPException(status_code=status, detail=error.detail) from error
        return invoice_view(invoice, lines[invoice.id])

    return router
