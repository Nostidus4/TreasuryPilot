"""plan_steps: minOut and the labelled venue of a swap-for-gas step (EXE-011)

Revision ID: 20261015_0072
Revises: 20261015_0071
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0072"
down_revision: str | None = "20261015_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_steps", sa.Column("min_out", sa.Numeric(78, 0), nullable=True))
    op.add_column("plan_steps", sa.Column("venue", sa.Text(), nullable=True))
    # SWAP_IN is action 3; only a swap carries an output bound, and its router is always labelled.
    op.create_check_constraint(
        "ck_plan_steps_swap_fields",
        "plan_steps",
        "(action = 3 AND min_out IS NOT NULL AND min_out > 0 AND venue IS NOT NULL AND venue = 'TEST_ROUTER')"
        " OR (action <> 3 AND min_out IS NULL AND venue IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_plan_steps_swap_fields", "plan_steps", type_="check")
    op.drop_column("plan_steps", "venue")
    op.drop_column("plan_steps", "min_out")
