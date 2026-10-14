"""Scope OIDC sessions to their configured organization."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0030"
down_revision: str | None = "20261014_0029"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("organization_scope_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sessions_organization_scope_id_organizations",
        "sessions",
        "organizations",
        ["organization_scope_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sessions_organization_scope_id_organizations", "sessions", type_="foreignkey"
    )
    op.drop_column("sessions", "organization_scope_id")
