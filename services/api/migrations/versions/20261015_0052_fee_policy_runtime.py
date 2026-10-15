"""store fee proposal basis and fee-review estimates

Revision ID: 20261015_0052
Revises: 20261015_0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0052"
down_revision: str | None = "20261015_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "treasury_fee_policies",
        sa.Column(
            "avg_plan_fee_7d_wei",
            sa.Numeric(precision=78, scale=0),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "treasury_fee_policies",
        sa.Column(
            "p90_plan_fee_7d_wei",
            sa.Numeric(precision=78, scale=0),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "treasury_fee_policies",
        sa.Column(
            "plans_per_day_7d",
            sa.Numeric(precision=12, scale=3),
            server_default="0",
            nullable=False,
        ),
    )
    op.alter_column("treasury_fee_policies", "reference_eth_price", nullable=True)
    op.drop_constraint(
        "ck_treasury_fee_policies_reference_eth_price",
        "treasury_fee_policies",
        type_="check",
    )
    op.create_check_constraint(
        "ck_treasury_fee_policies_reference_eth_price",
        "treasury_fee_policies",
        "reference_eth_price IS NULL OR reference_eth_price > 0",
    )
    op.create_check_constraint(
        "ck_treasury_fee_policies_avg_plan_fee",
        "treasury_fee_policies",
        "avg_plan_fee_7d_wei >= 0",
    )
    op.create_check_constraint(
        "ck_treasury_fee_policies_p90_plan_fee",
        "treasury_fee_policies",
        "p90_plan_fee_7d_wei >= 0",
    )
    op.create_check_constraint(
        "ck_treasury_fee_policies_plans_per_day",
        "treasury_fee_policies",
        "plans_per_day_7d >= 0",
    )
    op.create_index(
        "uq_treasury_fee_policies_pending",
        "treasury_fee_policies",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND superseded_at IS NULL"),
    )
    op.create_unique_constraint("uq_fee_acceptances_plan", "fee_acceptances", ["plan_id"])

    op.add_column(
        "review_items",
        sa.Column("fee_estimate_wei", sa.Numeric(precision=78, scale=0)),
    )
    op.create_check_constraint(
        "ck_review_items_fee_estimate_nonnegative",
        "review_items",
        "fee_estimate_wei IS NULL OR fee_estimate_wei >= 0",
    )
    op.create_check_constraint(
        "ck_review_items_fee_approval_details",
        "review_items",
        "type <> 'FEE_APPROVAL' OR (plan_id IS NOT NULL AND fee_estimate_wei IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_items_fee_approval_details", "review_items", type_="check")
    op.drop_constraint("ck_review_items_fee_estimate_nonnegative", "review_items", type_="check")
    op.drop_column("review_items", "fee_estimate_wei")
    op.drop_constraint("uq_fee_acceptances_plan", "fee_acceptances", type_="unique")
    op.drop_index("uq_treasury_fee_policies_pending", table_name="treasury_fee_policies")
    op.drop_constraint(
        "ck_treasury_fee_policies_plans_per_day", "treasury_fee_policies", type_="check"
    )
    op.drop_constraint(
        "ck_treasury_fee_policies_p90_plan_fee", "treasury_fee_policies", type_="check"
    )
    op.drop_constraint(
        "ck_treasury_fee_policies_avg_plan_fee", "treasury_fee_policies", type_="check"
    )
    op.drop_constraint(
        "ck_treasury_fee_policies_reference_eth_price",
        "treasury_fee_policies",
        type_="check",
    )
    op.alter_column("treasury_fee_policies", "reference_eth_price", nullable=False)
    op.create_check_constraint(
        "ck_treasury_fee_policies_reference_eth_price",
        "treasury_fee_policies",
        "reference_eth_price > 0",
    )
    op.drop_column("treasury_fee_policies", "plans_per_day_7d")
    op.drop_column("treasury_fee_policies", "p90_plan_fee_7d_wei")
    op.drop_column("treasury_fee_policies", "avg_plan_fee_7d_wei")
