"""Subscriptions and customer invoicing outside customer treasuries (ADM-L03)

Revision ID: 20261016_0094
Revises: 20261016_0093
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0094"
down_revision: str | None = "20261016_0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def _uuid(name: str) -> sa.Column[postgresql.UUID]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        _uuid("id"),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("base_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("per_request_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_plans_currency"),
        sa.CheckConstraint(
            "base_fee_minor >= 0 AND per_request_fee_minor >= 0", name="ck_billing_plans_nonneg"
        ),
    )
    op.create_table(
        "billing_subscriptions",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("plan_id"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payment_method", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled')", name="ck_billing_subscriptions_status"
        ),
        sa.CheckConstraint(
            "payment_method IN ('card', 'bank_transfer')", name="ck_billing_subscriptions_method"
        ),
    )
    op.create_index(
        "uq_billing_subscriptions_active_org",
        "billing_subscriptions",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "billing_invoices",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("subscription_id"),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("provider_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["billing_subscriptions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("org_id", "period_month", name="uq_billing_invoices_org_month"),
        sa.CheckConstraint(
            "status IN ('open', 'paid', 'payment_failed', 'void')",
            name="ck_billing_invoices_status",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_invoices_currency"),
        sa.CheckConstraint("total_minor >= 0", name="ck_billing_invoices_total_nonneg"),
    )
    op.create_index("ix_billing_invoices_org_created", "billing_invoices", ["org_id", "created_at"])
    op.create_table(
        "billing_invoice_lines",
        _uuid("id"),
        _uuid("invoice_id"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["billing_invoices.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "quantity >= 0 AND unit_amount_minor >= 0"
            " AND amount_minor = quantity * unit_amount_minor",
            name="ck_billing_invoice_lines_amount",
        ),
    )


def downgrade() -> None:
    op.drop_table("billing_invoice_lines")
    op.drop_index("ix_billing_invoices_org_created", table_name="billing_invoices")
    op.drop_table("billing_invoices")
    op.drop_index("uq_billing_subscriptions_active_org", table_name="billing_subscriptions")
    op.drop_table("billing_subscriptions")
    op.drop_table("billing_plans")
