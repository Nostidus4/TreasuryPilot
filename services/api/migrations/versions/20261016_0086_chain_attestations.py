"""EAS payment receipts: one chain_attestations row per request (REC-005, ADR-018)

Revision ID: 20261016_0086
Revises: 20261015_0085
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0086"
down_revision: str | None = "20261015_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The receipt carries only hashes and addresses (BR-074); this row holds the publication
    # state. A failed publication never touches payment_requests.status (M11 §11).
    op.create_table(
        "chain_attestations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("schema_uid", postgresql.BYTEA(), nullable=False),
        sa.Column("attestation_uid", postgresql.BYTEA(), nullable=True),
        sa.Column("tx_hash", postgresql.BYTEA(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('Queued', 'Sent', 'Confirmed', 'Failed')",
            name="ck_chain_attestations_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_chain_attestations_attempts"),
        sa.CheckConstraint(
            "octet_length(schema_uid) = 32", name="ck_chain_attestations_schema_uid"
        ),
        sa.CheckConstraint(
            "attestation_uid IS NULL OR octet_length(attestation_uid) = 32",
            name="ck_chain_attestations_uid",
        ),
        sa.CheckConstraint(
            "tx_hash IS NULL OR octet_length(tx_hash) = 32", name="ck_chain_attestations_tx_hash"
        ),
        sa.CheckConstraint(
            "(status = 'Confirmed') = (attestation_uid IS NOT NULL)",
            name="ck_chain_attestations_confirmed_uid",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_chain_attestations_request"),
    )
    op.create_index(
        "ix_chain_attestations_due",
        "chain_attestations",
        ["next_attempt_at"],
        postgresql_where=sa.text("status <> 'Confirmed'"),
    )


def downgrade() -> None:
    op.drop_index("ix_chain_attestations_due", table_name="chain_attestations")
    op.drop_table("chain_attestations")
