"""track on-chain owner capability freshness

Revision ID: 20261013_0004
Revises: 20261013_0003
Create Date: 2026-10-13 00:15:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0004"
down_revision: str | None = "20261013_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memberships",
        sa.Column(
            "owner_is_onchain", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "memberships", sa.Column("owner_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_memberships_owner_check_time",
        "memberships",
        "NOT owner_is_onchain OR owner_checked_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memberships_owner_check_time", "memberships", type_="check")
    op.drop_column("memberships", "owner_checked_at")
    op.drop_column("memberships", "owner_is_onchain")
