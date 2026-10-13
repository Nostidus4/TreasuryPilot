"""add routed review items

Revision ID: 20261013_0006
Revises: 20261013_0005
Create Date: 2026-10-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0006"
down_revision: str | None = "20261013_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "'POLICY_BLOCK', 'NEEDS_AUTHORITY', 'FEE_APPROVAL', 'UNCERTAIN_TX', 'DISCREPANCY', 'AI_REJECTED', 'INFRA', 'UNEXPECTED_OUTFLOW'"
_STATUSES = "'Open', 'Resolved', 'Dismissed'"
_ACTIONS = "'RETRY', 'REPLAN', 'CANCEL', 'EDIT_REQUEST', 'GRANT_EXCEPTION', 'ACCEPT_FEE', 'ACKNOWLEDGE', 'MARK_MATCHED'"


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("primary_code", sa.String(length=64), nullable=False),
        sa.Column("reason_codes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "completed_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("assigned_role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Open", nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=24), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.CheckConstraint(f"type IN ({_TYPES})", name="ck_review_items_type"),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_review_items_status"),
        sa.CheckConstraint(
            f"resolution IS NULL OR resolution IN ({_ACTIONS})", name="ck_review_items_resolution"
        ),
        sa.CheckConstraint("length(btrim(primary_code)) > 0", name="ck_review_items_primary_code"),
        sa.CheckConstraint("cardinality(reason_codes) > 0", name="ck_review_items_reason_codes"),
        sa.CheckConstraint(
            "array_position(reason_codes, NULL) IS NULL",
            name="ck_review_items_reason_codes_no_null",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(completed_steps) = 'array'", name="ck_review_items_completed_steps"
        ),
        sa.CheckConstraint("source_version > 0", name="ck_review_items_source_version"),
        sa.CheckConstraint("version > 0", name="ck_review_items_version"),
        sa.CheckConstraint(
            "(status = 'Open' AND resolved_by IS NULL AND resolved_at IS NULL AND resolution IS NULL) OR "
            "(status <> 'Open' AND resolved_at IS NOT NULL AND resolution IS NOT NULL)",
            name="ck_review_items_resolution_state",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_review_items_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "treasury_id"],
            ["payment_requests.id", "payment_requests.treasury_id"],
            name="fk_review_items_request_treasury",
            ondelete="RESTRICT",
        ),
        # Users are soft-deleted; the resolving actor remains part of the audit record.
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_review_items_id_org"),
    )
    op.create_index(
        "uq_review_items_open_request_type",
        "review_items",
        ["request_id", "type"],
        unique=True,
        postgresql_where=sa.text("status = 'Open'"),
    )
    op.create_index(
        "ix_review_items_org_status_role_sla",
        "review_items",
        ["org_id", "status", "assigned_role", "sla_due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_items_org_status_role_sla", table_name="review_items")
    op.drop_index("uq_review_items_open_request_type", table_name="review_items")
    op.drop_table("review_items")
