from __future__ import annotations

import uuid
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

TenantRow = TypeVar("TenantRow")


class OrgScopedRepository(Generic[TenantRow]):
    """Repository bound to one organization: every query filters by ``org_id`` (BR-093).

    Subclasses set ``model`` to a tenant-owned table and build queries from
    ``self.select()`` instead of ``sqlalchemy.select`` so the filter cannot be forgotten.
    """

    model: ClassVar[type[Any]]

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def select(self) -> Select[TenantRow]:
        return select(self.model).where(self.model.org_id == self.organization_id)

    async def get(self, row_id: uuid.UUID) -> TenantRow | None:
        row: TenantRow | None = await self.session.scalar(
            self.select().where(self.model.id == row_id)
        )
        return row

    def add(self, row: TenantRow) -> None:
        if getattr(row, "org_id", None) != self.organization_id:
            raise ValueError("row belongs to a different organization")
        self.session.add(row)
