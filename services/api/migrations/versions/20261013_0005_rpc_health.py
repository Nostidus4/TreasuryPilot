"""create rpc_health

Revision ID: 20261013_0005
Revises: 20261012_0002
Create Date: 2026-10-13 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0005"
# Rechain onto the latest head if the mandate/invoice schema PRs merge first.
down_revision: str | None = "20261012_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per RPC attempt by the worker's chain client (M06 §4).
    # shortcut: nothing prunes rows yet, add the 24 h cleanup when the client is wired into tasks.
    op.create_table(
        "rpc_health",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("head", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_rpc_health_latency_ms"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rpc_health_provider_at", "rpc_health", ["provider", "at"])


def downgrade() -> None:
    op.drop_index("ix_rpc_health_provider_at", table_name="rpc_health")
    op.drop_table("rpc_health")
