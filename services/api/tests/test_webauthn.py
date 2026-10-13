from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
import uuid
from datetime import UTC, datetime, timedelta

import cbor2
import pytest
from alembic import command
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from services.api.tests.test_auth_repository import _alembic_config
from sqlalchemy import func, select

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.mfa import MfaService
from treasurypilot_api.identity.models import (
    MfaWebAuthnChallenge,
    MfaWebAuthnCredential,
    Session,
    User,
)
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.webauthn import WebAuthnMfaService


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client_data(kind: str, challenge: bytes, origin: str) -> bytes:
    return json.dumps(
        {"type": kind, "challenge": _b64(challenge), "origin": origin},
        separators=(",", ":"),
    ).encode()


class _Authenticator:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)

    def registration(self, challenge: bytes, *, origin: str = "https://app.example.test") -> dict:
        public = self.key.public_key().public_numbers()
        cose_key = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32), -3: public.y.to_bytes(32)}
        )
        auth_data = (
            hashlib.sha256(b"app.example.test").digest()
            + bytes([0x45])  # user present, user verified, attested credential data
            + struct.pack(">I", 0)
            + bytes(16)  # AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + cose_key
        )
        attestation = cbor2.dumps({"fmt": "none", "authData": auth_data, "attStmt": {}})
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "response": {
                "attestationObject": _b64(attestation),
                "clientDataJSON": _b64(_client_data("webauthn.create", challenge, origin)),
            },
            "clientExtensionResults": {},
        }

    def assertion(
        self,
        challenge: bytes,
        user_id: uuid.UUID,
        *,
        rp_id: str = "app.example.test",
        origin: str = "https://app.example.test",
        sign_count: int = 1,
    ) -> dict:
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([0x05])  # user present and verified
            + struct.pack(">I", sign_count)
        )
        client_data = _client_data("webauthn.get", challenge, origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "response": {
                "authenticatorData": _b64(auth_data),
                "clientDataJSON": _b64(client_data),
                "signature": _b64(signature),
                "userHandle": _b64(user_id.bytes),
            },
            "clientExtensionResults": {},
        }


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def test_webauthn_rejects_untrusted_origin_and_rp_config() -> None:
    with pytest.raises(ValueError):
        WebAuthnMfaService(None, None, rp_id="example.test", origin="https://evil.test")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        WebAuthnMfaService(None, None, rp_id="app.example.test", origin="http://app.example.test")  # type: ignore[arg-type]


