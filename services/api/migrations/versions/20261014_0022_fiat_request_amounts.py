"""store fiat invoice values and the approved FX reference"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0022"
down_revision: str | None = "20261014_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_requests",
        sa.Column("fiat_amount_minor_units", sa.Numeric(precision=78, scale=0), nullable=True),
    )
    op.add_column("payment_requests", sa.Column("fiat_currency", sa.String(length=3)))
    op.add_column(
        "payment_requests",
        sa.Column("fx_reference_quote", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "payment_requests", sa.Column("fx_tolerance_bps", sa.SmallInteger(), nullable=True)
    )
    op.create_check_constraint(
        "ck_payment_requests_fiat_fx_pair",
        "payment_requests",
        "(fiat_amount_minor_units IS NULL AND fiat_currency IS NULL AND "
        "fx_reference_quote IS NULL AND fx_tolerance_bps IS NULL) OR "
        "(fiat_amount_minor_units > 0 AND fiat_currency ~ '^[A-Z]{3}$' AND "
        "jsonb_typeof(fx_reference_quote) = 'object' AND "
        "fx_tolerance_bps BETWEEN 0 AND 10000)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_requests_fiat_fx_pair", "payment_requests", type_="check")
    op.drop_column("payment_requests", "fx_tolerance_bps")
    op.drop_column("payment_requests", "fx_reference_quote")
    op.drop_column("payment_requests", "fiat_currency")
    op.drop_column("payment_requests", "fiat_amount_minor_units")
