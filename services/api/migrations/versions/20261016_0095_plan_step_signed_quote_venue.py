"""plan_steps: allow the SIGNED_QUOTE venue of the production swap adapter (EXE-L02, #152)

Revision ID: 20261016_0095
Revises: 20261016_0094
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_0095"
down_revision: str | None = "20261016_0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE = "(action = 3 AND min_out IS NOT NULL AND min_out > 0 AND venue IS NOT NULL AND venue IN ({venues})) OR (action <> 3 AND min_out IS NULL AND venue IS NULL)"


def _swap(venues: str) -> None:
    op.drop_constraint("ck_plan_steps_swap_fields", "plan_steps", type_="check")
    op.create_check_constraint(
        "ck_plan_steps_swap_fields", "plan_steps", _RULE.format(venues=venues)
    )


def upgrade() -> None:
    _swap("'TEST_ROUTER', 'SIGNED_QUOTE'")


def downgrade() -> None:
    # Fails while a SIGNED_QUOTE step exists: plan_steps is append-only and must not be rewritten.
    _swap("'TEST_ROUTER'")
