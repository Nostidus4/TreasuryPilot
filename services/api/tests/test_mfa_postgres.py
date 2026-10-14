from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.identity.auth import SESSION_IDLE_LIFETIME
from treasurypilot_api.identity.mfa import FactorRecord, hash_recovery_code
from treasurypilot_api.identity.mfa_repository import SqlAlchemyMfaRepository
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _factor(user_id: uuid.UUID, **overrides: object) -> FactorRecord:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "kind": "webauthn",
        "label": "key",
        "secret": None,
        "credential_id": b"cred-1",
        "public_key": b"\x01" * 64,
        "sign_count": 0,
        "last_counter": None,
        "created_at": NOW,
        "confirmed_at": NOW,
    }
    return FactorRecord(**{**values, **overrides})  # type: ignore[arg-type]


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        mfa = SqlAlchemyMfaRepository(sessions)
        auth = SqlAlchemyAuthRepository(sessions)
        user_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:i, 'mfa@example.com')"),
                {"i": user_id},
            )

        # The step-up time written by MFA is what the auth repository reports on the session.
        session_id = uuid.uuid4()
        await auth.create_session(
            session_id=session_id,
            user_id=user_id,
            token_hash=b"\x02" * 32,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=12),
            ip_hash=b"\x03" * 32,
            ua_hash=b"\x04" * 32,
        )

        async def access():  # type: ignore[no-untyped-def]
            return await auth.access_session(
                session_id=session_id,
                token_hash=b"\x02" * 32,
                now=NOW + timedelta(minutes=1),
                idle_lifetime=SESSION_IDLE_LIFETIME,
            )

        assert (await access()).step_up_at is None  # type: ignore[union-attr]
        await mfa.mark_step_up(session_id=session_id, now=NOW)
        assert (await access()).step_up_at == NOW  # type: ignore[union-attr]

        # A security key credential can be registered once, across all users.
        webauthn = _factor(user_id)
        assert await mfa.add_factor(webauthn)
        assert not await mfa.add_factor(_factor(user_id))
        assert not await mfa.advance_sign_count(factor_id=webauthn.id, sign_count=0)
        assert await mfa.advance_sign_count(factor_id=webauthn.id, sign_count=5)
        assert not await mfa.advance_sign_count(factor_id=webauthn.id, sign_count=5)

        # A TOTP time step is accepted once.
        totp = _factor(
            user_id,
            kind="totp",
            secret="envelope",
            credential_id=None,
            public_key=None,
            confirmed_at=None,
        )
        assert await mfa.add_factor(totp)
        assert await mfa.advance_totp_counter(factor_id=totp.id, counter=100)
        assert not await mfa.advance_totp_counter(factor_id=totp.id, counter=100)
        assert not await mfa.advance_totp_counter(factor_id=totp.id, counter=99)
        await mfa.confirm_factor(factor_id=totp.id, now=NOW)
        listed = {f.id: f for f in await mfa.list_factors(user_id)}
        assert listed[totp.id].confirmed_at == NOW
        assert listed[totp.id].last_counter == 100
        assert listed[webauthn.id].sign_count == 5

        # Recovery codes are single use and replaced as a set.
        codes = [hash_recovery_code(f"code-{i}", b"secret") for i in range(3)]
        await mfa.replace_recovery_codes(user_id=user_id, code_hashes=codes, now=NOW)
        assert await mfa.count_recovery_codes(user_id) == 3
        assert await mfa.consume_recovery_code(user_id=user_id, code_hash=codes[0], now=NOW)
        assert not await mfa.consume_recovery_code(user_id=user_id, code_hash=codes[0], now=NOW)
        assert not await mfa.consume_recovery_code(
            user_id=uuid.uuid4(), code_hash=codes[1], now=NOW
        )
        assert await mfa.count_recovery_codes(user_id) == 2
        await mfa.replace_recovery_codes(user_id=user_id, code_hashes=codes[:1], now=NOW)
        assert await mfa.consume_recovery_code(user_id=user_id, code_hash=codes[0], now=NOW)

        assert await mfa.delete_factor(user_id=user_id, factor_id=totp.id)
        assert not await mfa.delete_factor(user_id=user_id, factor_id=totp.id)

        # Only unconfirmed factors older than the cutoff are dropped.
        pending = _factor(
            user_id,
            kind="totp",
            secret="envelope",
            credential_id=None,
            public_key=None,
            confirmed_at=None,
        )
        assert await mfa.add_factor(pending)
        await mfa.delete_pending_factors(user_id=user_id, before=NOW)
        await mfa.delete_pending_factors(user_id=uuid.uuid4(), before=NOW + timedelta(hours=1))
        assert pending.id in {f.id for f in await mfa.list_factors(user_id)}
        await mfa.delete_pending_factors(user_id=user_id, before=NOW + timedelta(hours=1))
        assert pending.id not in {f.id for f in await mfa.list_factors(user_id)}
        assert webauthn.id in {f.id for f in await mfa.list_factors(user_id)}
    finally:
        await engine.dispose()


def test_mfa_repository_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
