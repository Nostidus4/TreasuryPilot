from __future__ import annotations

import uuid
from typing import Generic, TypeVar, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class OrganizationScopedRepository(Generic[ModelT]):
    """Base queries for rows that carry both ``id`` and ``org_id`` columns."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], model: type[ModelT]) -> None:
        columns = model.__table__.columns  # type: ignore[attr-defined]
        if "org_id" not in columns or "id" not in columns:
            raise TypeError("organization-scoped models must define id and org_id columns")
        self._sessions = sessions
        self._model = model

    def scoped(self, statement: Select[tuple[ModelT]], organization_id: uuid.UUID):
        """Add the tenant predicate before a query can execute."""
        return statement.where(self._model.org_id == organization_id)

    async def get_by_id(self, *, organization_id: uuid.UUID, record_id: uuid.UUID) -> ModelT | None:
        statement = self.scoped(
            select(self._model).where(self._model.id == record_id),
            organization_id,
        )
        async with self._sessions() as session:
            return cast(ModelT | None, await session.scalar(statement))

    async def list_for_organization(self, *, organization_id: uuid.UUID) -> tuple[ModelT, ...]:
        statement = self.scoped(select(self._model), organization_id)
        async with self._sessions() as session:
            rows = await session.scalars(statement)
            return tuple(rows.all())
