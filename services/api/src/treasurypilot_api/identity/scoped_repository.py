from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class OrganizationScopedRepository(Generic[ModelT]):
    """Base queries for rows that carry both ``id`` and ``org_id`` columns."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], model: type[ModelT]) -> None:
        columns: Any = cast(Any, model).__table__.columns
        if "org_id" not in columns or "id" not in columns:
            raise TypeError("organization-scoped models must define id and org_id columns")
        self._sessions = sessions
        self._model = model

    def scoped(self, statement: Select[ModelT], organization_id: uuid.UUID) -> Select[ModelT]:
        """Add the tenant predicate before a query can execute."""
        organization_column: Any = cast(Any, self._model).org_id
        return statement.where(organization_column == organization_id)

    async def get_by_id(self, *, organization_id: uuid.UUID, record_id: uuid.UUID) -> ModelT | None:
        id_column: Any = cast(Any, self._model).id
        statement = self.scoped(
            select(self._model).where(id_column == record_id),
            organization_id,
        )
        async with self._sessions() as session:
            return cast(ModelT | None, await session.scalar(statement))

    async def list_for_organization(self, *, organization_id: uuid.UUID) -> tuple[ModelT, ...]:
        statement = self.scoped(select(self._model), organization_id)
        async with self._sessions() as session:
            rows = await session.scalars(statement)
            return tuple(rows.all())
