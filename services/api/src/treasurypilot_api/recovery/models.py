from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_review_items_version"),
        CheckConstraint(
            "status IN ('Open', 'Resolved', 'Dismissed')", name="ck_review_items_status"
        ),
        Index(
            "uq_review_items_open_request_type",
            "request_id",
            "type",
            unique=True,
            postgresql_where=text("status = 'Open'"),
        ),
        Index("ix_review_items_org_status_due", "org_id", "status", "sla_due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_requests.id"), nullable=False
    )
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    completed_steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    assigned_roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="Open")
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_resolved: Mapped[bool] = mapped_column(nullable=False, default=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}
