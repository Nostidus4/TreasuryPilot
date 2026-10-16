"""Cross-chain bridge transfers with in-flight accounting (EXE-L03, #153)

One row per bridge transfer. ``(source_treasury_id, idempotency_key)`` is unique, so a transfer is
claimed exactly once; the worker only calls the bridge provider for the call that inserted the row.

Revision ID: 20261016_0093
Revises: 20261016_0092
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0093"
down_revision: str | None = "20261016_0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'PendingSend', 'Sent', 'Completed', 'Failed', 'Unknown'"


def upgrade() -> None:
    op.create_table(
        "bridge_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_treasury_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("treasuries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "destination_treasury_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("treasuries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(78, 0), nullable=False),
        sa.Column("min_amount_out", sa.Numeric(78, 0), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PendingSend"),
        sa.Column("provider_ref", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_bridge_transfers_status"),
        sa.CheckConstraint("amount > 0", name="ck_bridge_transfers_amount_positive"),
        sa.CheckConstraint("min_amount_out > 0", name="ck_bridge_transfers_min_out_positive"),
        sa.CheckConstraint(
            "source_treasury_id <> destination_treasury_id", name="ck_bridge_transfers_distinct"
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0", name="ck_bridge_transfers_idempotency_key"
        ),
        sa.UniqueConstraint(
            "source_treasury_id", "idempotency_key", name="uq_bridge_transfers_idempotency"
        ),
    )
    op.create_index(
        "ix_bridge_transfers_open",
        "bridge_transfers",
        ["source_treasury_id", "status"],
        postgresql_where=sa.text("status IN ('PendingSend', 'Sent', 'Unknown')"),
    )


def downgrade() -> None:
    op.drop_index("ix_bridge_transfers_open", table_name="bridge_transfers")
    op.drop_table("bridge_transfers")
