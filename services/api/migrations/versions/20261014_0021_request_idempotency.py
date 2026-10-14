"""Add create idempotency storage to payment requests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0021"
down_revision: str | None = "20261014_0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("payment_requests", sa.Column("idempotency_key", sa.String(length=255)))
    op.add_column(
        "payment_requests", sa.Column("idempotency_payload_hash", sa.LargeBinary(length=32))
    )
    op.create_unique_constraint(
        "uq_payment_requests_idempotency_key", "payment_requests", ["org_id", "idempotency_key"]
    )
    op.create_check_constraint(
        "ck_payment_requests_idempotency_hash",
        "payment_requests",
        "(idempotency_key IS NULL AND idempotency_payload_hash IS NULL) OR "
        "(idempotency_key IS NOT NULL AND octet_length(idempotency_payload_hash) = 32)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_requests_idempotency_hash", "payment_requests", type_="check")
    op.drop_constraint("uq_payment_requests_idempotency_key", "payment_requests", type_="unique")
    op.drop_column("payment_requests", "idempotency_payload_hash")
    op.drop_column("payment_requests", "idempotency_key")
