from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_core.ids import uuid7


class AiPurpose(StrEnum):
    """Mirrors `treasurypilot_worker.agent.AiTask`; services do not import each other."""

    EXTRACT = "EXTRACT"
    TERMS = "TERMS"
    ANOMALY = "ANOMALY"
    PLAN = "PLAN"
    EXPLAIN = "EXPLAIN"
    EXCEPTION_DRAFT = "EXCEPTION_DRAFT"
    COPILOT = "COPILOT"
    EVAL = "EVAL"


class AiValidationResult(StrEnum):
    OK = "OK"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    POSTCHECK_FAILED = "POSTCHECK_FAILED"
    REJECTED = "REJECTED"


ai_purpose_enum = Enum(
    AiPurpose, name="ai_purpose", values_callable=lambda values: [v.value for v in values]
)
ai_validation_result_enum = Enum(
    AiValidationResult,
    name="ai_validation_result",
    values_callable=lambda values: [v.value for v in values],
)


class AiCall(Base):
    """AI decision log (F-093), written by worker-ai. Append-only: a trigger blocks changes."""

    __tablename__ = "ai_calls"
    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="ck_ai_calls_latency_ms"),
        CheckConstraint("input_tokens >= 0", name="ck_ai_calls_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_ai_calls_output_tokens"),
        CheckConstraint("cost_usd_micros >= 0", name="ck_ai_calls_cost_usd_micros"),
        CheckConstraint(
            "validation_result IS NOT NULL OR error IS NOT NULL", name="ck_ai_calls_outcome"
        ),
        Index("ix_ai_calls_org_created", "org_id", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[AiPurpose] = mapped_column(ai_purpose_enum, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_result: Mapped[AiValidationResult | None] = mapped_column(ai_validation_result_enum)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
