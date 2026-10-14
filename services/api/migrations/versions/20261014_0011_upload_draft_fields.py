"""allow incomplete upload drafts until operator confirms extraction fields

Revision ID: 20261014_0011
Revises: 20261014_0010
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20261014_0011"
down_revision: str | None = "20261014_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are complete; only new upload drafts can use these nulls.
    for column in ("vendor_id", "payee_id", "invoice_no", "issue_date", "due_at", "amount"):
        op.alter_column("payment_requests", column, nullable=True)
    op.create_check_constraint(
        "ck_payment_requests_complete_before_transition",
        "payment_requests",
        "status = 'Draft' OR (vendor_id IS NOT NULL AND payee_id IS NOT NULL AND "
        "invoice_no IS NOT NULL AND issue_date IS NOT NULL AND due_at IS NOT NULL "
        "AND amount IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_upload_request_confirmed_before_transition",
        "payment_requests",
        "source != 'UPLOAD' OR status = 'Draft' OR extraction_confirmed_by IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_upload_request_confirmed_before_transition", "payment_requests", type_="check"
    )
    op.drop_constraint(
        "ck_payment_requests_complete_before_transition", "payment_requests", type_="check"
    )
    # Refuse to discard user data or fail later with an opaque NOT NULL error.
    if not context.is_offline_mode():
        incomplete = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM payment_requests WHERE vendor_id IS NULL "
                    "OR payee_id IS NULL OR invoice_no IS NULL OR issue_date IS NULL "
                    "OR due_at IS NULL OR amount IS NULL)"
                )
            )
            .scalar_one()
        )
        if incomplete:
            raise RuntimeError("Resolve or remove incomplete upload drafts before downgrade")
    for column in ("amount", "due_at", "issue_date", "invoice_no", "payee_id", "vendor_id"):
        op.alter_column("payment_requests", column, nullable=False)
