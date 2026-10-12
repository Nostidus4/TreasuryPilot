from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from treasurypilot_api.identity.api import _authenticated
from treasurypilot_api.identity.auth import AuthFailure


@dataclass(frozen=True, slots=True)
class MemberContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    roles: frozenset[str]


def _organization_id(request: Request) -> uuid.UUID:
    for key in ("organization_id", "org_id", "orgId", "o"):
        value = request.path_params.get(key)
        if value is not None:
            try:
                return uuid.UUID(str(value))
            except ValueError:
                break
    raise AuthFailure(
        status=404,
        code="ORG_NOT_FOUND",
        title="Organization not found",
        detail="The organization does not exist or is not available to this user.",
    )


def _not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="ORG_NOT_FOUND",
        title="Organization not found",
        detail="The organization does not exist or is not available to this user.",
    )


def _forbidden() -> AuthFailure:
    return AuthFailure(
        status=403,
        code="FORBIDDEN",
        title="Forbidden",
        detail="An organization role with permission for this action is required.",
    )


async def require_member(request: Request) -> MemberContext:
    """Authenticate and hide organization resources from non-members."""
    organization_id = _organization_id(request)
    access = await _authenticated(
        request,
        require_csrf=request.method.upper() not in {"GET", "HEAD", "OPTIONS"},
    )
    repository = getattr(request.app.state, "organization_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="AUTH_UNAVAILABLE",
            title="Organization service unavailable",
            detail="Organization storage is not configured.",
        )
    roles = await repository.get_member_roles(
        organization_id=organization_id,
        user_id=access.user.id,
    )
    if roles is None:
        raise _not_found()
    return MemberContext(organization_id, access.user.id, frozenset(roles))


def require_role(*roles: str) -> Callable[..., Awaitable[MemberContext]]:
    """Build a dependency that permits only members holding one of ``roles``."""
    allowed = frozenset(roles)
    if not allowed:
        raise ValueError("at least one role is required")

    async def dependency(
        member: MemberContext = Depends(require_member),  # noqa: B008
    ) -> MemberContext:
        if member.roles.isdisjoint(allowed):
            raise _forbidden()
        return member

    return dependency
