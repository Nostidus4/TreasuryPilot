"""Add configurable invitation retention and hash-only deletion receipts.

Revision ID: 20261013_0012
Revises: 20261014_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0012"
down_revision: str | None = "20261014_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retention_policies",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invite_retention_days", sa.Integer(), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "invite_retention_days IS NULL OR invite_retention_days BETWEEN 0 AND 36500",
            name="ck_retention_policies_invite_days",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.create_table(
        "deletion_receipts",
        sa.Column("record_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(record_hash) = 32", name="ck_deletion_receipts_hash_length"
        ),
        sa.CheckConstraint("record_type = 'invite'", name="ck_deletion_receipts_record_type"),
        sa.PrimaryKeyConstraint("record_hash"),
    )


def downgrade() -> None:
    op.drop_table("deletion_receipts")
    op.drop_table("retention_policies")
