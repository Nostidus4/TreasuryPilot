"""Add MFA factors, recovery codes and per-session step-up time."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0044"
down_revision: str | None = "20261014_0036"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("step_up_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "mfa_factors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("credential_id", sa.LargeBinary(), nullable=True),
        sa.Column("public_key", sa.LargeBinary(length=64), nullable=True),
        sa.Column("sign_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_counter", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('totp', 'webauthn')", name="ck_mfa_factors_kind"),
        sa.CheckConstraint(
            "(kind = 'totp' AND secret IS NOT NULL AND credential_id IS NULL)"
            " OR (kind = 'webauthn' AND secret IS NULL AND credential_id IS NOT NULL"
            " AND public_key IS NOT NULL)",
            name="ck_mfa_factors_material",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mfa_factors_user_id", "mfa_factors", ["user_id"])
    op.create_index(
        "uq_mfa_factors_credential_id",
        "mfa_factors",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("credential_id IS NOT NULL"),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(code_hash) = 32", name="ck_mfa_recovery_codes_hash_length"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])


def downgrade() -> None:
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_factors")
    op.drop_column("sessions", "step_up_at")
