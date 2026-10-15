"""organization-scoped invoice email intake configuration

Revision ID: 20261015_0055
Revises: 20261015_0054
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0055"
down_revision: str | None = "20261015_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_inbound_emails",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_part", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "local_part ~ '^[a-f0-9]{48}$'", name="ck_invoice_inbound_emails_local_part"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_invoice_inbound_emails_treasury_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.create_index(
        "uq_invoice_inbound_emails_local_part",
        "invoice_inbound_emails",
        ["local_part"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_inbound_emails_local_part", table_name="invoice_inbound_emails")
    op.drop_table("invoice_inbound_emails")
