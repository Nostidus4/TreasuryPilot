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
from treasurypilot_api.compliance import retention
from treasurypilot_api.compliance.models import DeletionReceipt, SubjectDeletionControl
from treasurypilot_api.compliance.retention import (
    MAX_AUTH_RETENTION_DAYS,
    MAX_INVITE_RETENTION_DAYS,
    auth_receipt_hash,
    configure_auth_policy,
    configure_policy,
    invite_receipt_hash,
    request_subject_deletion,
    run_retention,
    set_subject_legal_hold,
    siwe_nonce_receipt_hash,
    subject_receipt_hash,
)
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.models import (
    Invite,
    MagicLink,
    MfaFactor,
    MfaRecoveryCode,
    OIDCIdentity,
    Organization,
    Session,
    SiweNonce,
    User,
    WalletLink,
)
from treasurypilot_api.notifications.models import (
    NotificationChannel,
    NotificationEmailPreference,
    NotificationPreference,
    TelegramLinkCode,
)

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
    assert "CREATE TABLE auth_retention_policies" in sql
    assert "CREATE TABLE subject_deletion_controls" in sql
    assert "CREATE TABLE deletion_receipts" in sql
    assert "record_type IN ('invite', 'session', 'magic_link', 'subject', 'siwe_nonce')" in sql
    assert "DROP TABLE auth_retention_policies" in sql
    assert "DROP TABLE deletion_receipts" in sql
    assert "DROP TABLE retention_policies" in sql
    assert "DROP COLUMN siwe_nonce_retention_days" in sql
    record_id = uuid.uuid4()
    assert invite_receipt_hash(record_id) == invite_receipt_hash(record_id)
    assert len(invite_receipt_hash(record_id)) == 32
    assert invite_receipt_hash(record_id) != invite_receipt_hash(uuid.uuid4())
    assert auth_receipt_hash("session", record_id) == auth_receipt_hash("session", record_id)
    assert len(auth_receipt_hash("magic_link", record_id)) == 32
    assert auth_receipt_hash("session", record_id) != auth_receipt_hash("magic_link", record_id)
    assert auth_receipt_hash("session", record_id) != invite_receipt_hash(record_id)
    assert siwe_nonce_receipt_hash("generated-challenge") == siwe_nonce_receipt_hash(
        "generated-challenge"
    )
    assert len(siwe_nonce_receipt_hash("generated-challenge")) == 32
    assert siwe_nonce_receipt_hash("generated-challenge") != siwe_nonce_receipt_hash(
        "different-challenge"
    )
    with pytest.raises(ValueError, match="nonce"):
        siwe_nonce_receipt_hash("")
    assert len(subject_receipt_hash(record_id)) == 32
    assert subject_receipt_hash(record_id) != auth_receipt_hash("session", record_id)
    with pytest.raises(ValueError, match="record_type"):
        auth_receipt_hash("invite", record_id)


@pytest.mark.parametrize("days", [-1, MAX_INVITE_RETENTION_DAYS + 1, 1_000_000])
def test_configure_policy_rejects_out_of_range_days(days: int) -> None:
    with pytest.raises(ValueError, match="invite_retention_days"):
        asyncio.run(
            configure_policy(
                None,  # type: ignore[arg-type]
                org_id=uuid.uuid4(),
                invite_retention_days=days,
                legal_hold=False,
            )
        )


@pytest.mark.parametrize(
    ("session_days", "magic_link_days", "siwe_days"),
    [
        (-1, 10, None),
        (10, MAX_AUTH_RETENTION_DAYS + 1, None),
        (1_000_000, None, None),
        (None, None, MAX_AUTH_RETENTION_DAYS + 1),
    ],
)
def test_configure_auth_policy_rejects_out_of_range_days(
    session_days: int | None, magic_link_days: int | None, siwe_days: int | None
) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        asyncio.run(
            configure_auth_policy(
                None,  # type: ignore[arg-type]
                session_retention_days=session_days,
                magic_link_retention_days=magic_link_days,
                siwe_nonce_retention_days=siwe_days,
                legal_hold=False,
            )
        )


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def scalars(self, _statement: object) -> list[uuid.UUID]:
        return list(_ORGS)

    async def get(self, *_args: object, **_kwargs: object) -> None:
        return None


