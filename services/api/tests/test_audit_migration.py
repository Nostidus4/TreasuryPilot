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
