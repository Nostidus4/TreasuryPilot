from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Declarative base for API-owned persistence models."""


def create_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create the API engine and transaction-scoped asynchronous session factory."""

    # Looked up at call time so OpenTelemetry's wrapper (installed in create_app) traces it.
    engine = sqlalchemy_asyncio.create_async_engine(database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class AuditMixin:
    """Who/when columns shared by mutable configuration tables."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class VersionedMixin(AuditMixin):
    """Audit columns plus a ``version`` column used for optimistic locking."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]


class RowVersionedMixin(AuditMixin):
    """Optimistic locking for tables whose ``version`` column is a domain label."""

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.row_version}  # type: ignore[attr-defined]
