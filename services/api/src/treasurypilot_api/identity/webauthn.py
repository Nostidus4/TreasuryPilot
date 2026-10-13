"""WebAuthn ceremonies bound to the authenticated user and current session."""

from __future__ import annotations

import binascii
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.mfa import STEP_UP_LIFETIME, MfaService
from treasurypilot_api.identity.models import (
    MfaTotp,
    MfaWebAuthnChallenge,
    MfaWebAuthnCredential,
    Session,
)

CHALLENGE_LIFETIME = timedelta(minutes=5)


def _invalid() -> AuthFailure:
    return AuthFailure(
        status=403,
        code="WEBAUTHN_INVALID",
        title="WebAuthn verification failed",
        detail="The WebAuthn response is invalid, expired, or belongs to another session.",
    )


class WebAuthnMfaService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mfa: MfaService,
        *,
        rp_id: str,
        origin: str,
    ) -> None:
        parsed = urlparse(origin)
        if (
            not rp_id
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and rp_id == "localhost"))
            or (parsed.hostname != rp_id and not parsed.hostname.endswith("." + rp_id))
        ):
            raise ValueError("WebAuthn origin must be a secure origin within its RP ID")
        self._sessions = sessions
        self._mfa = mfa
        self._rp_id = rp_id
        self._origin = origin.rstrip("/")

    async def _challenge(
        self,
        db: AsyncSession,
        challenge_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        kind: str,
        now: datetime,
    ) -> MfaWebAuthnChallenge:
        row = await db.scalar(
            select(MfaWebAuthnChallenge)
            .where(
                MfaWebAuthnChallenge.id == challenge_id,
                MfaWebAuthnChallenge.user_id == user_id,
                MfaWebAuthnChallenge.session_id == session_id,
                MfaWebAuthnChallenge.kind == kind,
            )
            .with_for_update()
        )
        if row is None or row.used_at is not None or now >= row.expires_at:
            raise _invalid()
        return row

    async def _store_challenge(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        kind: str,
        challenge: bytes,
        now: datetime,
    ) -> uuid.UUID:
        # One outstanding ceremony per session; remove consumed/expired rows for
        # this user. The shared account limiter bounds active challenges in other sessions.
        await db.execute(
            delete(MfaWebAuthnChallenge).where(
                MfaWebAuthnChallenge.user_id == user_id,
                or_(
                    MfaWebAuthnChallenge.session_id == session_id,
                    MfaWebAuthnChallenge.expires_at <= now,
                    MfaWebAuthnChallenge.used_at.is_not(None),
                ),
            )
        )
        challenge_id = uuid.uuid4()
        db.add(
            MfaWebAuthnChallenge(
                id=challenge_id,
                user_id=user_id,
                session_id=session_id,
                kind=kind,
                challenge=challenge,
                expires_at=now + CHALLENGE_LIFETIME,
            )
        )
        return challenge_id

    async def begin_registration(
        self, user_id: uuid.UUID, session_id: uuid.UUID, email: str, now: datetime
    ) -> tuple[uuid.UUID, dict[str, Any]]:
        await self._mfa.limit_attempt(user_id, scope="options")
        async with self._sessions() as db:
            existing_totp = await db.scalar(
                select(MfaTotp.encrypted_secret).where(MfaTotp.user_id == user_id)
            )
            credentials = (
                await db.scalars(
                    select(MfaWebAuthnCredential).where(MfaWebAuthnCredential.user_id == user_id)
                )
            ).all()
        if existing_totp is not None or credentials:
            await self._mfa.require_fresh_step_up(user_id, session_id, now)
        challenge = secrets.token_bytes(32)
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name="TreasuryPilot",
            user_id=user_id.bytes,
            user_name=email,
            challenge=challenge,
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.REQUIRED
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=credential.credential_id)
                for credential in credentials
            ],
        )
        async with self._sessions() as db, db.begin():
            challenge_id = await self._store_challenge(
                db, user_id, session_id, "registration", challenge, now
            )
        return challenge_id, json.loads(options_to_json(options))

    async def complete_registration(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        challenge_id: uuid.UUID,
        credential: dict[str, Any],
        now: datetime,
    ) -> None:
        await self._mfa.limit_attempt(user_id)
        async with self._sessions() as db, db.begin():
            challenge = await self._challenge(
                db, challenge_id, user_id, session_id, "registration", now
            )
            session = await db.scalar(
                select(Session)
                .where(
                    Session.id == session_id,
                    Session.user_id == user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                )
                .with_for_update()
            )
            if session is None:
                raise _invalid()
            existing_totp = await db.scalar(
                select(MfaTotp.encrypted_secret).where(MfaTotp.user_id == user_id)
            )
            existing_credential = await db.scalar(
                select(MfaWebAuthnCredential.credential_id)
                .where(MfaWebAuthnCredential.user_id == user_id)
                .limit(1)
            )
            if (existing_totp is not None or existing_credential is not None) and (
                session.step_up_at is None
                or session.step_up_at > now
                or now - session.step_up_at >= STEP_UP_LIFETIME
            ):
                raise _invalid()
            try:
                verified = verify_registration_response(
                    credential=credential,
                    expected_challenge=challenge.challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origin,
                    require_user_verification=True,
                )
            except (WebAuthnException, ValueError, TypeError):
                raise _invalid() from None
            if len(verified.credential_id) > 1024:
                raise _invalid()
            existing_id = await db.scalar(
                select(MfaWebAuthnCredential.credential_id).where(
                    MfaWebAuthnCredential.credential_id == verified.credential_id
                )
            )
            if existing_id is not None:
                raise _invalid()
            db.add(
                MfaWebAuthnCredential(
                    credential_id=verified.credential_id,
                    user_id=user_id,
                    public_key=verified.credential_public_key,
                    sign_count=verified.sign_count,
                )
            )
            challenge.used_at = now

    async def begin_authentication(
        self, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime
    ) -> tuple[uuid.UUID, dict[str, Any]]:
        await self._mfa.limit_attempt(user_id, scope="options")
        async with self._sessions() as db:
            credentials = (
                await db.scalars(
                    select(MfaWebAuthnCredential).where(MfaWebAuthnCredential.user_id == user_id)
                )
            ).all()
        if not credentials:
            raise _invalid()
        challenge = secrets.token_bytes(32)
        options = generate_authentication_options(
            rp_id=self._rp_id,
            challenge=challenge,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=credential.credential_id)
                for credential in credentials
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        async with self._sessions() as db, db.begin():
            challenge_id = await self._store_challenge(
                db, user_id, session_id, "authentication", challenge, now
            )
        return challenge_id, json.loads(options_to_json(options))

    async def complete_authentication(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        challenge_id: uuid.UUID,
        assertion: dict[str, Any],
        now: datetime,
    ) -> datetime:
        await self._mfa.limit_attempt(user_id)
        try:
            credential_id = base64url_to_bytes(assertion["id"])
            user_handle = assertion["response"].get("userHandle")
            if user_handle is not None and base64url_to_bytes(user_handle) != user_id.bytes:
                raise _invalid()
        except (AttributeError, KeyError, TypeError, ValueError, binascii.Error):
            raise _invalid() from None
        async with self._sessions() as db, db.begin():
            challenge = await self._challenge(
                db, challenge_id, user_id, session_id, "authentication", now
            )
            credential = await db.scalar(
                select(MfaWebAuthnCredential)
                .where(
                    MfaWebAuthnCredential.credential_id == credential_id,
                    MfaWebAuthnCredential.user_id == user_id,
                )
                .with_for_update()
            )
            if credential is None:
                raise _invalid()
            try:
                verified = verify_authentication_response(
                    credential=assertion,
                    expected_challenge=challenge.challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origin,
                    credential_public_key=credential.public_key,
                    credential_current_sign_count=credential.sign_count,
                    require_user_verification=True,
                )
            except (WebAuthnException, ValueError, TypeError):
                raise _invalid() from None
            if verified.credential_id != credential_id:
                raise _invalid()
            session = await db.scalar(
                select(Session)
                .where(
                    Session.id == session_id,
                    Session.user_id == user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                )
                .with_for_update()
            )
            if session is None:
                raise _invalid()
            credential.sign_count = verified.new_sign_count
            session.step_up_at = now
            challenge.used_at = now
        return now + STEP_UP_LIFETIME
