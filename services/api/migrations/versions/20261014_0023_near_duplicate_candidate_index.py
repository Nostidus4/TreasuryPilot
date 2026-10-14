"""index near-duplicate candidate fields on payment requests

Revision ID: 20261014_0023
Revises: 20261014_0021
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_0023"
down_revision: str | None = "20261014_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_payment_requests_vendor_amount_issue_date",
        "payment_requests",
        ["vendor_id", "amount", "issue_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_requests_vendor_amount_issue_date", table_name="payment_requests")
