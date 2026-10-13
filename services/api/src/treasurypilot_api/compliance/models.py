from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class ScreeningListEntry(Base):
    """A fixture screening-list entry (compliance §4). TEST DATA, not a live list."""

    __tablename__ = "screening_lists"
    __table_args__ = (
        CheckConstraint("octet_length(address) = 20", name="ck_screening_lists_address"),
        CheckConstraint("length(btrim(source_label)) > 0", name="ck_screening_lists_source_label"),
        UniqueConstraint("address", "list_name", name="uq_screening_lists_address_list"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    source_label: Mapped[str] = mapped_column(String(300), nullable=False)
    list_name: Mapped[str] = mapped_column(String(120), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
