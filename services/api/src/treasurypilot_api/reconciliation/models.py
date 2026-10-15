from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class Reconciliation(Base):
    """One per request, created when the request is Paid (REC-002, BR-096)."""

    __tablename__ = "reconciliations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NotReady', 'Pending', 'Matched', 'Discrepancy')",
            name="ck_reconciliations_status",
        ),
        UniqueConstraint("request_id", name="uq_reconciliations_request"),
        Index("ix_reconciliations_org_status", "org_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_requests.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="Pending")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationLine(Base):
    __tablename__ = "reconciliation_lines"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('INTERNAL_TRANSFER', 'CONVERSION', 'EXTERNAL_EXPENSE', "
            "'LENDING_TRANSFER', 'FEE')",
            name="ck_reconciliation_lines_classification",
        ),
        CheckConstraint("amount >= 0", name="ck_reconciliation_lines_amount"),
        UniqueConstraint(
            "reconciliation_id",
            "transaction_id",
            "classification",
            name="uq_reconciliation_lines_tx_class",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliations.id", ondelete="RESTRICT"), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    tx_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    from_address: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    to_address: Mapped[bytes | None] = mapped_column(LargeBinary)
    asset_address: Mapped[bytes | None] = mapped_column(LargeBinary)
    amount: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    day: Mapped[date | None] = mapped_column(Date)
