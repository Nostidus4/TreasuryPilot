"""Membership and role checks for org-scoped routes (FR-008, FR-011, BR-093).

Every route under ``/v1/orgs/{organization_id}`` depends on ``require_member``
or ``require_role``. Non-members get 404 so an organization's existence never
leaks; members without the role get 403.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Protocol, cast

from fastapi import Depends, Request

from treasurypilot_api.identity.api import _authenticated, _service
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess
from treasurypilot_api.identity.models import OrganizationRole

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class MembershipLookup(Protocol):
    async def member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        """Roles of the active membership, or ``None`` when the user is not a member."""
        ...


@dataclass(frozen=True, slots=True)
class MemberAccess:
    access: SessionAccess
    organization_id: uuid.UUID
    roles: frozenset[str]

    @property
    def user_id(self) -> uuid.UUID:
        return self.access.user.id


def organization_not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="ORG_NOT_FOUND",
        title="Organization not found",
        detail="The organization does not exist or is not available to this user.",
    )


def maker_checker_conflict() -> AuthFailure:
    return AuthFailure(
        status=409,
        code="MAKER_CHECKER",
        title="Maker-checker violation",
        detail="The creator or last editor of a request cannot approve it.",
    )


def _lookup(request: Request) -> MembershipLookup:
    lookup = getattr(request.app.state, "organization_repository", None)
    if lookup is None:
        raise AuthFailure(
            status=503,
            code="ORG_UNAVAILABLE",
            title="Organization service unavailable",
            detail="Organization storage is not configured.",
        )
    return cast(MembershipLookup, lookup)


async def require_member(organization_id: uuid.UUID, request: Request) -> MemberAccess:
    access = await _authenticated(
        request, require_csrf=request.method not in _SAFE_METHODS, allow_scoped=True
    )
    if access.organization_scope_id is not None and access.organization_scope_id != organization_id:
        raise organization_not_found()
    roles = await _lookup(request).member_roles(
        organization_id=organization_id, user_id=access.user.id
    )
    if roles is None:
        raise organization_not_found()
    return MemberAccess(access=access, organization_id=organization_id, roles=roles)


def require_role(
    *roles: OrganizationRole, step_up: bool = False
) -> Callable[..., Awaitable[MemberAccess]]:
    """Require one of ``roles``; with ``step_up`` also a fresh second-factor check."""

    allowed = frozenset(role.value for role in roles)

    async def dependency(member: Annotated[MemberAccess, Depends(require_member)]) -> MemberAccess:
        if not member.roles & allowed:
            raise AuthFailure(
                status=403,
                code="FORBIDDEN",
                title="Forbidden",
                detail="Your organization role does not allow this action.",
            )
        return member

    if not step_up:
        return dependency

    # A default, not Annotated: ``dependency`` is local, so a string annotation cannot resolve it.
    async def with_step_up(
        request: Request,
        member: MemberAccess = Depends(dependency),  # noqa: B008
    ) -> MemberAccess:
        _service(request).require_step_up(member.access)
        return member

    return with_step_up
