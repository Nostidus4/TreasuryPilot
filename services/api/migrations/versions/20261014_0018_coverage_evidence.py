"""persist fallback and module clone evidence for treasury coverage

Revision ID: 20261014_0018
Revises: 20261014_0017
Create Date: 2026-10-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0018"
down_revision: str | None = "20261014_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "treasuries",
        sa.Column(
            "coverage_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_treasuries_coverage_details_array",
        "treasuries",
        "jsonb_typeof(coverage_details) = 'array'",
    )
    op.add_column("safe_config_snapshots", sa.Column("fallback_handler", sa.LargeBinary(length=20)))
    op.add_column(
        "safe_config_snapshots",
        sa.Column(
            "module_implementations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_safe_config_snapshots_fallback_handler_length",
        "safe_config_snapshots",
        "fallback_handler IS NULL OR octet_length(fallback_handler) = 20",
    )
    op.create_check_constraint(
        "ck_safe_config_snapshots_module_implementations_object",
        "safe_config_snapshots",
        "jsonb_typeof(module_implementations) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_safe_config_snapshots_module_implementations_object",
        "safe_config_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_safe_config_snapshots_fallback_handler_length",
        "safe_config_snapshots",
        type_="check",
    )
    op.drop_column("safe_config_snapshots", "module_implementations")
    op.drop_column("safe_config_snapshots", "fallback_handler")
    op.drop_constraint("ck_treasuries_coverage_details_array", "treasuries", type_="check")
    op.drop_column("treasuries", "coverage_details")
