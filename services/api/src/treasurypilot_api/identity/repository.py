from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.auth import (
    ConsumeResult,
    ConsumeStatus,
    MembershipRecord,
    ProfileRecord,
    SessionAccess,
    UserRecord,
    WalletRecord,
)
from treasurypilot_api.identity.models import (
    MagicLink,
    Membership,
    Session,
    User,
    UserStatus,
    WalletLink,
)


def _user_record(user: User) -> UserRecord:
    return UserRecord(
        id=user.id,
        email=str(user.email),
        display_name=user.display_name,
        status=user.status,
    )


class SqlAlchemyAuthRepository:
    """PostgreSQL-backed auth repository with locked consume/session transitions."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def find_active_user_by_email(self, email: str) -> UserRecord | None:
        async with self._sessions() as session:
            user = await session.scalar(
                select(User).where(User.email == email, User.status == UserStatus.ACTIVE)
            )
            return _user_record(user) if user is not None else None

    async def replace_magic_link(
        self,
        *,
        email: str,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            # A newly requested link invalidates every outstanding link for the account.
            await session.execute(
                update(MagicLink)
                .where(MagicLink.email == email, MagicLink.used_at.is_(None))
                .values(used_at=created_at)
            )
            session.add(
                MagicLink(
                    id=uuid.uuid4(),
                    email=email,
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    async def invalidate_magic_link(self, *, token_hash: bytes, invalidated_at: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(MagicLink)
                .where(MagicLink.token_hash == token_hash, MagicLink.used_at.is_(None))
                .values(used_at=invalidated_at)
            )

    async def consume_magic_link(self, *, token_hash: bytes, now: datetime) -> ConsumeResult:
        async with self._sessions() as session, session.begin():
            link = await session.scalar(
                select(MagicLink).where(MagicLink.token_hash == token_hash).with_for_update()
            )
            if link is None or not hmac.compare_digest(link.token_hash, token_hash):
                return ConsumeResult(ConsumeStatus.INVALID)
            if link.used_at is not None:
                return ConsumeResult(ConsumeStatus.INVALID)
            if now >= link.expires_at:
                return ConsumeResult(ConsumeStatus.EXPIRED)

            user = await session.scalar(
                select(User).where(User.email == link.email, User.status == UserStatus.ACTIVE)
            )
            if user is None:
                return ConsumeResult(ConsumeStatus.INVALID)
            link.used_at = now
            await session.flush()
            return ConsumeResult(ConsumeStatus.VALID, _user_record(user))

    async def create_session(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
        ip_hash: bytes,
        ua_hash: bytes,
    ) -> None:
        async with self._sessions() as session, session.begin():
            session.add(
                Session(
                    id=session_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                    last_seen_at=created_at,
                    ip_hash=ip_hash,
                    ua_hash=ua_hash,
                )
            )

    async def access_session(
        self,
        *,
        session_id: uuid.UUID,
        token_hash: bytes,
        now: datetime,
        idle_lifetime: timedelta,
    ) -> SessionAccess | None:
        async with self._sessions() as session, session.begin():
            auth_session = await session.scalar(
                select(Session).where(Session.id == session_id).with_for_update()
            )
            if auth_session is None or auth_session.revoked_at is not None:
                return None
            if not hmac.compare_digest(auth_session.token_hash, token_hash):
                return None
            if now >= auth_session.expires_at or now - auth_session.last_seen_at >= idle_lifetime:
                auth_session.revoked_at = now
                return None

            user = await session.scalar(
                select(User).where(
                    User.id == auth_session.user_id,
                    User.status == UserStatus.ACTIVE,
                )
            )
            if user is None:
                auth_session.revoked_at = now
                return None
            auth_session.last_seen_at = now
            return SessionAccess(user=_user_record(user))

    async def revoke_session(self, *, session_id: uuid.UUID, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(Session)
                .where(Session.id == session_id, Session.revoked_at.is_(None))
                .values(revoked_at=now)
            )

    async def get_profile(self, user_id: uuid.UUID) -> ProfileRecord | None:
        async with self._sessions() as session:
            user = await session.scalar(
                select(User).where(User.id == user_id, User.status == UserStatus.ACTIVE)
            )
            if user is None:
                return None
            memberships = (
                await session.scalars(
                    select(Membership)
                    .where(Membership.user_id == user_id)
                    .order_by(Membership.org_id, Membership.id)
                )
            ).all()
            wallets = (
                await session.scalars(
                    select(WalletLink)
                    .where(WalletLink.user_id == user_id, WalletLink.unlinked_at.is_(None))
                    .order_by(WalletLink.linked_at, WalletLink.id)
                )
            ).all()
            return ProfileRecord(
                user=_user_record(user),
                memberships=tuple(
                    MembershipRecord(
                        id=item.id,
                        org_id=item.org_id,
                        roles=tuple(item.roles),
                        status=item.status,
                    )
                    for item in memberships
                ),
                wallets=tuple(
                    WalletRecord(
                        address=item.address,
                        chain_family=item.chain_family,
                        is_contract=item.is_contract,
                        linked_at=item.linked_at,
                    )
                    for item in wallets
                ),
            )
