"""Attach the AI or template draft to one-time exception records.

Revision ID: 20261015_0064
Revises: 20261015_0063
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0064"
down_revision: str | None = "20261015_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exceptions", sa.Column("draft", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("exceptions", "draft")
