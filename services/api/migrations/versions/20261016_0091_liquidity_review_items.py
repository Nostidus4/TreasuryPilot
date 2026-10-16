"""Review items for liquidity plans and an idle marker for the liquidity cycle (EXE-014, #261)

A liquidity plan serves no request, so its review items (fee approval, stopped plan, unresolved
transaction) are keyed by plan. ``treasuries.liquidity_idle_*`` records that a cycle found nothing
to do for a given set of inputs, so the next cycles skip the claim until they change.

Revision ID: 20261016_0091
Revises: 20261016_0088
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0091"
down_revision: str | None = "20261016_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "(request_id IS NOT NULL AND request_version IS NOT NULL "
    "AND mandate_version_id IS NULL) OR "
    "(request_id IS NULL AND request_version IS NULL "
    "AND mandate_version_id IS NOT NULL AND type = 'DISCREPANCY')"
)
_NEW = (
    _OLD + " OR (request_id IS NULL AND request_version IS NULL AND mandate_version_id IS NULL "
    "AND plan_id IS NOT NULL AND type IN ('FEE_APPROVAL', 'INFRA', 'UNCERTAIN_TX'))"
)


def upgrade() -> None:
    op.drop_constraint("ck_review_items_subject", "review_items", type_="check")
    op.create_check_constraint("ck_review_items_subject", "review_items", _NEW)
    op.create_index(
        "uq_review_items_open_plan_type",
        "review_items",
        ["plan_id", "type"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'Open' AND request_id IS NULL AND mandate_version_id IS NULL"
        ),
    )
    op.add_column(
        "treasuries", sa.Column("liquidity_idle_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("treasuries", sa.Column("liquidity_idle_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM review_items WHERE request_id IS NULL
                       AND mandate_version_id IS NULL) THEN
                RAISE EXCEPTION 'cannot downgrade 20261016_0091: liquidity review items exist';
            END IF;
        END $$
        """
    )
    op.drop_column("treasuries", "liquidity_idle_key")
    op.drop_column("treasuries", "liquidity_idle_at")
    op.drop_index("uq_review_items_open_plan_type", table_name="review_items")
    op.drop_constraint("ck_review_items_subject", "review_items", type_="check")
    op.create_check_constraint("ck_review_items_subject", "review_items", _OLD)
