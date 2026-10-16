"""Subscription billing tables (ADM-L03). Fees are integer minor units of a fiat currency."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class BillingPlan(Base):
    """A platform price list entry (BR-091: charged outside customer treasuries)."""

    __tablename__ = "billing_plans"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_plans_currency"),
        CheckConstraint(
            "base_fee_minor >= 0 AND per_request_fee_minor >= 0", name="ck_billing_plans_nonneg"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    base_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    per_request_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BillingSubscription(Base):
    """An organization's plan. At most one active subscription per organization."""

    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'cancelled')", name="ck_billing_subscriptions_status"
        ),
        # Fiat rails only: card or bank transfer, never a customer treasury (BR-091).
        CheckConstraint(
            "payment_method IN ('card', 'bank_transfer')", name="ck_billing_subscriptions_method"
        ),
        Index(
            "uq_billing_subscriptions_active_org",
            "org_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, default="card")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingInvoice(Base):
    """A monthly platform invoice for one org, collected outside its treasuries."""

    __tablename__ = "billing_invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'paid', 'payment_failed', 'void')",
            name="ck_billing_invoices_status",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_invoices_currency"),
        CheckConstraint("total_minor >= 0", name="ck_billing_invoices_total_nonneg"),
        UniqueConstraint("org_id", "period_month", name="uq_billing_invoices_org_month"),
        Index("ix_billing_invoices_org_created", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_subscriptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)  # first day, UTC month
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_ref: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingInvoiceLine(Base):
    __tablename__ = "billing_invoice_lines"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0 AND unit_amount_minor >= 0"
            " AND amount_minor = quantity * unit_amount_minor",
            name="ck_billing_invoice_lines_amount",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_invoices.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
