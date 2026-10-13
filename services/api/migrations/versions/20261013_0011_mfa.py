"""Add TOTP, recovery codes and session-bound step-up.

Revision ID: 20261013_0011
Revises: 20261013_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0011"
down_revision: str | None = "20261013_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("step_up_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "mfa_totp",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=True),
        sa.Column("pending_secret", sa.LargeBinary(), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), server_default="-1", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.CheckConstraint(
            "octet_length(code_hash) = 32", name="ck_mfa_recovery_codes_hash_length"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "code_hash"),
    )


def downgrade() -> None:
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_totp")
    op.drop_column("sessions", "step_up_at")
