"""ERP integration framework: OAuth connections and idempotent sync records (REC-L01)

Revision ID: 20261016_0090
Revises: 20261016_0088
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0090"
down_revision: str | None = "20261016_0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Connected", nullable=False),
        sa.Column("external_tenant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_name", sa.String(length=200), nullable=True),
        # AES-GCM FieldCipher envelopes (never plaintext).
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("payment_account_code", sa.String(length=64), nullable=True),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('Connected', 'ReauthRequired')", name="ck_erp_connections_status"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_erp_connections_org", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"], ["users.id"], name="fk_erp_connections_user", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "provider", name="uq_erp_connections_org_provider"),
    )
    op.create_table(
        "erp_sync_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="Pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("external_status", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('BILL', 'PAYMENT')", name="ck_erp_sync_records_kind"),
        sa.CheckConstraint(
            "status IN ('Pending', 'Synced', 'AwaitingApproval', 'Failed')",
            name="ck_erp_sync_records_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_erp_sync_records_attempts"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["erp_connections.id"],
            name="fk_erp_sync_records_connection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["reconciliations.id"],
            name="fk_erp_sync_records_reconciliation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "reconciliation_id", "kind", name="uq_erp_sync_records_slot"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_erp_sync_records_idempotency"),
    )
    op.create_index(
        "ix_erp_sync_records_due",
        "erp_sync_records",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('Pending', 'AwaitingApproval', 'Failed')"),
    )


def downgrade() -> None:
    op.drop_index("ix_erp_sync_records_due", table_name="erp_sync_records")
    op.drop_table("erp_sync_records")
    op.drop_table("erp_connections")
