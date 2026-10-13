from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import defer

from treasurypilot_api.identity.scoped_repository import OrganizationScopedRepository
from treasurypilot_api.treasury.models import Treasury


class _ScalarRows:
    def all(self) -> Sequence[object]:
        return ()


class _CapturingSession:
    def __init__(self, statements: list[Any]) -> None:
        self.statements = statements

    async def __aenter__(self) -> _CapturingSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def scalar(self, statement: Any) -> None:
        self.statements.append(statement)
        return None

    async def scalars(self, statement: Any) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows()


class _CapturingSessionFactory:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def __call__(self) -> _CapturingSession:
        return _CapturingSession(self.statements)


def test_organization_scoped_repository_always_filters_by_org_id() -> None:
    session_factory = _CapturingSessionFactory()
    repository = OrganizationScopedRepository(session_factory, Treasury)
    organization_id = uuid.uuid4()
    record_id = uuid.uuid4()

    import asyncio

    asyncio.run(repository.get_by_id(organization_id=organization_id, record_id=record_id))
    asyncio.run(repository.list_for_organization(organization_id=organization_id))

    assert len(session_factory.statements) == 2
    get_sql = str(session_factory.statements[0].compile(dialect=postgresql.dialect()))
    list_sql = str(session_factory.statements[1].compile(dialect=postgresql.dialect()))
    assert "treasuries.org_id" in get_sql
    assert "treasuries.id" in get_sql
    assert "treasuries.org_id" in list_sql
    assert (
        organization_id
        in session_factory.statements[0].compile(dialect=postgresql.dialect()).params.values()
    )
    assert (
        organization_id
        in session_factory.statements[1].compile(dialect=postgresql.dialect()).params.values()
    )


def test_organization_scoped_repository_never_lazy_loads_relationships() -> None:
    session_factory = _CapturingSessionFactory()
    repository = OrganizationScopedRepository(session_factory, Treasury)
    eager = defer(Treasury.module_address)

    import asyncio

    asyncio.run(
        repository.get_by_id(organization_id=uuid.uuid4(), record_id=uuid.uuid4(), options=(eager,))
    )

    options = session_factory.statements[0]._with_options
    assert options[0] is eager
    assert options[-1].strategy == (("lazy", "raise"),)
