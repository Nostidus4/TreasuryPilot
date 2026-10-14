"""Add scoped inbound invoice API keys."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0028"
down_revision: str | None = "20261014_0027"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name="ck_invoice_api_keys_name"
        ),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_invoice_api_keys_hash"),
        sa.CheckConstraint("cardinality(scopes) > 0", name="ck_invoice_api_keys_scopes"),
        sa.CheckConstraint(
            "array_position(scopes, NULL) IS NULL",
            name="ck_invoice_api_keys_scopes_no_null",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("token_hash", name="uq_invoice_api_keys_token_hash"),
    )
    op.create_index("ix_invoice_api_keys_org", "invoice_api_keys", ["org_id"])
    op.add_column(
        "payment_requests",
        sa.Column("created_via_api_key_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_payment_requests_created_via_api_key",
        "payment_requests",
        "invoice_api_keys",
        ["created_via_api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payment_requests_created_via_api_key", "payment_requests", type_="foreignkey"
    )
    op.drop_column("payment_requests", "created_via_api_key_id")
    op.drop_index("ix_invoice_api_keys_org", table_name="invoice_api_keys")
    op.drop_table("invoice_api_keys")
