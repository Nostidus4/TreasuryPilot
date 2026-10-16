"""Subscriptions and customer invoicing (ADM-L03, FR-926, BR-091).

Hard boundary: platform fees are invoiced in fiat and collected through a payment provider
(card or bank transfer). This module must never import treasury, chain, execution or signer
code, and no code path may debit a customer treasury; a test enforces the import boundary.
All amounts are integer minor units of the plan's fiat currency.
"""

from __future__ import annotations

import hashlib
import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.admin.billing_models import (
    BillingInvoice,
    BillingInvoiceLine,
    BillingPlan,
    BillingSubscription,
)
from treasurypilot_api.admin.models import UsageMonthly
from treasurypilot_api.admin.usage import recompute_month

PaymentMethod = Literal["card", "bank_transfer"]
PAYMENT_TERMS_DAYS = 14


class BillingError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    org_id: uuid.UUID
    invoice_id: uuid.UUID
    amount_minor: int
    currency: str
    payment_method: PaymentMethod
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CollectionResult:
    succeeded: bool
    provider_ref: str
    failure_code: str | None = None


class PaymentProvider(Protocol):
    """Adapter for a fiat payment processor. Implementations must honor the idempotency key."""

    name: str

    async def collect(self, request: CollectionRequest) -> CollectionResult: ...


class FakePaymentProvider:
    """Deterministic in-memory provider for local runs and tests; makes no network calls."""

    name = "fake"

    def __init__(self, *, decline_orgs: frozenset[uuid.UUID] = frozenset()) -> None:
        self.decline_orgs = decline_orgs
        self.calls: list[CollectionRequest] = []

    async def collect(self, request: CollectionRequest) -> CollectionResult:
        self.calls.append(request)
        digest = hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:16]
        ref = f"fake_{digest}"
        if request.org_id in self.decline_orgs:
            return CollectionResult(False, ref, "card_declined")
        return CollectionResult(True, ref)


def month_bounds(month: date) -> tuple[datetime, datetime]:
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    return start, start + timedelta(days=monthrange(month.year, month.month)[1])


async def create_plan(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    currency: str,
    base_fee_minor: int,
    per_request_fee_minor: int,
) -> BillingPlan:
    if await session.scalar(select(BillingPlan.id).where(BillingPlan.code == code)) is not None:
        raise BillingError("PLAN_EXISTS", "A plan with this code already exists")
    plan = BillingPlan(
        id=uuid.uuid4(),
        code=code,
        name=name,
        currency=currency,
        base_fee_minor=base_fee_minor,
        per_request_fee_minor=per_request_fee_minor,
    )
    session.add(plan)
    await session.flush()
    return plan


async def subscribe(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    plan_id: uuid.UUID,
    payment_method: PaymentMethod,
    now: datetime,
) -> BillingSubscription:
    """Start a subscription, replacing the org's active one (at most one is active)."""
    if await session.get(BillingPlan, plan_id) is None:
        raise BillingError("PLAN_NOT_FOUND", "Plan not found")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"billing_subscription:{org_id}"},
    )
    current = await session.scalar(
        select(BillingSubscription)
        .where(BillingSubscription.org_id == org_id, BillingSubscription.status == "active")
        .with_for_update()
    )
    if current is not None:
        current.status = "cancelled"
        current.cancelled_at = now
        await session.flush()
    subscription = BillingSubscription(
        id=uuid.uuid4(),
        org_id=org_id,
        plan_id=plan_id,
        status="active",
        payment_method=payment_method,
        started_at=now,
    )
    session.add(subscription)
    await session.flush()
    return subscription


def price_lines(plan: BillingPlan, paid_count: int, month: date) -> list[tuple[str, str, int, int]]:
    """(kind, description, quantity, unit_amount_minor) lines. Pure integer arithmetic."""
    label = f"{month:%Y-%m}"
    lines = [("base", f"{plan.name} base fee {label}", 1, plan.base_fee_minor)]
    if paid_count > 0 and plan.per_request_fee_minor > 0:
        lines.append(
            ("paid_requests", f"Paid requests {label}", paid_count, plan.per_request_fee_minor)
        )
    return lines


