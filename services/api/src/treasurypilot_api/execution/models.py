from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class OperationKind(StrEnum):
    PAY = "PAY"
    REFILL = "REFILL"
    SWAP = "SWAP"
    WITHDRAW = "WITHDRAW"
    SUPPLY = "SUPPLY"


class OperationStatus(StrEnum):
    NOT_SUBMITTED = "NotSubmitted"
    SUBMITTED = "Submitted"
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    REVERTED = "Reverted"
    UNKNOWN = "Unknown"
    ABANDONED = "Abandoned"


class TransactionStatus(StrEnum):
    SUBMITTED = "Submitted"
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    REVERTED = "Reverted"
    DROPPED = "Dropped"
    UNKNOWN = "Unknown"


class TransactionCrosscheck(StrEnum):
    NOT_RUN = "NotRun"
    MATCH = "Match"
    MISMATCH = "Mismatch"


class GasPayer(StrEnum):
    EXECUTOR = "EXECUTOR"
    SENTINEL = "SENTINEL"
    RECEIPT = "RECEIPT"


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class, name=name, values_callable=lambda values: [value.value for value in values]
    )


operation_kind_enum = _enum(OperationKind, "operation_kind")
operation_status_enum = _enum(OperationStatus, "operation_status")
transaction_status_enum = _enum(TransactionStatus, "transaction_status")
transaction_crosscheck_enum = _enum(TransactionCrosscheck, "transaction_crosscheck")
gas_payer_enum = _enum(GasPayer, "gas_payer")


