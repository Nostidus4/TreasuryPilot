"""Add idempotency keys to invoice approvals."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0011"
down_revision: str | None = "20261014_0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("idempotency_key_hash", sa.LargeBinary(length=32)))
    op.create_check_constraint(
        "ck_approvals_idempotency_key_hash",
        "approvals",
        "idempotency_key_hash IS NULL OR octet_length(idempotency_key_hash) = 32",
    )
    op.create_unique_constraint(
        "uq_approvals_request_idempotency_key",
        "approvals",
        ["request_id", "idempotency_key_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_approvals_request_idempotency_key", "approvals", type_="unique")
    op.drop_constraint("ck_approvals_idempotency_key_hash", "approvals", type_="check")
    op.drop_column("approvals", "idempotency_key_hash")
