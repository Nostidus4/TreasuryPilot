"""Index approvals for the periodic expiry sweep."""

from __future__ import annotations

from alembic import op

revision: str = "20261014_0012"
down_revision: str | None = "20261014_0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_approvals_valid_expiry",
        "approvals",
        ["expires_at"],
        postgresql_where="status = 'Valid'",
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_valid_expiry", table_name="approvals")
