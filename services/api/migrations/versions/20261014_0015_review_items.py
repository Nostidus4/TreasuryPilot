"""Create the organization-scoped recovery review queue.

Revision ID: 20261014_0015
Revises: 20261014_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0015"
down_revision: str | None = "20261014_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "treasury_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("treasuries.id"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_requests.id"),
            nullable=False,
        ),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True)),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("primary_code", sa.String(100), nullable=False),
        sa.Column("reason_codes", postgresql.ARRAY(sa.String(100)), nullable=False),
        sa.Column("completed_steps", postgresql.JSONB(), nullable=False),
        sa.Column("assigned_roles", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="Open"),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "resolved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.String(32)),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("version > 0", name="ck_review_items_version"),
        sa.CheckConstraint(
            "type IN ("
            "'POLICY_BLOCK', 'NEEDS_AUTHORITY', 'FEE_APPROVAL', 'UNCERTAIN_TX', "
            "'DISCREPANCY', 'AI_REJECTED', 'INFRA', 'UNEXPECTED_OUTFLOW')",
            name="ck_review_items_type",
        ),
        sa.CheckConstraint(
            "status IN ('Open', 'Resolved', 'Dismissed')", name="ck_review_items_status"
        ),
    )
    op.create_index(
        "uq_review_items_open_request_type",
        "review_items",
        ["request_id", "type"],
        unique=True,
        postgresql_where=sa.text("status = 'Open'"),
    )
    op.create_index(
        "ix_review_items_org_status_due",
        "review_items",
        ["org_id", "status", "sla_due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_items_org_status_due", table_name="review_items")
    op.drop_index("uq_review_items_open_request_type", table_name="review_items")
    op.drop_table("review_items")
