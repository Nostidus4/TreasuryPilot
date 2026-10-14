"""create observed on-chain events and indexer cursors

Revision ID: 20261015_0045
Revises: 20261014_0036
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0045"
down_revision: str | None = "20261014_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STREAMS = ("MODULE", "SAFE_CONFIG", "SAFE_EXEC", "TOKEN")


def _stream() -> postgresql.ENUM:
    return postgresql.ENUM(*STREAMS, name="index_stream", create_type=False)


def upgrade() -> None:
    postgresql.ENUM(*STREAMS, name="index_stream").create(op.get_bind(), checkfirst=False)
    op.create_table(
        "observed_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("stream", _stream(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("tx_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("block_number >= 0", name="ck_observed_events_block_number"),
        sa.CheckConstraint("log_index >= 0", name="ck_observed_events_log_index"),
        sa.CheckConstraint("octet_length(block_hash) = 32", name="ck_observed_events_block_hash"),
        sa.CheckConstraint("octet_length(tx_hash) = 32", name="ck_observed_events_tx_hash"),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_observed_events_address"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_observed_events_payload_object"
        ),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chain_id", "tx_hash", "log_index", name="uq_observed_events_chain_tx_log"
        ),
    )
    op.create_index(
        "ix_observed_events_treasury_stream_block",
        "observed_events",
        ["treasury_id", "stream", "block_number"],
    )
    op.create_table(
        "index_cursors",
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stream", _stream(), nullable=False),
        sa.Column("last_block", sa.BigInteger(), nullable=False),
        sa.Column("last_block_hash", sa.LargeBinary(length=32)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("last_block >= 0", name="ck_index_cursors_last_block"),
        sa.CheckConstraint(
            "last_block_hash IS NULL OR octet_length(last_block_hash) = 32",
            name="ck_index_cursors_block_hash",
        ),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("treasury_id", "stream"),
    )


def downgrade() -> None:
    op.drop_table("index_cursors")
    op.drop_index("ix_observed_events_treasury_stream_block", table_name="observed_events")
    op.drop_table("observed_events")
    postgresql.ENUM(name="index_stream").drop(op.get_bind(), checkfirst=False)
