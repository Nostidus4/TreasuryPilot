"""Add destination jurisdiction to vendors for Travel Rule transfers.

Revision ID: 20261015_0058
Revises: 20261015_0057
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0058"
down_revision: str | None = "20261015_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("country", sa.String(length=2), nullable=True))
    op.create_check_constraint(
        "ck_vendors_country", "vendors", "country IS NULL OR country ~ '^[A-Z]{2}$'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_vendors_country", "vendors", type_="check")
    op.drop_column("vendors", "country")
