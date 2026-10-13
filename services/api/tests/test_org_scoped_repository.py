from __future__ import annotations

import uuid
from typing import cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.identity.models import Membership
from treasurypilot_api.identity.organizations import MembershipRepository


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


def test_queries_are_always_filtered_by_the_bound_organization() -> None:
    org_id = uuid.uuid4()
    repository = MembershipRepository(cast(AsyncSession, RecordingSession()), org_id)

    compiled = repository.select().compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )

    assert f"memberships.org_id = '{org_id}'" in str(compiled)


def test_adding_a_row_from_another_organization_is_rejected() -> None:
    org_id = uuid.uuid4()
    session = RecordingSession()
    repository = MembershipRepository(cast(AsyncSession, session), org_id)
    own = Membership(org_id=org_id, user_id=uuid.uuid4(), roles=["Finance"])
    foreign = Membership(org_id=uuid.uuid4(), user_id=uuid.uuid4(), roles=["Finance"])

    repository.add(own)
    with pytest.raises(ValueError, match="different organization"):
        repository.add(foreign)

    assert session.added == [own]