async def _exercise_webauthn(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    clock = _Clock()
    mfa = MfaService(sessions, b"webauthn-integration-secret-32-bytes!", MemoryRateLimiter(clock))
    service = WebAuthnMfaService(
        sessions, mfa, rp_id="app.example.test", origin="https://app.example.test"
    )
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    authenticator = _Authenticator()
    try:
        async with sessions() as db, db.begin():
            db.add(User(id=user_id, email=f"{user_id}@example.test"))
            await db.flush()
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

        old_id, _ = await service.begin_registration(
            user_id, session_id, "person@example.test", clock.value
        )
        registration_id, options = await service.begin_registration(
            user_id, session_id, "person@example.test", clock.value
        )
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(MfaWebAuthnChallenge)) == 1
            challenge = await db.scalar(
                select(MfaWebAuthnChallenge).where(MfaWebAuthnChallenge.id == registration_id)
            )
            assert challenge is not None
            assert _b64(challenge.challenge) == options["challenge"]
        valid_registration = authenticator.registration(challenge.challenge)
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id, session_id, old_id, valid_registration, clock.value
            )
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id, uuid.uuid4(), registration_id, valid_registration, clock.value
            )
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id,
                session_id,
                registration_id,
                authenticator.registration(challenge.challenge, origin="https://evil.test"),
                clock.value,
            )
        clock.advance(timedelta(minutes=6))
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id, session_id, registration_id, valid_registration, clock.value
            )
        clock.advance(timedelta(minutes=10))
        registration_id, options = await service.begin_registration(
            user_id, session_id, "person@example.test", clock.value
        )
        renewed_challenge = base64.urlsafe_b64decode(
            options["challenge"] + "=" * (-len(options["challenge"]) % 4)
        )
        valid_registration = authenticator.registration(renewed_challenge)
        revoked_registration_session = uuid.uuid4()
        async with sessions() as db, db.begin():
            db.add(
                Session(
                    id=revoked_registration_session,
                    user_id=user_id,
                    token_hash=os.urandom(32),
                    created_at=clock.value,
                    expires_at=clock.value + timedelta(hours=12),
                    last_seen_at=clock.value,
                    ip_hash=os.urandom(32),
                    ua_hash=os.urandom(32),
                )
            )
        revoked_registration_id, revoked_registration_options = await service.begin_registration(
            user_id, revoked_registration_session, "person@example.test", clock.value
        )
        revoked_registration_challenge = base64.urlsafe_b64decode(
            revoked_registration_options["challenge"]
            + "=" * (-len(revoked_registration_options["challenge"]) % 4)
        )
        async with sessions() as db, db.begin():
            session = await db.get(Session, revoked_registration_session)
            assert session is not None
            session.revoked_at = clock.value
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id,
                revoked_registration_session,
                revoked_registration_id,
                authenticator.registration(revoked_registration_challenge),
                clock.value,
            )
        await service.complete_registration(
            user_id, session_id, registration_id, valid_registration, clock.value
        )
        async with sessions() as db:
            stored = await db.scalar(
                select(MfaWebAuthnCredential).where(
                    MfaWebAuthnCredential.credential_id == authenticator.credential_id
                )
            )
            assert stored is not None and stored.user_id == user_id
        with pytest.raises(AuthFailure, match="MFA_STEP_UP_REQUIRED"):
            await mfa.begin_enrollment(user_id, session_id, clock.value, "TreasuryPilot")
        clock.advance(timedelta(minutes=16))
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_registration(
                user_id, session_id, registration_id, valid_registration, clock.value
            )

        authentication_id, auth_options = await service.begin_authentication(
            user_id, session_id, clock.value
        )
        auth_challenge = base64.urlsafe_b64decode(
            auth_options["challenge"] + "=" * (-len(auth_options["challenge"]) % 4)
        )
        valid_assertion = authenticator.assertion(auth_challenge, user_id)
        wrong_credential = dict(valid_assertion)
        wrong_credential["id"] = _b64(os.urandom(32))
        wrong_credential["rawId"] = wrong_credential["id"]
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_authentication(
                user_id, session_id, authentication_id, wrong_credential, clock.value
            )
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_authentication(
                user_id,
                session_id,
                authentication_id,
                authenticator.assertion(auth_challenge, user_id, rp_id="evil.test"),
                clock.value,
            )
        expires_at = await service.complete_authentication(
            user_id, session_id, authentication_id, valid_assertion, clock.value
        )
        assert expires_at == clock.value + timedelta(minutes=5)
        await mfa.require_fresh_step_up(user_id, session_id, clock.value)
        totp_secret, _ = await mfa.begin_enrollment(
            user_id, session_id, clock.value, "TreasuryPilot"
        )
        assert totp_secret
        with pytest.raises(AuthFailure, match="MFA_ENROLLMENT_EXPIRED"):
            await mfa.confirm_enrollment(user_id, uuid.uuid4(), "000000", clock.value)
        clock.advance(timedelta(minutes=16))
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_authentication(
                user_id, session_id, authentication_id, valid_assertion, clock.value
            )
        revoked_id, revoked_options = await service.begin_authentication(
            user_id, session_id, clock.value
        )
        revoked_challenge = base64.urlsafe_b64decode(
            revoked_options["challenge"] + "=" * (-len(revoked_options["challenge"]) % 4)
        )
        async with sessions() as db, db.begin():
            session = await db.get(Session, session_id)
            assert session is not None
            session.revoked_at = clock.value
        with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
            await service.complete_authentication(
                user_id,
                session_id,
                revoked_id,
                authenticator.assertion(revoked_challenge, user_id, sign_count=2),
                clock.value,
            )
    finally:
        await engine.dispose()


async def _exercise_malformed_payloads(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    clock = _Clock()
    mfa = MfaService(sessions, b"webauthn-malformed-secret-32-bytes!!", MemoryRateLimiter(clock))
    service = WebAuthnMfaService(
        sessions, mfa, rp_id="app.example.test", origin="https://app.example.test"
    )
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with sessions() as db, db.begin():
            db.add(User(id=user_id, email=f"{user_id}@example.test"))
            await db.flush()
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
        registration_id, _ = await service.begin_registration(
            user_id, session_id, "person@example.test", clock.value
        )
        async with sessions() as db, db.begin():
            db.add(
                MfaWebAuthnCredential(
                    credential_id=os.urandom(32), user_id=user_id, public_key=b"x", sign_count=0
                )
            )
        authentication_id, _ = await service.begin_authentication(user_id, session_id, clock.value)
        for payload in ({}, {"id": "AA", "rawId": "AA", "response": {}, "type": "x"}):
            with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
                await service.complete_registration(
                    user_id, session_id, registration_id, payload, clock.value
                )
        for payload in (
            {},
            {"id": "AA", "response": "x"},
            {"id": "AA", "rawId": "AA", "response": {}, "type": "x"},
        ):
            with pytest.raises(AuthFailure, match="WEBAUTHN_INVALID"):
                await service.complete_authentication(
                    user_id, session_id, authentication_id, payload, clock.value
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL WebAuthn integration",
)
def test_postgres_webauthn_binding_origin_rp_replay_and_revocation() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_webauthn(database_url))
        asyncio.run(_exercise_malformed_payloads(database_url))
    finally:
        command.downgrade(config, "base")