_ORGS = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]


def test_one_failing_organization_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[uuid.UUID] = []

    async def fake_run_org(
        _sessions: object, org_id: uuid.UUID, **_kwargs: object
    ) -> tuple[int, int]:
        seen.append(org_id)
        if org_id == _ORGS[0]:
            raise OverflowError("boom")
        return 2, 1

    monkeypatch.setattr(retention, "_run_org", fake_run_org)
    monkeypatch.setattr(retention, "_run_auth", _no_auth_records)
    monkeypatch.setattr(retention, "_run_subject_requests", _no_subject_requests)
    result = asyncio.run(
        run_retention(lambda: _FakeSession(), now=datetime.now(UTC), dry_run=False)  # type: ignore[arg-type]
    )
    assert seen == _ORGS
    assert (result.examined, result.deleted, result.failed) == (4, 2, 1)


async def _no_auth_records(*_args: object, **_kwargs: object) -> tuple[int, int]:
    return 0, 0


async def _no_subject_requests(*_args: object, **_kwargs: object) -> tuple[int, int, int]:
    return 0, 0, 0


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
    old_id, young_id, audited_id, entity_cased_id, actor_cased_id, data_cased_id = (
        uuid.uuid4() for _ in range(6)
    )
    user_id, old_session_id, young_session_id, old_link_id, young_link_id = (
        uuid.uuid4() for _ in range(5)
    )
    used_nonce = "old-used-generated-siwe-challenge"
    expired_nonce = "old-expired-generated-siwe-challenge"
    boundary_nonce = "boundary-generated-siwe-challenge"
    young_nonce = "young-generated-siwe-challenge"
    old_email = "expired-person@example.test"
    try:
        async with sessions() as session, session.begin():
            session.add(Organization(id=org_id, name="Retention integration test"))
            session.add(User(id=user_id, email="auth-user@example.test"))
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
                    Invite(
                        id=entity_cased_id,
                        org_id=org_id,
                        email="Cased-Entity@Example.test",
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=40),
                        expires_at=now - timedelta(days=30),
                    ),
                    Invite(
                        id=actor_cased_id,
                        org_id=org_id,
                        email="Cased-Actor@Example.test",
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=40),
                        expires_at=now - timedelta(days=30),
                    ),
                    Invite(
                        id=data_cased_id,
                        org_id=org_id,
                        email="Cased-Data@Example.test",
                        roles=["Operator"],
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=40),
                        expires_at=now - timedelta(days=30),
                    ),
                    Session(
                        id=old_session_id,
                        user_id=user_id,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=60),
                        expires_at=now - timedelta(days=30),
                        last_seen_at=now - timedelta(days=31),
                        ip_hash=os.urandom(32),
                        ua_hash=os.urandom(32),
                    ),
                    Session(
                        id=young_session_id,
                        user_id=user_id,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=2),
                        expires_at=now + timedelta(days=30),
                        last_seen_at=now - timedelta(days=1),
                        ip_hash=os.urandom(32),
                        ua_hash=os.urandom(32),
                    ),
                    MagicLink(
                        id=old_link_id,
                        email="old-link-person@example.test",
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=60),
                        expires_at=now - timedelta(days=30),
                    ),
                    MagicLink(
                        id=young_link_id,
                        email="young-link-person@example.test",
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=2),
                        expires_at=now + timedelta(days=4),
                    ),
                    SiweNonce(
                        nonce=used_nonce,
                        user_id=user_id,
                        created_at=now - timedelta(days=60),
                        expires_at=now - timedelta(days=20),
                        used_at=now - timedelta(days=30),
                    ),
                    SiweNonce(
                        nonce=expired_nonce,
                        user_id=user_id,
                        created_at=now - timedelta(days=60),
                        expires_at=now - timedelta(days=30),
                    ),
                    SiweNonce(
                        nonce=boundary_nonce,
                        user_id=user_id,
                        created_at=now - timedelta(days=60),
                        expires_at=now - timedelta(days=7, minutes=2),
                    ),
                    SiweNonce(
                        nonce=young_nonce,
                        user_id=user_id,
                        created_at=now - timedelta(days=1),
                        expires_at=now + timedelta(minutes=9),
                    ),
                ]
            )
            await configure_policy(session, org_id=org_id, invite_retention_days=7, legal_hold=True)
            await configure_auth_policy(
                session,
                session_retention_days=7,
                magic_link_retention_days=7,
                siwe_nonce_retention_days=7,
                legal_hold=True,
            )
            await session.flush()
            await write(
                session,
                org_id=org_id,
                actor=AuditActor(actor_type="SYSTEM"),
                action="invite.created",
                entity=AuditEntity(entity_type="invite", entity_id=audited_id),
                data={},
            )
            # One upper-cased audit reference per guard branch; invite emails are mixed-case.
            await write(
                session,
                org_id=org_id,
                actor=AuditActor(actor_type="SYSTEM"),
                action="invite.revoked",
                entity=AuditEntity(entity_type="invite", entity_id="CASED-ENTITY@EXAMPLE.TEST"),
                data={},
            )
            await write(
                session,
                org_id=org_id,
                actor=AuditActor(actor_type="USER", actor_id="CASED-ACTOR@EXAMPLE.TEST"),
                action="invite.accepted",
                entity=AuditEntity(entity_type="other"),
                data={},
            )
            await write(
                session,
                org_id=org_id,
                actor=AuditActor(actor_type="SYSTEM"),
                action="invite.revoked",
                entity=AuditEntity(entity_type="other"),
                data={"email": "CASED-DATA@EXAMPLE.TEST"},
            )

        held = await run_retention(sessions, now=now, dry_run=False)
        assert held.deleted == 0
        async with sessions() as session:
            assert await session.get(Session, old_session_id) is not None
            assert await session.get(MagicLink, old_link_id) is not None
            assert await session.get(SiweNonce, used_nonce) is not None
            assert await session.get(SiweNonce, expired_nonce) is not None
        async with sessions() as session, session.begin():
            await configure_policy(
                session, org_id=org_id, invite_retention_days=7, legal_hold=False
            )
            await configure_auth_policy(
                session,
                session_retention_days=7,
                magic_link_retention_days=7,
                siwe_nonce_retention_days=7,
                legal_hold=False,
            )

        preview = await run_retention(sessions, now=now)
        assert preview.examined == 5 and preview.failed == 0 and preview.deleted == 0
        result = await run_retention(sessions, now=now, dry_run=False)
        assert result.examined == 5 and result.deleted == 5
        assert (await run_retention(sessions, now=now, dry_run=False)).deleted == 0
        async with sessions() as session:
            assert await session.get(Invite, old_id) is None
            assert await session.get(Invite, young_id) is not None
            assert await session.get(Invite, audited_id) is not None
            assert await session.get(Invite, entity_cased_id) is not None
            assert await session.get(Invite, actor_cased_id) is not None
            assert await session.get(Invite, data_cased_id) is not None
            assert await session.get(Session, old_session_id) is None
            assert await session.get(Session, young_session_id) is not None
            assert await session.get(MagicLink, old_link_id) is None
            assert await session.get(MagicLink, young_link_id) is not None
            assert await session.get(SiweNonce, used_nonce) is None
            assert await session.get(SiweNonce, expired_nonce) is None
            assert await session.get(SiweNonce, boundary_nonce) is not None
            assert await session.get(SiweNonce, young_nonce) is not None
            receipts = list(await session.scalars(select(DeletionReceipt)))
            assert len(receipts) == 5
            receipt_by_type = {receipt.record_type: receipt for receipt in receipts}
            assert receipt_by_type["invite"].record_hash == invite_receipt_hash(old_id)
            assert receipt_by_type["session"].record_hash == auth_receipt_hash(
                "session", old_session_id
            )
            assert receipt_by_type["magic_link"].record_hash == auth_receipt_hash(
                "magic_link", old_link_id
            )
            siwe_receipt_hashes = {
                receipt.record_hash for receipt in receipts if receipt.record_type == "siwe_nonce"
            }
            assert siwe_receipt_hashes == {
                siwe_nonce_receipt_hash(used_nonce),
                siwe_nonce_receipt_hash(expired_nonce),
            }
            receipt_data = str([receipt.__dict__ for receipt in receipts])
            assert old_email not in receipt_data
            assert "old-link-person@example.test" not in receipt_data
            assert "auth-user@example.test" not in receipt_data
            assert used_nonce not in receipt_data
            assert expired_nonce not in receipt_data
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL subject-erasure test",
)
def test_subject_deletion_honors_holds_and_retains_only_hash_receipts() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_subject_deletion_case(database_url))
    finally:
        command.downgrade(config, "base")


