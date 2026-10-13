from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastapi import Depends, Request

from treasurypilot_api.identity.api import _authenticated
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole

if TYPE_CHECKING:
    from treasurypilot_api.identity.organizations import OrganizationRepository


@dataclass(frozen=True, slots=True)
class MemberContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    roles: frozenset[str]
    signer_roles_active: bool = False

    def has_any(self, *roles: OrganizationRole) -> bool:
        signer_roles = {
            OrganizationRole.OWNER,
            OrganizationRole.APPROVER,
            OrganizationRole.GUARDIAN,
        }
        return any(
            role.value in self.roles and (role not in signer_roles or self.signer_roles_active)
            for role in roles
        )


def not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="ORG_NOT_FOUND",
        title="Organization not found",
        detail="The organization does not exist or is not available to this user.",
    )


def forbidden() -> AuthFailure:
    return AuthFailure(
        status=403,
        code="FORBIDDEN",
        title="Forbidden",
        detail="An organization role with permission for this action is required.",
    )


def maker_checker_conflict() -> AuthFailure:
    return AuthFailure(
        status=409,
        code="MAKER_CHECKER",
        title="Maker-checker violation",
        detail="The creator or last editor of a request cannot approve it.",
    )


def organization_repository(request: Request) -> OrganizationRepository:
    repository = getattr(request.app.state, "organization_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="ORG_UNAVAILABLE",
            title="Organization service unavailable",
            detail="Organization storage is not configured.",
        )
    return cast("OrganizationRepository", repository)


async def require_member(organization_id: uuid.UUID, request: Request) -> MemberContext:
    """Authenticate and hide organization resources from non-members.

    ``organization_id`` is typed so FastAPI rejects malformed ids with 422 before
    this runs, and the caller is authenticated before membership is looked up.
    """
    access = await _authenticated(
        request,
        require_csrf=request.method.upper() not in {"GET", "HEAD", "OPTIONS"},
    )
    roles = await organization_repository(request).get_member_roles(
        organization_id=organization_id,
        user_id=access.user.id,
    )
    if roles is None:
        raise not_found()
    repository = organization_repository(request)
    signer_wallet_check = getattr(repository, "has_active_signer_wallet", None)
    signer_roles_active = (
        await signer_wallet_check(organization_id=organization_id, user_id=access.user.id)
        if signer_wallet_check is not None
        else False
    )
    return MemberContext(
        organization_id,
        access.user.id,
        frozenset(roles),
        signer_roles_active=signer_roles_active,
    )


def require_role(*roles: OrganizationRole) -> Callable[..., Awaitable[MemberContext]]:
    """Build a dependency that permits only members holding one of ``roles``."""
    if not roles:
        raise ValueError("at least one role is required")

    async def dependency(
        member: MemberContext = Depends(require_member),  # noqa: B008
    ) -> MemberContext:
        if not member.has_any(*roles):
            raise forbidden()
        return member

    return dependency
