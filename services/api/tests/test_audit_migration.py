from __future__ import annotations

import asyncio
import io
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.audit import (
    ZERO_HASH,
    AuditActor,
    AuditActorType,
    AuditEntity,
    AuditHead,
    AuditHeadMissing,
    AuditLog,
    compute_hash,
    write,
)
from treasurypilot_api.audit.api import AuditFilters, AuditNotFound, SqlAlchemyAuditRepository

API_ROOT = Path(__file__).parents[1]
SYSTEM = AuditActor(AuditActorType.SYSTEM)


def alembic_config(*, database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    url = database_url or "postgresql+asyncpg://offline/offline"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_audit_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for name in (
        "CREATE TABLE audit_log",
        "CREATE TABLE audit_heads",
        "CREATE TRIGGER audit_log_no_update_or_delete",
        "CREATE TRIGGER audit_log_no_truncate",
        "CREATE TRIGGER audit_heads_no_delete",
        "CREATE TRIGGER organizations_create_audit_head",
    ):
        assert name in sql


async def _verify_chain(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:a, 'A'), (:b, 'B')"),
                {"a": org_id, "b": other_org},
            )

        # One session reused across commits: the cached head must not go stale.
        async with sessions() as session:
            for index in range(2):
                async with session.begin():
                    await write(
                        session,
                        org_id=org_id,
                        actor=SYSTEM,
                        action="test.write",
                        entity=AuditEntity("test", str(index)),
                        data={"index": index, "amount": "100"},
                    )
                if index == 0:
                    # Keep the head in this session's identity map (as code that reads it
                    # would), then let another request append before our next write.
                    async with session.begin():
                        held_head = await session.get(AuditHead, org_id)
                    assert held_head is not None
                    async with sessions() as other, other.begin():
                        await write(
                            other,
                            org_id=org_id,
                            actor=SYSTEM,
                            action="test.concurrent",
                            entity=AuditEntity("test"),
                            data={},
                        )

        async with sessions() as session:
            rows = (
                await session.scalars(
                    select(AuditLog).where(AuditLog.org_id == org_id).order_by(AuditLog.seq)
                )
            ).all()
        assert len(rows) == 3
        previous = ZERO_HASH
        for row in rows:
            assert row.prev_hash == previous  # one linear chain, no fork
            assert compute_hash(row) == row.hash  # recomputable from stored rows
            previous = row.hash

        for statement in (
            "UPDATE audit_log SET action = 'x'",
            "DELETE FROM audit_log",
            "TRUNCATE audit_log",
            "TRUNCATE audit_heads",
            f"DELETE FROM audit_heads WHERE org_id = '{org_id}'",
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))

        # An unused head may go with its organization; a missing head is an error.
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :id"), {"id": other_org}
            )
        with pytest.raises(AuditHeadMissing):
            async with sessions() as session, session.begin():
                await write(
                    session,
                    org_id=other_org,
                    actor=SYSTEM,
                    action="test.write",
                    entity=AuditEntity("test"),
                    data={},
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL audit chain test",
)
def test_audit_chain_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_verify_chain(database_url))
    finally:
        command.downgrade(config, "base")


async def _verify_detects_tamper(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyAuditRepository(sessions)
    org_id, auditor, outsider = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'A')"), {"id": org_id}
            )
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:a, 'aud@x.io'), (:b, 'out@x.io')"),
                {"a": auditor, "b": outsider},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles)"
                    " VALUES (:id, :org, :user, ARRAY['Auditor'])"
                ),
                {"id": uuid.uuid4(), "org": org_id, "user": auditor},
            )

        # An empty chain is intact.
        empty = await repository.verify(organization_id=org_id, user_id=auditor)
        assert (empty.status, empty.checked, empty.broken_at) == ("INTACT", 0, None)

        rows = []
        for index in range(3):
            async with sessions() as session, session.begin():
                rows.append(
                    await write(
                        session,
                        org_id=org_id,
                        actor=AuditActor(AuditActorType.USER, auditor),
                        action="test.write",
                        entity=AuditEntity("request", str(index)),
                        data={"amount": str(index * 100)},
                    )
                )

        intact = await repository.verify(organization_id=org_id, user_id=auditor)
        assert (intact.status, intact.checked, intact.broken_at) == ("INTACT", 3, None)

        page = await repository.list(
            organization_id=org_id,
            user_id=auditor,
            filters=AuditFilters(entity_type="request", entity_id="1"),
            cursor=None,
            limit=10,
        )
        assert [row.seq for row in page.items] == [rows[1].seq]
        first = await repository.list(
            organization_id=org_id,
            user_id=auditor,
            filters=AuditFilters(),
            cursor=None,
            limit=2,
        )
        assert [row.seq for row in first.items] == [rows[0].seq, rows[1].seq]
        assert first.next_cursor == rows[1].seq

        with pytest.raises(AuditNotFound):
            await repository.verify(organization_id=org_id, user_id=outsider)

        # Manual tamper: edit the middle record's amount behind the append-only trigger.
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_or_delete")
            )
            await connection.execute(
                text("""UPDATE audit_log SET data = '{"amount": "999"}' WHERE seq = :seq"""),
                {"seq": rows[1].seq},
            )
            await connection.execute(
                text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_or_delete")
            )
        broken = await repository.verify(organization_id=org_id, user_id=auditor)
        assert (broken.status, broken.checked, broken.broken_at) == ("BROKEN", 2, rows[1].seq)

        # Deleting the tail leaves the head pointing past the stored chain.
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_or_delete")
            )
            await connection.execute(
                text('UPDATE audit_log SET data = \'{"amount": "100"}\' WHERE seq = :seq'),
                {"seq": rows[1].seq},
            )
            await connection.execute(
                text("DELETE FROM audit_log WHERE seq = :seq"), {"seq": rows[2].seq}
            )
            await connection.execute(
                text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_or_delete")
            )
        truncated = await repository.verify(organization_id=org_id, user_id=auditor)
        assert (truncated.status, truncated.broken_at) == ("BROKEN", rows[2].seq)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL audit verification test",
)
def test_audit_verify_reports_first_tampered_record_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_verify_detects_tamper(database_url))
    finally:
        command.downgrade(config, "base")
