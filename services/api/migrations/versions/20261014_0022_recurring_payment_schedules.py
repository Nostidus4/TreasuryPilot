"""Add recurring payment schedule templates and period history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0022"
down_revision: str | None = "20261014_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_payment_requests_source", "payment_requests", type_="check")
    op.create_check_constraint(
        "ck_payment_requests_source",
        "payment_requests",
        "source IN ('MANUAL', 'UPLOAD', 'CSV', 'RECURRING')",
    )
    op.create_table(
        "recurring_payment_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paying_wallet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_no_template", sa.String(length=180), nullable=False),
        sa.Column("amount", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("cost_center", sa.String(length=120), nullable=True),
        sa.Column("cadence", sa.String(length=12), nullable=False),
        sa.Column("interval", sa.Integer(), server_default="1", nullable=False),
        sa.Column("period_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("next_period", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("due_days_after_issue", sa.Integer(), server_default="30", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Active", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_edited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(invoice_no_template)) > 0", name="ck_recurring_invoice_template"),
        sa.CheckConstraint("amount > 0", name="ck_recurring_amount_positive"),
        sa.CheckConstraint("interval > 0", name="ck_recurring_interval_positive"),
        sa.CheckConstraint("period_index >= 0", name="ck_recurring_period_index"),
        sa.CheckConstraint("due_days_after_issue BETWEEN 0 AND 365", name="ck_recurring_due_offset"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_recurring_end_date"),
        sa.CheckConstraint("version > 0", name="ck_recurring_version"),
        sa.CheckConstraint("cadence IN ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY')", name="ck_recurring_cadence"),
        sa.CheckConstraint("status IN ('Active', 'Paused', 'Completed')", name="ck_recurring_status"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["treasury_id", "org_id"], ["treasuries.id", "treasuries.org_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["treasury_id", "chain_id"], ["treasuries.id", "treasuries.chain_id"], name="fk_recurring_schedule_treasury_chain", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vendor_id", "org_id"], ["vendors.id", "vendors.org_id"], name="fk_recurring_schedule_vendor_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payee_id", "treasury_id", "vendor_id"], ["payees.id", "payees.treasury_id", "payees.vendor_id"], name="fk_recurring_schedule_payee_vendor", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id", "chain_id"], ["assets.id", "assets.chain_id"], name="fk_recurring_schedule_asset_chain", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paying_wallet_id", "treasury_id"], ["treasury_wallets.id", "treasury_wallets.treasury_id"], name="fk_recurring_schedule_wallet_treasury", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_edited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_schedules_due", "recurring_payment_schedules", ["status", "next_period"])
    op.create_table(
        "recurring_payment_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("skipped_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('Generated', 'Skipped')", name="ck_recurring_period_status"),
        sa.CheckConstraint(
            "(status = 'Generated' AND request_id IS NOT NULL AND skipped_by IS NULL AND skipped_at IS NULL) OR "
            "(status = 'Skipped' AND request_id IS NULL AND skipped_by IS NOT NULL AND skipped_at IS NOT NULL)",
            name="ck_recurring_period_outcome",
        ),
        sa.ForeignKeyConstraint(["schedule_id"], ["recurring_payment_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["skipped_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "period_date", name="uq_recurring_period_schedule_date"),
        sa.UniqueConstraint("request_id", name="uq_recurring_period_request"),
    )


def downgrade() -> None:
    op.drop_table("recurring_payment_periods")
    op.drop_index("ix_recurring_schedules_due", table_name="recurring_payment_schedules")
    op.drop_table("recurring_payment_schedules")
    op.drop_constraint("ck_payment_requests_source", "payment_requests", type_="check")
    op.create_check_constraint(
        "ck_payment_requests_source",
        "payment_requests",
        "source IN ('MANUAL', 'UPLOAD', 'CSV')",
    )
