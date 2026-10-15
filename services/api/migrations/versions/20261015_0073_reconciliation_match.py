"""reconciliation resolution columns and auto-match off by default

Revision ID: 20261015_0073
Revises: 20261015_0072
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0073"
down_revision: str | None = "20261015_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # M11-D3 / OQ-09: auto-match is off unless an admin turns it on. Nothing consumed the flag
    # before REC-003, so no org has made a deliberate choice yet.
    op.alter_column("organizations", "auto_match", server_default=sa.text("false"))
    op.execute("UPDATE organizations SET auto_match = false")
    op.add_column("reconciliations", sa.Column("resolution_note", sa.Text(), nullable=True))
    for column in ("resolved_by", "owner_ack_by"):
        op.add_column(
            "reconciliations",
            sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_reconciliations_{column}",
            "reconciliations",
            "users",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column(
        "reconciliations", sa.Column("owner_ack_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    # Irreversible data change: the UPDATE above cannot be undone, so earlier ``true`` values are
    # not restored. Only the column default goes back.
    op.drop_column("reconciliations", "owner_ack_at")
    for column in ("owner_ack_by", "resolved_by"):
        op.drop_constraint(f"fk_reconciliations_{column}", "reconciliations", type_="foreignkey")
        op.drop_column("reconciliations", column)
    op.drop_column("reconciliations", "resolution_note")
    op.alter_column("organizations", "auto_match", server_default=sa.text("true"))