async def generate_invoices(
    session: AsyncSession, month: date, *, now: datetime
) -> list[BillingInvoice]:
    """Create the month's invoice for each active subscription; safe to repeat.

    Only completed UTC months are billed. Usage is recomputed from the event store first so the
    invoice always matches it. An org that already has an invoice for the month is skipped, so
    an issued invoice is never altered. Returns the newly created invoices.
    """
    month_start, month_end = month_bounds(month)
    if month_end > now:
        raise BillingError("MONTH_NOT_CLOSED", "Only completed UTC months can be invoiced")
    await recompute_month(session, month)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"billing_invoices:{month:%Y-%m}"},
    )
    existing = set(
        await session.scalars(
            select(BillingInvoice.org_id).where(BillingInvoice.period_month == month)
        )
    )
    subscriptions = (
        await session.execute(
            select(BillingSubscription, BillingPlan)
            .join(BillingPlan, BillingPlan.id == BillingSubscription.plan_id)
            .where(
                BillingSubscription.status == "active",
                BillingSubscription.started_at < month_end,
            )
            .order_by(BillingSubscription.org_id)
        )
    ).all()
    created: list[BillingInvoice] = []
    for subscription, plan in subscriptions:
        if subscription.org_id in existing:
            continue
        paid_count = int(
            await session.scalar(
                select(func.coalesce(func.sum(UsageMonthly.paid_count), 0)).where(
                    UsageMonthly.org_id == subscription.org_id, UsageMonthly.month == month
                )
            )
            or 0
        )
        lines = price_lines(plan, paid_count, month)
        total = sum(quantity * unit for _, _, quantity, unit in lines)
        invoice = BillingInvoice(
            id=uuid.uuid4(),
            org_id=subscription.org_id,
            subscription_id=subscription.id,
            period_month=month,
            currency=plan.currency,
            total_minor=total,
            status="paid" if total == 0 else "open",
            created_at=now,
            due_at=now + timedelta(days=PAYMENT_TERMS_DAYS),
            paid_at=now if total == 0 else None,
        )
        session.add(invoice)
        await session.flush()
        session.add_all(
            BillingInvoiceLine(
                id=uuid.uuid4(),
                invoice_id=invoice.id,
                kind=kind,
                description=description,
                quantity=quantity,
                unit_amount_minor=unit,
                amount_minor=quantity * unit,
            )
            for kind, description, quantity, unit in lines
        )
        created.append(invoice)
    await session.flush()
    return created


async def collect_invoice(
    session: AsyncSession,
    provider: PaymentProvider,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
    now: datetime,
) -> BillingInvoice:
    """Charge the invoice through the provider (card / bank transfer) and record the outcome.

    The invoice row stays locked for the call, so concurrent requests cannot double-charge, and
    the provider also receives a stable idempotency key. A paid invoice is returned unchanged.
    """
    invoice = await session.scalar(
        select(BillingInvoice)
        .where(BillingInvoice.id == invoice_id, BillingInvoice.org_id == org_id)
        .with_for_update()
    )
    if invoice is None:
        raise BillingError("INVOICE_NOT_FOUND", "Invoice not found")
    if invoice.status == "paid":
        return invoice
    if invoice.status == "void":
        raise BillingError("INVOICE_VOID", "A void invoice cannot be collected")
    subscription = await session.get(BillingSubscription, invoice.subscription_id)
    assert subscription is not None  # FK RESTRICT
    result = await provider.collect(
        CollectionRequest(
            org_id=org_id,
            invoice_id=invoice.id,
            amount_minor=invoice.total_minor,
            currency=invoice.currency,
            payment_method="bank_transfer"
            if subscription.payment_method == "bank_transfer"
            else "card",
            idempotency_key=f"billing-invoice:{invoice.id}",
        )
    )
    invoice.provider = provider.name
    invoice.provider_ref = result.provider_ref
    if result.succeeded:
        invoice.status, invoice.paid_at = "paid", now
    else:
        invoice.status = "payment_failed"
    await session.flush()
    return invoice
