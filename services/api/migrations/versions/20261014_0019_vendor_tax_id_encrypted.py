"""store the vendor tax id as ciphertext

Revision ID: 20261014_0019
Revises: 20261014_0018
Create Date: 2026-10-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0019"
down_revision: str | None = "20261014_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No endpoint wrote the plaintext column before, so there is nothing to convert.
    op.drop_column("vendors", "tax_id")
    op.add_column("vendors", sa.Column("tax_id_encrypted", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("vendors", "tax_id_encrypted")
    op.add_column("vendors", sa.Column("tax_id", sa.String(length=64), nullable=True))
