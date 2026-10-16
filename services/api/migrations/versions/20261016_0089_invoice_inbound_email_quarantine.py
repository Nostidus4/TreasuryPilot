"""invoice email sender allowlist and quarantine

Revision ID: 20261016_0089
Revises: 20261016_0088
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0089"
down_revision: str | None = "20261016_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoice_inbound_emails",
        sa.Column(
            "sender_allowlist",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )
    op.create_table(
        "invoice_inbound_quarantine",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_digest", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("sender_domain", sa.String(length=253), nullable=True),
        sa.Column("attachment_count", sa.SmallInteger(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('SENDER_NOT_ALLOWLISTED', 'SENDER_UNAUTHENTICATED')",
            name="ck_invoice_inbound_quarantine_reason",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "message_digest", name="uq_invoice_inbound_quarantine_message"
        ),
    )
    op.create_index(
        "ix_invoice_inbound_quarantine_org_received",
        "invoice_inbound_quarantine",
        ["org_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_inbound_quarantine_org_received", table_name="invoice_inbound_quarantine"
    )
    op.drop_table("invoice_inbound_quarantine")
    op.drop_column("invoice_inbound_emails", "sender_allowlist")
