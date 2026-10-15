"""Persist Travel Rule exchanges and encrypted party data.

Revision ID: 20261015_0053
Revises: 20261015_0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0053"
down_revision: str | None = "20261015_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "travel_rule_exchanges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=78, scale=0), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("origin_jurisdiction", sa.String(length=2), nullable=False),
        sa.Column("beneficiary_jurisdiction", sa.String(length=2), nullable=False),
        sa.Column("beneficiary_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'SELF_HOSTED', 'NOT_REQUIRED', 'ERROR')",
            name="ck_travel_rule_exchanges_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_travel_rule_exchanges_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_travel_rule_exchanges_currency"),
        sa.CheckConstraint(
            "octet_length(beneficiary_address) = 20",
            name="ck_travel_rule_exchanges_address",
        ),
        sa.CheckConstraint("chain_id > 0", name="ck_travel_rule_exchanges_chain"),
        sa.CheckConstraint(
            "origin_jurisdiction ~ '^[A-Z]{2}$'",
            name="ck_travel_rule_exchanges_origin",
        ),
        sa.CheckConstraint(
            "beneficiary_jurisdiction ~ '^[A-Z]{2}$'",
            name="ck_travel_rule_exchanges_beneficiary",
        ),
        sa.CheckConstraint("length(btrim(provider)) > 0", name="ck_travel_rule_exchanges_provider"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "request_id", name="uq_travel_rule_exchanges_org_request"),
    )
    op.create_index(
        "ix_travel_rule_exchanges_status",
        "travel_rule_exchanges",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_travel_rule_exchanges_status", table_name="travel_rule_exchanges")
    op.drop_table("travel_rule_exchanges")
