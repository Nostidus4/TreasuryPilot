from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.auth import UserRecord, normalize_email
from treasurypilot_api.identity.models import (
    Membership,
    Organization,
    SAMLIdentity,
    SAMLLoginRequest,
    SAMLReplayID,
    User,
    UserStatus,
)


class SAMLIdentityError(ValueError):
    """A SAML assertion is valid but cannot be mapped to an active tenant member."""


def hash_relay_state(relay_state: str) -> bytes:
    return hashlib.sha256(relay_state.encode("ascii")).digest()


def hash_browser_nonce(browser_nonce: str) -> bytes:
    return hashlib.sha256(browser_nonce.encode("ascii")).digest()


class SAMLIdentityRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_request(
        self,
        *,
        request_id: str,
        relay_state: str,
        browser_nonce: str,
        organization_id: uuid.UUID,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        if not request_id or len(request_id) > 255 or expires_at <= now:
            raise SAMLIdentityError("invalid SAML request")
        async with self._sessions() as session, session.begin():
            organization = await session.scalar(
                select(Organization).where(
                    Organization.id == organization_id,
                    Organization.platform_status == "active",
                )
            )
            if organization is None:
                raise SAMLIdentityError("SAML organization is unavailable")
            await session.execute(
                delete(SAMLLoginRequest).where(SAMLLoginRequest.expires_at <= now)
            )
            session.add(
                SAMLLoginRequest(
                    request_id=request_id,
                    org_id=organization_id,
                    relay_state_hash=hash_relay_state(relay_state),
                    browser_nonce_hash=hash_browser_nonce(browser_nonce),
                    created_at=now,
                    expires_at=expires_at,
                )
            )

    async def find_pending_request(
        self, *, relay_state: str, browser_nonce: str, now: datetime
    ) -> tuple[str, uuid.UUID] | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SAMLLoginRequest).where(
                    SAMLLoginRequest.relay_state_hash == hash_relay_state(relay_state),
                    SAMLLoginRequest.browser_nonce_hash == hash_browser_nonce(browser_nonce),
                    SAMLLoginRequest.consumed_at.is_(None),
                    SAMLLoginRequest.expires_at > now,
                )
            )
            if row is None:
                return None
            return row.request_id, row.org_id

    async def complete_login(
        self,
        *,
        request_id: str,
        relay_state: str,
        browser_nonce: str,
        organization_id: uuid.UUID,
        issuer: str,
        subject: str,
        email: str,
        response_id: str,
        assertion_id: str,
        assertion_expires_at: datetime,
        now: datetime,
    ) -> UserRecord:
        normalized_email = normalize_email(email)
        if (
            not request_id
            or not issuer
            or len(issuer) > 500
            or not subject
            or len(subject) > 255
            or not response_id
            or not assertion_id
            or len(response_id) > 255
            or len(assertion_id) > 255
            or assertion_expires_at <= now
        ):
            raise SAMLIdentityError("invalid SAML identity")

        response_key = f"response:{response_id}"
        assertion_key = f"assertion:{assertion_id}"
        async with self._sessions() as session, session.begin():
            request = await session.scalar(
                select(SAMLLoginRequest)
                .where(
                    SAMLLoginRequest.request_id == request_id,
                    SAMLLoginRequest.org_id == organization_id,
                    SAMLLoginRequest.relay_state_hash == hash_relay_state(relay_state),
                    SAMLLoginRequest.browser_nonce_hash == hash_browser_nonce(browser_nonce),
                )
                .with_for_update()
            )
            if request is None or request.consumed_at is not None or request.expires_at <= now:
                raise SAMLIdentityError("SAML login request is invalid or already used")

            await session.execute(delete(SAMLReplayID).where(SAMLReplayID.expires_at <= now))
            replayed = await session.scalar(
                select(SAMLReplayID.identifier).where(
                    SAMLReplayID.identifier.in_((response_key, assertion_key))
                )
            )
            if replayed is not None:
                raise SAMLIdentityError("SAML response was already used")

            organization = await session.scalar(
                select(Organization).where(
                    Organization.id == organization_id,
                    Organization.platform_status == "active",
                )
            )
            if organization is None:
                raise SAMLIdentityError("SAML organization is unavailable")

            identity = await session.scalar(
                select(SAMLIdentity)
                .where(
                    SAMLIdentity.org_id == organization_id,
                    SAMLIdentity.issuer == issuer,
                    SAMLIdentity.subject == subject,
                )
                .with_for_update()
            )
            if identity is None:
                matches = (
                    await session.scalars(
                        select(User)
                        .join(Membership, Membership.user_id == User.id)
                        .where(
                            Membership.org_id == organization_id,
                            Membership.status == "active",
                            User.status == UserStatus.ACTIVE,
                            User.email == normalized_email,
                        )
                        .with_for_update()
                        .limit(2)
                    )
                ).all()
                if len(matches) != 1:
                    raise SAMLIdentityError(
                        "SAML account does not match one active organization member"
                    )
                user = matches[0]
                identity = SAMLIdentity(
                    org_id=organization_id,
                    issuer=issuer,
                    subject=subject,
                    user_id=user.id,
                )
                session.add(identity)
            else:
                mapped_user = await session.scalar(
                    select(User)
                    .join(Membership, Membership.user_id == User.id)
                    .where(
                        User.id == identity.user_id,
                        User.status == UserStatus.ACTIVE,
                        User.email == normalized_email,
                        Membership.org_id == organization_id,
                        Membership.status == "active",
                    )
                    .with_for_update()
                )
                if mapped_user is None:
                    raise SAMLIdentityError(
                        "SAML identity no longer matches an active organization member"
                    )
                user = mapped_user

            request.consumed_at = now
            session.add_all(
                (
                    SAMLReplayID(
                        identifier=response_key,
                        org_id=organization_id,
                        created_at=now,
                        expires_at=assertion_expires_at,
                    ),
                    SAMLReplayID(
                        identifier=assertion_key,
                        org_id=organization_id,
                        created_at=now,
                        expires_at=assertion_expires_at,
                    ),
                )
            )
            try:
                await session.flush()
            except IntegrityError:
                raise SAMLIdentityError("SAML identity or response was already used") from None
            return UserRecord(user.id, str(user.email), user.display_name, user.status)
