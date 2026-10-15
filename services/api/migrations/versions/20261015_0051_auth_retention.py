"""Add explicit auth artifact retention and hash-only deletion receipts.

Revision ID: 20261015_0051
Revises: 20261015_0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0051"
down_revision: str | None = "20261015_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_retention_policies",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("session_retention_days", sa.Integer(), nullable=True),
        sa.Column("magic_link_retention_days", sa.Integer(), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_auth_retention_policies_singleton"),
        sa.CheckConstraint(
            "session_retention_days IS NULL OR session_retention_days BETWEEN 0 AND 36500",
            name="ck_auth_retention_policies_session_days",
        ),
        sa.CheckConstraint(
            "magic_link_retention_days IS NULL OR magic_link_retention_days BETWEEN 0 AND 36500",
            name="ck_auth_retention_policies_magic_link_days",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "subject_deletion_controls",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "audit_reference_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_subject_deletion_controls_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.drop_constraint("ck_deletion_receipts_record_type", "deletion_receipts", type_="check")
    op.create_check_constraint(
        "ck_deletion_receipts_record_type",
        "deletion_receipts",
        "record_type IN ('invite', 'session', 'magic_link', 'subject')",
    )


def downgrade() -> None:
    # Keep the expanded receipt check so prior code can coexist with already-created
    # auth-artifact and subject receipts after a code rollback.
    op.drop_table("subject_deletion_controls")
    op.drop_table("auth_retention_policies")
