from __future__ import annotations

import asyncio
import io
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from treasurypilot_api.audit.writer import AuditActor, AuditEntity, write
from treasurypilot_api.compliance.models import DeletionReceipt
from treasurypilot_api.compliance.retention import (
    configure_policy,
    invite_receipt_hash,
    run_retention,
)
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.models import Invite, Organization

API_ROOT = Path(__file__).parents[1]


def _config(database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        (database_url or "postgresql+asyncpg://offline/offline").replace("%", "%%"),
    )
    return config


def test_retention_migration_offline_and_hash_has_no_email() -> None:
    output = io.StringIO()
    config = _config()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE retention_policies" in sql
    assert "CREATE TABLE deletion_receipts" in sql
    assert "DROP TABLE deletion_receipts" in sql
    assert "DROP TABLE retention_policies" in sql
    record_id = uuid.uuid4()
    assert invite_receipt_hash(record_id) == invite_receipt_hash(record_id)
    assert len(invite_receipt_hash(record_id)) == 32
    assert invite_receipt_hash(record_id) != invite_receipt_hash(uuid.uuid4())


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL retention integration test",
)
def test_retention_deletion_and_legal_hold_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_integration_case(database_url))
    finally:
        command.downgrade(config, "base")


async def _integration_case(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    now = datetime.now(UTC)
    org_id = uuid.uuid4()
    old_id, young_id, audited_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    old_email = "expired-person@example.test"
    try:
        async with sessions() as session, session.begin():
            session.add(Organization(id=org_id, name="Retention integration test"))
            await session.flush()
            session.add_all(
                [
                    Invite(
                        id=old_id,
                        org_id=org_id,
                        email=old_email,
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=40),
                        expires_at=now - timedelta(days=30),
                    ),
                    Invite(
                        id=young_id,
                        org_id=org_id,
                        email="new-person@example.test",
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=3),
                        expires_at=now + timedelta(days=4),
                    ),
                    Invite(
                        id=audited_id,
                        org_id=org_id,
                        email="audited-person@example.test",
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=40),
                        expires_at=now - timedelta(days=30),
                    ),
                ]
            )
            await configure_policy(session, org_id=org_id, invite_retention_days=7, legal_hold=True)
            await session.flush()
            await write(
                session,
                org_id=org_id,
                actor=AuditActor(actor_type="SYSTEM"),
                action="invite.created",
                entity=AuditEntity(entity_type="invite", entity_id=audited_id),
                data={},
            )

        held = await run_retention(sessions, now=now, dry_run=False)
        assert held.deleted == 0
        async with sessions() as session, session.begin():
            await configure_policy(
                session, org_id=org_id, invite_retention_days=7, legal_hold=False
            )

        preview = await run_retention(sessions, now=now)
        assert preview.examined == 1 and preview.deleted == 0
        result = await run_retention(sessions, now=now, dry_run=False)
        assert result.examined == 1 and result.deleted == 1
        assert (await run_retention(sessions, now=now, dry_run=False)).deleted == 0
        async with sessions() as session:
            assert await session.get(Invite, old_id) is None
            assert await session.get(Invite, young_id) is not None
            assert await session.get(Invite, audited_id) is not None
            receipts = list(await session.scalars(select(DeletionReceipt)))
            assert len(receipts) == 1
            assert receipts[0].record_hash == invite_receipt_hash(old_id)
            assert old_email not in str(receipts[0].__dict__)
    finally:
        await engine.dispose()
