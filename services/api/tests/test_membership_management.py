from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.memberships import (
    InviteEmailMismatch,
    LastAdministrator,
    LastOwner,
    SqlAlchemyMembershipRepository,
)
from treasurypilot_api.identity.models import (
    Membership,
    Organization,
    User,
    WalletLink,
    uuid7,
)

API_ROOT = Path(__file__).parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _exercise_membership_flow(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    repository = SqlAlchemyMembershipRepository(sessions)
    now = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    owner_id, admin_id, signer_id = uuid7(), uuid7(), uuid7()
    org_id = uuid7()

    try:
        async with sessions() as session, session.begin():
            for user_id, email in (
                (owner_id, "owner@example.test"),
                (admin_id, "admin@example.test"),
                (signer_id, "signer@example.test"),
            ):
                session.add(User(id=user_id, email=email, display_name=email))
            session.add(
                Organization(
                    id=org_id,
                    name="Membership integration",
                    display_tz="UTC",
                    created_by=owner_id,
                    updated_by=owner_id,
                )
            )
            session.add_all(
                [
                    Membership(
                        id=uuid7(),
                        org_id=org_id,
                        user_id=owner_id,
                        roles=["OrgAdmin", "Owner"],
                        created_by=owner_id,
                        updated_by=owner_id,
                    ),
                    Membership(
                        id=uuid7(),
                        org_id=org_id,
                        user_id=admin_id,
                        roles=["OrgAdmin"],
                        created_by=owner_id,
                        updated_by=owner_id,
                    ),
                ]
            )

        token_hash = b"m" * 32
        invitation = await repository.create_invite(
            org_id=org_id,
            email="SIGNER@example.test",
            roles=("Approver",),
            created_by=owner_id,
            token_hash=token_hash,
            now=now,
        )
        assert invitation.expires_at == now + timedelta(days=7)

        with pytest.raises(InviteEmailMismatch):
            await repository.accept_invite(
                token_hash=token_hash,
                user_id=signer_id,
                email="wrong@example.test",
                now=now,
            )

        accepted = await repository.accept_invite(
            token_hash=token_hash,
            user_id=signer_id,
            email="signer@example.test",
            now=now,
        )
        assert accepted.roles == ("Approver",)
        assert accepted.signer_roles_active is False

        listed = await repository.list_members(org_id=org_id)
        assert listed is not None
        signer = next(item for item in listed if item.user_id == signer_id)
        assert signer.signer_roles_active is False

        async with sessions() as session, session.begin():
            session.add(
                WalletLink(
                    id=uuid7(),
                    user_id=signer_id,
                    address=b"\x11" * 20,
                    linked_at=now,
                )
            )
        listed = await repository.list_members(org_id=org_id)
        assert listed is not None
        signer = next(item for item in listed if item.user_id == signer_id)
        assert signer.signer_roles_active is True

        with pytest.raises(LastOwner):
            await repository.update_member(
                org_id=org_id,
                user_id=owner_id,
                roles=("OrgAdmin",),
                updated_by=admin_id,
            )
        with pytest.raises(LastAdministrator):
            await repository.remove_member(org_id=org_id, user_id=admin_id)

        changed = await repository.update_member(
            org_id=org_id,
            user_id=admin_id,
            roles=("Finance",),
            updated_by=owner_id,
        )
        assert changed is not None and changed.roles == ("Finance",)
        assert await repository.remove_member(org_id=org_id, user_id=admin_id)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(Membership.id).where(
                        Membership.org_id == org_id, Membership.user_id == admin_id
                    )
                )
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL membership integration test",
)
def test_postgres_membership_invites_guards_and_signer_wallet_gate() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_membership_flow(database_url))
    finally:
        command.downgrade(config, "base")
