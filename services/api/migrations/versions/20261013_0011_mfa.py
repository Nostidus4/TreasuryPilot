"""Add TOTP, recovery codes and session-bound step-up.

Revision ID: 20261013_0011
Revises: 20261013_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0011"
down_revision: str | None = "20261013_0012"
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
        sa.Column("pending_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), server_default="-1", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pending_session_id"], ["sessions.id"], ondelete="SET NULL"),
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
    op.create_table(
        "mfa_webauthn_credentials",
        sa.Column("credential_id", sa.LargeBinary(length=1024), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("credential_id"),
    )
    op.create_index("ix_mfa_webauthn_credentials_user_id", "mfa_webauthn_credentials", ["user_id"])
    op.create_table(
        "mfa_webauthn_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("challenge", sa.LargeBinary(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('registration', 'authentication')", name="ck_mfa_webauthn_challenge_kind"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mfa_webauthn_challenges_user_session",
        "mfa_webauthn_challenges",
        ["user_id", "session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_webauthn_challenges_user_session", table_name="mfa_webauthn_challenges")
    op.drop_table("mfa_webauthn_challenges")
    op.drop_index("ix_mfa_webauthn_credentials_user_id", table_name="mfa_webauthn_credentials")
    op.drop_table("mfa_webauthn_credentials")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_totp")
    op.drop_column("sessions", "step_up_at")
