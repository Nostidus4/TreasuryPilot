"""Add OIDC subject bindings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0026"
down_revision: str | None = "20261014_0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "oidc_identities",
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "length(subject) BETWEEN 1 AND 255", name="ck_oidc_identity_subject_length"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issuer", "subject"),
        sa.UniqueConstraint("user_id", "issuer", name="uq_oidc_identities_user_issuer"),
    )


def downgrade() -> None:
    op.drop_table("oidc_identities")