class Operation(Base):
    """Durable outbox row for one signed execution step."""

    __tablename__ = "operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "treasury_id"],
            ["payment_requests.id", "payment_requests.treasury_id"],
            name="fk_operations_request_treasury",
            ondelete="RESTRICT",
        ),
        CheckConstraint("octet_length(step_id) = 32", name="ck_operations_step_id_length"),
        CheckConstraint("length(btrim(idempotency_key)) > 0", name="ck_operations_idempotency_key"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_operations_payload_object"),
        CheckConstraint("attempts >= 0", name="ck_operations_attempts_nonnegative"),
        UniqueConstraint("step_id", name="uq_operations_step_id"),
        UniqueConstraint(
            "treasury_id", "idempotency_key", name="uq_operations_treasury_idempotency"
        ),
        Index("ix_operations_treasury_status", "treasury_id", "status"),
        Index("ix_operations_request_created", "request_id", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    plan_step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_id: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    kind: Mapped[OperationKind] = mapped_column(operation_kind_enum, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[OperationStatus] = mapped_column(
        operation_status_enum,
        nullable=False,
        default=OperationStatus.NOT_SUBMITTED,
        server_default=OperationStatus.NOT_SUBMITTED.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Transaction(Base):
    """An on-chain attempt for an operation; replacements remain separate rows."""

    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["replaced_by_tx_id", "operation_id"],
            ["transactions.id", "transactions.operation_id"],
            name="fk_transactions_replacement_same_operation",
            ondelete="SET NULL (replaced_by_tx_id)",
        ),
        CheckConstraint("octet_length(tx_hash) = 32", name="ck_transactions_hash_length"),
        CheckConstraint("octet_length(from_address) = 20", name="ck_transactions_from_length"),
        CheckConstraint("nonce >= 0", name="ck_transactions_nonce_nonnegative"),
        CheckConstraint(
            "block_number IS NULL OR block_number >= 0", name="ck_transactions_block_number"
        ),
        CheckConstraint("confirmations >= 0", name="ck_transactions_confirmations"),
        CheckConstraint("gas_used IS NULL OR gas_used >= 0", name="ck_transactions_gas_used"),
        CheckConstraint(
            "effective_gas_price IS NULL OR effective_gas_price >= 0",
            name="ck_transactions_gas_price",
        ),
        CheckConstraint("fee_wei IS NULL OR fee_wei >= 0", name="ck_transactions_fee"),
        CheckConstraint(
            "block_hash IS NULL OR octet_length(block_hash) = 32",
            name="ck_transactions_block_hash_length",
        ),
        CheckConstraint(
            "revert_selector IS NULL OR octet_length(revert_selector) = 4",
            name="ck_transactions_revert_selector_length",
        ),
        UniqueConstraint("id", "operation_id", name="uq_transactions_id_operation"),
        UniqueConstraint("chain_id", "tx_hash", name="uq_transactions_chain_hash"),
        Index("ix_transactions_operation_submitted", "operation_id", "submitted_at"),
        Index("ix_transactions_status_pending", "status", "last_seen_pending_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False
    )
    chain_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chains.chain_id", ondelete="RESTRICT"), nullable=False
    )
    tx_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    nonce: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    from_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    replaced_by_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[TransactionStatus] = mapped_column(
        transaction_status_enum,
        nullable=False,
        default=TransactionStatus.SUBMITTED,
        server_default=TransactionStatus.SUBMITTED.value,
    )
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    block_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    revert_selector: Mapped[bytes | None] = mapped_column(LargeBinary(4))
    gas_used: Mapped[int | None] = mapped_column(Numeric(78, 0))
    effective_gas_price: Mapped[int | None] = mapped_column(Numeric(78, 0))
    fee_wei: Mapped[int | None] = mapped_column(Numeric(78, 0))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crosscheck: Mapped[TransactionCrosscheck] = mapped_column(
        transaction_crosscheck_enum,
        nullable=False,
        default=TransactionCrosscheck.NOT_RUN,
        server_default=TransactionCrosscheck.NOT_RUN.value,
    )


class GasLedger(Base):
    """Per-transaction gas spend, with both logical payer and concrete address."""

    __tablename__ = "gas_ledger"
    __table_args__ = (
        CheckConstraint("fee_wei >= 0", name="ck_gas_ledger_fee_nonnegative"),
        CheckConstraint("octet_length(payer_address) = 20", name="ck_gas_ledger_payer_address"),
        UniqueConstraint("transaction_id", name="uq_gas_ledger_transaction"),
        Index("ix_gas_ledger_treasury_day", "treasury_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    payer: Mapped[GasPayer] = mapped_column(gas_payer_enum, nullable=False)
    payer_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    fee_wei: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    reverted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)


class IndexStream(StrEnum):
    MODULE = "MODULE"
    SAFE_CONFIG = "SAFE_CONFIG"
    SAFE_EXEC = "SAFE_EXEC"
    TOKEN = "TOKEN"


index_stream_enum = _enum(IndexStream, "index_stream")


class ObservedEvent(Base):
    """A log read from the chain (M06 §8.3); ``removed`` marks a reorged-out log."""

    __tablename__ = "observed_events"
    __table_args__ = (
        CheckConstraint("block_number >= 0", name="ck_observed_events_block_number"),
        CheckConstraint("log_index >= 0", name="ck_observed_events_log_index"),
        CheckConstraint("octet_length(block_hash) = 32", name="ck_observed_events_block_hash"),
        CheckConstraint("octet_length(tx_hash) = 32", name="ck_observed_events_tx_hash"),
        CheckConstraint("octet_length(address) = 20", name="ck_observed_events_address"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_observed_events_payload_object"
        ),
        UniqueConstraint(
            "chain_id", "tx_hash", "log_index", name="uq_observed_events_chain_tx_log"
        ),
        Index("ix_observed_events_treasury_stream_block", "treasury_id", "stream", "block_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    chain_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chains.chain_id", ondelete="RESTRICT"), nullable=False
    )
    stream: Mapped[IndexStream] = mapped_column(index_stream_enum, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    tx_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class IndexCursor(Base):
    __tablename__ = "index_cursors"
    __table_args__ = (
        CheckConstraint("last_block >= 0", name="ck_index_cursors_last_block"),
        CheckConstraint(
            "last_block_hash IS NULL OR octet_length(last_block_hash) = 32",
            name="ck_index_cursors_block_hash",
        ),
    )

    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="CASCADE"), primary_key=True
    )
    stream: Mapped[IndexStream] = mapped_column(index_stream_enum, primary_key=True)
    last_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_block_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
