"""add outbound webhook endpoints and delivery state

Revision ID: 20261014_0032
Revises: 20261014_0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0032"
down_revision: str | None = "20261014_0031"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("event_types", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("url LIKE 'https://%'", name="ck_webhook_endpoints_https"),
        sa.CheckConstraint("cardinality(event_types) > 0", name="ck_webhook_endpoints_event_types"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_webhook_endpoints_id_org"),
    )
    op.create_index("ix_webhook_endpoints_org", "webhook_endpoints", ["org_id", "created_at"])
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=240), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'delivered', 'dead')",
            name="ck_webhook_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id", "org_id"],
            ["webhook_endpoints.id", "webhook_endpoints.org_id"],
            name="fk_webhook_deliveries_endpoint_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "org_id"],
            ["domain_events.id", "domain_events.org_id"],
            name="fk_webhook_deliveries_event_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_deliveries_endpoint_event"),
    )
    op.create_index(
        "ix_webhook_deliveries_pending",
        "webhook_deliveries",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )
    op.create_index(
        "ix_webhook_deliveries_dead",
        "webhook_deliveries",
        ["org_id", "created_at"],
        postgresql_where=sa.text("status = 'dead'"),
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_dead", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_pending", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_endpoints_org", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
