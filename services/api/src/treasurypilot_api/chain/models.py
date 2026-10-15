from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class TokenMovement(Base):
    __tablename__ = "token_movements"
    __table_args__ = (
        CheckConstraint("octet_length(wallet) = 20", name="ck_token_movements_wallet"),
        CheckConstraint("octet_length(counterparty) = 20", name="ck_token_movements_counterparty"),
        CheckConstraint("amount >= 0", name="ck_token_movements_amount"),
        CheckConstraint("direction IN ('IN', 'OUT')", name="ck_token_movements_direction"),
        CheckConstraint(
            "\"class\" IN ('AGENT', 'INTERNAL_REFILL', 'INFLOW', 'UNEXPECTED_OUTFLOW', 'LENDING')",
            name="ck_token_movements_class",
        ),
        CheckConstraint(
            "(acknowledged_by IS NULL AND acknowledged_at IS NULL "
            "AND acknowledgement_reason IS NULL) OR "
            "(acknowledged_at IS NOT NULL AND acknowledgement_reason IS NOT NULL "
            "AND length(btrim(acknowledgement_reason)) > 0)",
            name="ck_token_movements_acknowledgement",
        ),
        UniqueConstraint("event_id", name="uq_token_movements_event"),
        Index("ix_token_movements_treasury_created", "treasury_id", "created_at"),
        Index(
            "ix_token_movements_unacknowledged_outflow",
            "treasury_id",
            "created_at",
            postgresql_where=text("\"class\" = 'UNEXPECTED_OUTFLOW' AND acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observed_events.id", ondelete="RESTRICT"), nullable=False
    )
    wallet: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    counterparty: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    amount: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    classification: Mapped[str] = mapped_column("class", String(32), nullable=False)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operations.id", ondelete="RESTRICT")
    )
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledgement_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChainSafetySignal(Base):
    __tablename__ = "chain_safety_signals"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('PRE_STEP_REVALIDATION', 'CIRCUIT_BREAKER')",
            name="ck_chain_safety_signals_type",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_chain_safety_signals_payload_object"
        ),
        UniqueConstraint(
            "token_movement_id", "signal_type", name="uq_chain_safety_signals_movement_type"
        ),
        Index(
            "ix_chain_safety_signals_pending",
            "treasury_id",
            "created_at",
            postgresql_where=text("invalidated_at IS NULL AND consumed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    observed_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observed_events.id", ondelete="RESTRICT"), nullable=False
    )
    token_movement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_movements.id", ondelete="RESTRICT"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
