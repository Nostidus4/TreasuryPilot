"""create plans (M10 §4)

Revision ID: 20261015_0064
Revises: 20261015_0063
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0064"
down_revision: str | None = "20261015_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "Draft",
    "Blocked",
    "AwaitingAuthority",
    "AwaitingFeeAcceptance",
    "Attested",
    "Executing",
    "Completed",
    "PartiallyCompleted",
    "Superseded",
    "Expired",
)
_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("planner_source", sa.String(length=16), nullable=True),
        sa.Column("plan_hash", postgresql.BYTEA(), nullable=True),
        sa.Column("chosen_reason", sa.Text(), nullable=True),
        sa.Column(
            "ai_call_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), server_default="Draft", nullable=False),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fee_estimate_wei", sa.Numeric(78, 0), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")", name="ck_plans_status"
        ),
        sa.CheckConstraint(
            "planner_source IS NULL OR planner_source IN ('AI', 'DETERMINISTIC', 'RULE_BASED')",
            name="ck_plans_planner_source",
        ),
        sa.CheckConstraint(
            "fee_estimate_wei IS NULL OR fee_estimate_wei >= 0", name="ck_plans_fee"
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_plans_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # One active plan per request: also the idempotent claim of the plan starter.
    op.create_index(
        "uq_plans_open_request",
        "plans",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({_OPEN})"),
    )
    op.create_index("ix_plans_treasury_status", "plans", ["treasury_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_plans_treasury_status", table_name="plans")
    op.drop_index("uq_plans_open_request", table_name="plans")
    op.drop_table("plans")
