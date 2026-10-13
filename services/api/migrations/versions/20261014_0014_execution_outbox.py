"""create execution outbox, transaction and gas ledger tables

Revision ID: 20261014_0014
Revises: 20261014_0013
Create Date: 2026-10-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0014"
down_revision: str | None = "20261014_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=78, scale=0)
ENUMS = {
    "operation_kind": ("PAY", "REFILL", "SWAP", "WITHDRAW", "SUPPLY"),
    "operation_status": (
        "NotSubmitted",
        "Submitted",
        "Pending",
        "Confirmed",
        "Reverted",
        "Unknown",
        "Abandoned",
    ),
    "transaction_status": ("Submitted", "Pending", "Confirmed", "Reverted", "Dropped", "Unknown"),
    "transaction_crosscheck": ("NotRun", "Match", "Mismatch"),
    "gas_payer": ("EXECUTOR", "SENTINEL", "RECEIPT"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(*ENUMS[name], name=name).create(bind, checkfirst=False)

    op.create_table(
        "operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", sa.LargeBinary(length=32), nullable=False),
        sa.Column("kind", _enum("operation_kind"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            _enum("operation_status"),
            server_default="NotSubmitted",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(step_id) = 32", name="ck_operations_step_id_length"),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0", name="ck_operations_idempotency_key"
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_operations_payload_object"),
        sa.CheckConstraint("attempts >= 0", name="ck_operations_attempts_nonnegative"),
        sa.ForeignKeyConstraint(
            ["request_id", "treasury_id"],
            ["payment_requests.id", "payment_requests.treasury_id"],
            name="fk_operations_request_treasury",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id", name="uq_operations_step_id"),
        sa.UniqueConstraint(
            "treasury_id", "idempotency_key", name="uq_operations_treasury_idempotency"
        ),
    )
    op.create_index("ix_operations_treasury_status", "operations", ["treasury_id", "status"])
    op.create_index(
        "ix_operations_request_created",
        "operations",
        ["request_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("nonce", MONEY, nullable=False),
        sa.Column("from_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("replaced_by_tx_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", _enum("transaction_status"), nullable=False),
        sa.Column("block_number", sa.BigInteger()),
        sa.Column("block_hash", sa.LargeBinary(length=32)),
        sa.Column("confirmations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revert_selector", sa.LargeBinary(length=4)),
        sa.Column("gas_used", MONEY),
        sa.Column("effective_gas_price", MONEY),
        sa.Column("fee_wei", MONEY),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_pending_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "crosscheck",
            _enum("transaction_crosscheck"),
            server_default="NotRun",
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(tx_hash) = 32", name="ck_transactions_hash_length"),
        sa.CheckConstraint("octet_length(from_address) = 20", name="ck_transactions_from_length"),
        sa.CheckConstraint("nonce >= 0", name="ck_transactions_nonce_nonnegative"),
        sa.CheckConstraint(
            "block_number IS NULL OR block_number >= 0", name="ck_transactions_block_number"
        ),
        sa.CheckConstraint("confirmations >= 0", name="ck_transactions_confirmations"),
        sa.CheckConstraint("gas_used IS NULL OR gas_used >= 0", name="ck_transactions_gas_used"),
        sa.CheckConstraint(
            "effective_gas_price IS NULL OR effective_gas_price >= 0",
            name="ck_transactions_gas_price",
        ),
        sa.CheckConstraint("fee_wei IS NULL OR fee_wei >= 0", name="ck_transactions_fee"),
        sa.CheckConstraint(
            "block_hash IS NULL OR octet_length(block_hash) = 32",
            name="ck_transactions_block_hash_length",
        ),
        sa.CheckConstraint(
            "revert_selector IS NULL OR octet_length(revert_selector) = 4",
            name="ck_transactions_revert_selector_length",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_tx_id", "operation_id"],
            ["transactions.id", "transactions.operation_id"],
            name="fk_transactions_replacement_same_operation",
            ondelete="SET NULL (replaced_by_tx_id)",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "operation_id", name="uq_transactions_id_operation"),
        sa.UniqueConstraint("chain_id", "tx_hash", name="uq_transactions_chain_hash"),
    )
    op.create_index(
        "ix_transactions_operation_submitted", "transactions", ["operation_id", "submitted_at"]
    )
    op.create_index(
        "ix_transactions_status_pending", "transactions", ["status", "last_seen_pending_at"]
    )

    op.create_table(
        "gas_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payer", _enum("gas_payer"), nullable=False),
        sa.Column("payer_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("fee_wei", MONEY, nullable=False),
        sa.Column("reverted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.CheckConstraint("fee_wei >= 0", name="ck_gas_ledger_fee_nonnegative"),
        sa.CheckConstraint("octet_length(payer_address) = 20", name="ck_gas_ledger_payer_address"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_gas_ledger_transaction"),
    )
    op.create_index("ix_gas_ledger_treasury_day", "gas_ledger", ["treasury_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_gas_ledger_treasury_day", table_name="gas_ledger")
    op.drop_table("gas_ledger")
    op.drop_index("ix_transactions_status_pending", table_name="transactions")
    op.drop_index("ix_transactions_operation_submitted", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_operations_request_created", table_name="operations")
    op.drop_index("ix_operations_treasury_status", table_name="operations")
    op.drop_table("operations")
    bind = op.get_bind()
    for name in reversed(tuple(ENUMS)):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
