"""EAS receipts: store the attest nonce so a resend can never double-attest (REC-005)

Revision ID: 20261016_0087
Revises: 20261016_0086
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0087"
down_revision: str | None = "20261016_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A resend re-signs with this nonce, so at most one attest transaction can ever be mined.
    op.add_column("chain_attestations", sa.Column("nonce", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("chain_attestations", "nonce")
