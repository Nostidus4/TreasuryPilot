from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.auth import UserRecord
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    OIDCIdentity,
    Organization,
    User,
    UserStatus,
)
from treasurypilot_core.ids import uuid7

# SSO group claims may grant work roles, never organization ownership, approval,
# guardian, or platform administration privileges.
OIDC_ASSIGNABLE_ROLES = frozenset({"Operator", "Finance", "Auditor"})


class OIDCIdentityRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def provision(
        self,
        *,
        issuer: str,
        subject: str,
        email: str,
        display_name: str | None,
        organization_id: uuid.UUID,
        groups: tuple[str, ...],
        group_role_map: Mapping[str, tuple[str, ...]],
    ) -> UserRecord:
        roles = sorted({role for group in groups for role in group_role_map.get(group, ())})
        if any(role not in OIDC_ASSIGNABLE_ROLES for role in roles):
            raise ValueError("OIDC identity has an invalid mapped organization role")
        if not roles:
            # A live identity with no mapped groups is deprovisioned from this
            # organization immediately; existing sessions cannot access its routes.
            async with self._sessions() as session, session.begin():
                identity = await session.scalar(
                    select(OIDCIdentity)
                    .where(OIDCIdentity.issuer == issuer, OIDCIdentity.subject == subject)
                    .with_for_update()
                )
                if identity is not None:
                    membership = await session.scalar(
                        select(Membership)
                        .where(
                            Membership.org_id == organization_id,
                            Membership.user_id == identity.user_id,
                        )
                        .with_for_update()
                    )
                    if membership is not None:
                        membership.status = MembershipStatus.SUSPENDED
            raise ValueError("OIDC identity has no allowed mapped organization role")
        async with self._sessions() as session, session.begin():
            organization = await session.scalar(
                select(Organization).where(Organization.id == organization_id)
            )
            if organization is None or organization.platform_status != "active":
                raise ValueError("OIDC organization is unavailable")
            identity = await session.scalar(
                select(OIDCIdentity)
                .where(OIDCIdentity.issuer == issuer, OIDCIdentity.subject == subject)
                .with_for_update()
            )
            user = None
            if identity is not None:
                user = await session.scalar(
                    select(User).where(User.id == identity.user_id).with_for_update()
                )
                if user is None or user.status != UserStatus.ACTIVE:
                    raise ValueError("OIDC account is disabled")
            else:
                # Linking by email is safe only because email_verified is required
                # by the ID-token verifier. Existing disabled users stay disabled.
                user = await session.scalar(
                    select(User).where(User.email == email).with_for_update()
                )
                if user is not None and user.status != UserStatus.ACTIVE:
                    raise ValueError("OIDC account is disabled")
                if user is None:
                    user = User(id=uuid7(), email=email, display_name=display_name)
                    session.add(user)
                    await session.flush()
                session.add(OIDCIdentity(issuer=issuer, subject=subject, user_id=user.id))
            membership = await session.scalar(
                select(Membership)
                .where(Membership.org_id == organization_id, Membership.user_id == user.id)
                .with_for_update()
            )
            if membership is None:
                membership = Membership(
                    id=uuid7(),
                    org_id=organization_id,
                    user_id=user.id,
                    roles=roles,
                    status=MembershipStatus.ACTIVE,
                )
                session.add(membership)
            else:
                # The provider's current group claim is authoritative for the
                # SSO-managed organization membership.
                membership.roles = roles
                membership.status = MembershipStatus.ACTIVE
            await session.flush()
            return UserRecord(user.id, str(user.email), user.display_name, user.status)