async def _subject_deletion_case(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    now = datetime.now(UTC)
    subject_id, held_id = uuid.uuid4(), uuid.uuid4()
    subject_email = "subject-to-delete@example.test"
    held_email = "held-subject@example.test"
    subject_session_id, held_session_id = uuid.uuid4(), uuid.uuid4()
    subject_magic_id, held_magic_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with sessions() as session, session.begin():
            session.add_all(
                [
                    User(id=subject_id, email=subject_email, display_name="Delete me"),
                    User(id=held_id, email=held_email, display_name="Do not delete yet"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Session(
                        id=subject_session_id,
                        user_id=subject_id,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=3),
                        expires_at=now + timedelta(days=3),
                        last_seen_at=now,
                        ip_hash=os.urandom(32),
                        ua_hash=os.urandom(32),
                    ),
                    Session(
                        id=held_session_id,
                        user_id=held_id,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=3),
                        expires_at=now + timedelta(days=3),
                        last_seen_at=now,
                        ip_hash=os.urandom(32),
                        ua_hash=os.urandom(32),
                    ),
                    MagicLink(
                        id=subject_magic_id,
                        email=subject_email,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=3),
                        expires_at=now + timedelta(days=3),
                    ),
                    MagicLink(
                        id=held_magic_id,
                        email=held_email,
                        token_hash=os.urandom(32),
                        created_at=now - timedelta(days=3),
                        expires_at=now + timedelta(days=3),
                    ),
                    MfaFactor(
                        user_id=subject_id,
                        kind="totp",
                        label="Personal authenticator",
                        secret="tpenc:v1:encrypted-secret",
                        confirmed_at=now,
                    ),
                    MfaRecoveryCode(user_id=subject_id, code_hash=os.urandom(32)),
                    OIDCIdentity(
                        user_id=subject_id,
                        issuer="https://issuer.example.test",
                        subject="personal-subject-identifier",
                    ),
                    SiweNonce(
                        user_id=subject_id,
                        nonce="subject-erasure-nonce",
                        expires_at=now + timedelta(minutes=10),
                    ),
                    WalletLink(user_id=subject_id, address=os.urandom(20)),
                    NotificationEmailPreference(user_id=subject_id),
                    NotificationPreference(user_id=subject_id),
                    NotificationChannel(
                        user_id=subject_id,
                        kind="TELEGRAM",
                        target="tpenc:v1:encrypted-target",
                        target_hash=os.urandom(32),
                    ),
                    TelegramLinkCode(
                        user_id=subject_id,
                        code_hash=os.urandom(32),
                        expires_at=now + timedelta(minutes=10),
                    ),
                ]
            )
            await session.flush()
            await configure_auth_policy(
                session,
                session_retention_days=None,
                magic_link_retention_days=None,
                siwe_nonce_retention_days=None,
                legal_hold=True,
            )
            await set_subject_legal_hold(session, user_id=held_id, legal_hold=True, updated_at=now)
            await request_subject_deletion(session, user_id=subject_id, requested_at=now)
            await request_subject_deletion(session, user_id=held_id, requested_at=now)

        # The deployment-wide auth hold also freezes a subject request's auth purge.
        held_result = await run_retention(sessions, now=now, dry_run=False)
        assert held_result.deleted == 0 and held_result.failed == 0
        async with sessions() as session:
            subject = await session.get(User, subject_id)
            assert subject is not None and subject.email == subject_email
            assert subject.status == "disabled"

        async with sessions() as session, session.begin():
            await configure_auth_policy(
                session,
                session_retention_days=None,
                magic_link_retention_days=None,
                siwe_nonce_retention_days=None,
                legal_hold=False,
            )
        preview = await run_retention(sessions, now=now, dry_run=True)
        assert preview.examined == 1 and preview.deleted == 0
        result = await run_retention(sessions, now=now, dry_run=False)
        assert result.examined == 1 and result.deleted == 1 and result.failed == 0

        async with sessions() as session:
            subject = await session.get(User, subject_id)
            assert subject is not None
            assert subject.email == f"deleted-{subject_id.hex}@privacy.invalid"
            assert subject.display_name is None and subject.status == "disabled"
            assert await session.get(Session, subject_session_id) is None
            assert await session.get(MagicLink, subject_magic_id) is None
            assert await session.get(SiweNonce, "subject-erasure-nonce") is None
            assert await session.get(Session, held_session_id) is not None
            assert await session.get(MagicLink, held_magic_id) is not None
            assert await session.get(SubjectDeletionControl, subject_id) is None
            assert (await session.get(SubjectDeletionControl, held_id)).legal_hold is True
            assert (
                await session.scalar(select(MfaFactor.id).where(MfaFactor.user_id == subject_id))
                is None
            )
            assert (
                await session.scalar(
                    select(MfaRecoveryCode.id).where(MfaRecoveryCode.user_id == subject_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(OIDCIdentity.subject).where(OIDCIdentity.user_id == subject_id)
                )
                is None
            )
            assert await session.scalar(select(SiweNonce.nonce)) is None
            assert (
                await session.scalar(select(WalletLink.id).where(WalletLink.user_id == subject_id))
                is None
            )
            assert await session.get(NotificationEmailPreference, subject_id) is None
            assert await session.get(NotificationPreference, subject_id) is None
            assert (
                await session.scalar(
                    select(NotificationChannel.id).where(NotificationChannel.user_id == subject_id)
                )
                is None
            )
            assert await session.scalar(select(TelegramLinkCode.code_hash)) is None
            receipts = list(await session.scalars(select(DeletionReceipt)))
            assert {receipt.record_type for receipt in receipts} == {
                "subject",
                "session",
                "magic_link",
                "siwe_nonce",
            }
            receipt_by_type = {receipt.record_type: receipt for receipt in receipts}
            assert receipt_by_type["subject"].record_hash == subject_receipt_hash(subject_id)
            assert receipt_by_type["session"].record_hash == auth_receipt_hash(
                "session", subject_session_id
            )
            assert receipt_by_type["magic_link"].record_hash == auth_receipt_hash(
                "magic_link", subject_magic_id
            )
            assert receipt_by_type["siwe_nonce"].record_hash == siwe_nonce_receipt_hash(
                "subject-erasure-nonce"
            )
            receipt_data = str([receipt.__dict__ for receipt in receipts])
            assert subject_email not in receipt_data
            assert held_email not in receipt_data
            assert "Delete me" not in receipt_data
            assert "subject-erasure-nonce" not in receipt_data

        async with sessions() as session, session.begin():
            await set_subject_legal_hold(session, user_id=held_id, legal_hold=False, updated_at=now)
        released = await run_retention(sessions, now=now, dry_run=False)
        assert released.examined == 1 and released.deleted == 1 and released.failed == 0
        async with sessions() as session:
            held_user = await session.get(User, held_id)
            assert held_user is not None and held_user.status == "disabled"
            assert held_user.email == f"deleted-{held_id.hex}@privacy.invalid"
        async with sessions() as session, session.begin():
            await set_subject_legal_hold(session, user_id=held_id, legal_hold=True, updated_at=now)
            await set_subject_legal_hold(session, user_id=held_id, legal_hold=False, updated_at=now)
        async with sessions() as session:
            assert await session.get(SubjectDeletionControl, held_id) is None
    finally:
        await engine.dispose()
