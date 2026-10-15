"""liquidity plans: plans and operations without a payment request (EXE-014)

Revision ID: 20261015_0085
Revises: 20261015_0084
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0085"
down_revision: str | None = "20261015_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"


def upgrade() -> None:
    # A liquidity plan (SUPPLY / WITHDRAW only) serves no request: request_id is NULL and the
    # stepId key is its liquidity cycle id (M08 8.4).
    op.alter_column("plans", "request_id", nullable=True)
    op.add_column("plans", sa.Column("liquidity_cycle_id", postgresql.BYTEA(), nullable=True))
    op.create_check_constraint(
        "ck_plans_liquidity_cycle",
        "plans",
        "(request_id IS NULL) = (liquidity_cycle_id IS NOT NULL) "
        "AND (liquidity_cycle_id IS NULL OR octet_length(liquidity_cycle_id) = 32)",
    )
    # At most one open liquidity plan per treasury (also the idempotent claim of the cycle).
    op.create_index(
        "uq_plans_open_liquidity",
        "plans",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text(f"request_id IS NULL AND status IN ({_OPEN})"),
    )
    # The operations of a liquidity plan have no request; the composite FK passes on NULL.
    op.alter_column("operations", "request_id", nullable=True)


def downgrade() -> None:
    # Liquidity plans and operations are evidence (an idle cycle's empty Draft is the only row
    # the worker deletes): refuse to half-revert once any exists.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM plans WHERE request_id IS NULL)
               OR EXISTS (SELECT 1 FROM operations WHERE request_id IS NULL) THEN
                RAISE EXCEPTION 'cannot downgrade 20261015_0085: liquidity rows exist';
            END IF;
        END $$
        """
    )
    op.drop_index("uq_plans_open_liquidity", table_name="plans")
    op.drop_constraint("ck_plans_liquidity_cycle", "plans", type_="check")
    op.drop_column("plans", "liquidity_cycle_id")
    op.alter_column("operations", "request_id", nullable=False)
    op.alter_column("plans", "request_id", nullable=False)
