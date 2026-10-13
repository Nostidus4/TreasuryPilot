"""create the domain-event outbox and in-app notification schema

Revision ID: 20261013_0010
Revises: 20261013_0004
Create Date: 2026-10-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0010"
# 0005-0007 are taken on main (rpc_health, ai_calls, audit_log). This stack (0003 mandate,
# 0004 invoice) is not on main yet: when it lands, chain 0003 onto main's head so this
# file follows one linear history.
down_revision: str | None = "20261013_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        # Dead letter: an event that could not be routed is parked, not retried forever.
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("length(btrim(type)) > 0", name="ck_domain_events_type"),
        sa.CheckConstraint("length(btrim(entity_type)) > 0", name="ck_domain_events_entity_type"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_domain_events_payload_object"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_domain_events_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_domain_events_id_org"),
    )
    op.create_index(
        "ix_domain_events_pending",
        "domain_events",
        ["created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(btrim(type)) > 0", name="ck_notifications_type"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_notifications_title"),
        sa.CheckConstraint("length(btrim(body)) > 0", name="ck_notifications_body"),
        sa.CheckConstraint("link LIKE '/%'", name="ck_notifications_internal_link"),
        sa.CheckConstraint(
            "severity IN ('INFO', 'ACTION', 'CRITICAL')", name="ck_notifications_severity"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["event_id", "org_id"],
            ["domain_events.id", "domain_events.org_id"],
            name="fk_notifications_event_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_notifications_user_event"),
    )
    op.create_index("ix_notifications_org_created", "notifications", ["org_id", "created_at"])
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "org_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_org_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_domain_events_pending", table_name="domain_events")
    op.drop_table("domain_events")
