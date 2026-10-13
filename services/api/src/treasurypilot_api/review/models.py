from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class ReviewType(StrEnum):
    POLICY_BLOCK = "POLICY_BLOCK"
    NEEDS_AUTHORITY = "NEEDS_AUTHORITY"
    FEE_APPROVAL = "FEE_APPROVAL"
    UNCERTAIN_TX = "UNCERTAIN_TX"
    DISCREPANCY = "DISCREPANCY"
    AI_REJECTED = "AI_REJECTED"
    INFRA = "INFRA"
    UNEXPECTED_OUTFLOW = "UNEXPECTED_OUTFLOW"


class ReviewStatus(StrEnum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    DISMISSED = "Dismissed"


class ReviewAction(StrEnum):
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    CANCEL = "CANCEL"
    EDIT_REQUEST = "EDIT_REQUEST"
    GRANT_EXCEPTION = "GRANT_EXCEPTION"
    ACCEPT_FEE = "ACCEPT_FEE"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    MARK_MATCHED = "MARK_MATCHED"


_REVIEW_TYPES = ", ".join(f"'{item.value}'" for item in ReviewType)
_REVIEW_STATUSES = ", ".join(f"'{item.value}'" for item in ReviewStatus)
_REVIEW_ACTIONS = ", ".join(f"'{item.value}'" for item in ReviewAction)


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint(f"type IN ({_REVIEW_TYPES})", name="ck_review_items_type"),
        CheckConstraint(f"status IN ({_REVIEW_STATUSES})", name="ck_review_items_status"),
        CheckConstraint(
            f"resolution IS NULL OR resolution IN ({_REVIEW_ACTIONS})",
            name="ck_review_items_resolution",
        ),
        CheckConstraint("length(btrim(primary_code)) > 0", name="ck_review_items_primary_code"),
        CheckConstraint("cardinality(reason_codes) > 0", name="ck_review_items_reason_codes"),
        CheckConstraint(
            "array_position(reason_codes, NULL) IS NULL",
            name="ck_review_items_reason_codes_no_null",
        ),
        CheckConstraint(
            "jsonb_typeof(completed_steps) = 'array'", name="ck_review_items_completed_steps"
        ),
        CheckConstraint("version > 0", name="ck_review_items_version"),
        CheckConstraint(
            "(status = 'Open' AND resolved_by IS NULL AND resolved_at IS NULL AND resolution IS NULL) OR "
            "(status <> 'Open' AND resolved_at IS NOT NULL AND resolution IS NOT NULL)",
            name="ck_review_items_resolution_state",
        ),
        ForeignKeyConstraint(
            ["request_id", "treasury_id"],
            ["payment_requests.id", "payment_requests.treasury_id"],
            name="fk_review_items_request_treasury",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_review_items_treasury_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="RESTRICT"),
        UniqueConstraint("id", "org_id", name="uq_review_items_id_org"),
        Index(
            "uq_review_items_open_request_type",
            "request_id",
            "type",
            unique=True,
            postgresql_where=text("status = 'Open'"),
        ),
        Index(
            "ix_review_items_org_status_role_sla", "org_id", "status", "assigned_role", "sla_due_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    completed_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    assigned_role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ReviewStatus.OPEN.value)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
