from __future__ import annotations

import asyncio
import base64
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from services.api.tests.test_auth import MutableClock, make_harness
from services.api.tests.test_auth_repository import _alembic_config

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.mfa import MfaService, matching_counter, totp_at
from treasurypilot_api.identity.models import Session, User
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter


def test_totp_matches_rfc6238_sha1_and_rejects_replay_or_bad_format() -> None:
    secret = b"12345678901234567890"
    instant = datetime.fromtimestamp(59, UTC)
    assert totp_at(secret, 1) == "287082"
    assert matching_counter(secret, "287082", instant, -1) == 1
    assert matching_counter(secret, "287082", instant, 1) is None
    assert matching_counter(secret, "２８７０８２", instant, -1) is None
    assert matching_counter(secret, "28708", instant, -1) is None


class _MfaStub(MfaService):
    async def begin_enrollment(
        self, user_id: uuid.UUID, now: datetime, issuer: str
    ) -> tuple[str, str]:
        return "SECRET", "otpauth://totp/test"


def test_mfa_enrollment_requires_session_and_csrf() -> None:
    with make_harness() as harness:
        harness.client.app.state.mfa_service = _MfaStub.__new__(_MfaStub)
        no_session = harness.client.post("/v1/me/mfa/totp/enrollment")
        assert no_session.status_code in (401, 403)
        harness.login()
        no_csrf = harness.client.post("/v1/me/mfa/totp/enrollment")
        assert no_csrf.status_code == 403
        csrf = harness.client.cookies.get("tp_csrf")
        assert csrf is not None
        enrolled = harness.client.post("/v1/me/mfa/totp/enrollment", headers={"X-CSRF-Token": csrf})
        assert enrolled.status_code == 200
        assert enrolled.headers["cache-control"] == "no-store"
        assert enrolled.json()["secret"] == "SECRET"


async def _exercise_mfa(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    clock = MutableClock()
    service = MfaService(
        sessions,
        b"integration-mfa-secret-value-32-bytes!!",
        MemoryRateLimiter(clock),
    )
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    try:
        async with sessions() as db, db.begin():
            db.add(User(id=user_id, email=f"{user_id}@example.test"))
            db.add(
                Session(
                    id=session_id,
                    user_id=user_id,
                    token_hash=os.urandom(32),
                    created_at=clock.value,
                    expires_at=clock.value + timedelta(hours=12),
                    last_seen_at=clock.value,
                    ip_hash=os.urandom(32),
                    ua_hash=os.urandom(32),
                )
            )
        with pytest.raises(AuthFailure, match="MFA_STEP_UP_REQUIRED"):
            await service.require_fresh_step_up(user_id, session_id, clock.value)
        secret_text, uri = await service.begin_enrollment(user_id, clock.value, "TreasuryPilot")
        assert secret_text in uri
        secret = base64.b32decode(secret_text + "=" * (-len(secret_text) % 8))
        code = totp_at(secret, int(clock.value.timestamp()) // 30)
        recovery_codes = await service.confirm_enrollment(user_id, code, clock.value)
        assert len(recovery_codes) == 10
        with pytest.raises(AuthFailure, match="MFA_CODE_INVALID"):
            await service.verify_step_up(user_id, session_id, code, clock.value)
        clock.advance(timedelta(seconds=30))
        next_code = totp_at(secret, int(clock.value.timestamp()) // 30)
        await service.verify_step_up(user_id, session_id, next_code, clock.value)
        await service.require_fresh_step_up(user_id, session_id, clock.value)
        clock.advance(timedelta(minutes=5))
        with pytest.raises(AuthFailure, match="MFA_STEP_UP_REQUIRED"):
            await service.require_fresh_step_up(user_id, session_id, clock.value)
        await service.verify_step_up(user_id, session_id, recovery_codes[0], clock.value)
        with pytest.raises(AuthFailure, match="MFA_CODE_INVALID"):
            await service.verify_step_up(user_id, session_id, recovery_codes[0], clock.value)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL MFA integration",
)
def test_postgres_enrollment_replay_recovery_and_step_up() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_mfa(database_url))
    finally:
        command.downgrade(config, "base")
