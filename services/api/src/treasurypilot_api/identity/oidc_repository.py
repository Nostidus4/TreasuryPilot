from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from treasurypilot_api.identity.oidc import OIDCFailure
from treasurypilot_api.identity.role_grants import (
    initialize_legacy_role_sources,
    recompute_membership_roles,
)
from treasurypilot_core.ids import uuid7

# SSO group claims may grant work roles, never organization ownership, approval,
# guardian, or platform administration privileges.
OIDC_ASSIGNABLE_ROLES = frozenset({"Operator", "Finance", "Auditor"})
# Membership rule: SSO manages only OIDC_ASSIGNABLE_ROLES. Any other role an existing
# member holds (Owner, Approver, ...) is preserved, so SSO can never demote or suspend
# an owner. SSO never re-activates a suspended membership: login is rejected instead.


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
        groups: tuple[str, ...] | None,
        group_role_map: Mapping[str, tuple[str, ...]],
    ) -> UserRecord:
        # groups is None when the provider sent no groups claim: keep existing roles.
        roles = sorted({role for group in groups or () for role in group_role_map.get(group, ())})
        if any(role not in OIDC_ASSIGNABLE_ROLES for role in roles):
            raise ValueError("OIDC identity has an invalid mapped organization role")
        if groups is not None and not roles:
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
                        initialize_legacy_role_sources(membership, oidc_identity_linked=True)
                        membership.oidc_roles = []
                        recompute_membership_roles(membership)
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
            identity_was_existing = identity is not None
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
                try:
                    if user is None:
                        user = User(id=uuid7(), email=email, display_name=display_name)
                        session.add(user)
                        await session.flush()
                    elif await session.scalar(
                        select(OIDCIdentity.subject).where(
                            OIDCIdentity.user_id == user.id, OIDCIdentity.issuer == issuer
                        )
                    ):
                        raise ValueError("OIDC account is already linked to another identity")
                    session.add(OIDCIdentity(issuer=issuer, subject=subject, user_id=user.id))
                    await session.flush()
                except IntegrityError:
                    raise OIDCFailure("OIDC identity could not be linked") from None
            membership = await session.scalar(
                select(Membership)
                .where(Membership.org_id == organization_id, Membership.user_id == user.id)
                .with_for_update()
            )
            if membership is None:
                if not roles:
                    raise ValueError("OIDC identity has no allowed mapped organization role")
                membership = Membership(
                    id=uuid7(),
                    org_id=organization_id,
                    user_id=user.id,
                    roles=roles,
                    oidc_roles=roles,
                    role_sources_initialized=True,
                    status=MembershipStatus.ACTIVE,
                )
                session.add(membership)
            elif membership.status != MembershipStatus.ACTIVE:
                raise ValueError("OIDC membership is not active")
            elif groups is not None:
                # The provider's group claim is authoritative for SSO-managed roles only.
                initialize_legacy_role_sources(
                    membership, oidc_identity_linked=identity_was_existing
                )
                membership.oidc_roles = roles
                recompute_membership_roles(membership)
            await session.flush()
            return UserRecord(user.id, str(user.email), user.display_name, user.status)
