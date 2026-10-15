from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel, _authenticated, _require_unscoped
from treasurypilot_api.identity.auth import AuthFailure, normalize_email
from treasurypilot_api.identity.models import (
    Invite,
    Membership,
    MembershipStatus,
    OIDCIdentity,
    Organization,
    OrganizationRole,
    User,
    WalletLink,
    uuid7,
)
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.identity.role_grants import initialize_legacy_role_sources

INVITE_LIFETIME = timedelta(days=7)
_SIMPLE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SIGNER_ROLES = {
    OrganizationRole.OWNER.value,
    OrganizationRole.APPROVER.value,
    OrganizationRole.GUARDIAN.value,
}


@dataclass(frozen=True, slots=True)
class MemberRecord:
    user_id: uuid.UUID
    email: str
    roles: tuple[str, ...]
    status: str
    signer_roles_active: bool


@dataclass(frozen=True, slots=True)
class InviteRecord:
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    roles: tuple[str, ...]
    created_at: datetime
    expires_at: datetime


class MembershipNotFound(Exception):
    """The membership or invitation is not visible or no longer active."""


class InviteExpired(Exception):
    """The invitation has expired."""


class InviteEmailMismatch(Exception):
    """The authenticated account does not match the invitation email."""


class InviteAlreadyUsed(Exception):
    """The invitation has already been accepted or revoked."""


class InviteAlreadyPending(Exception):
    """A pending invitation already exists for this organization and email."""


class AlreadyMember(Exception):
    """The invited person already has a membership in the organization."""


class LastAdministrator(Exception):
    """An organization must retain an active OrgAdmin."""


class LastOwner(Exception):
    """An organization must retain an active Owner once it has one."""


class RoleSourceManaged(Exception):
    """The update would remove a role that SCIM or SSO still grants."""


class MembershipRepository(Protocol):
    async def create_invite(
        self,
        *,
        org_id: uuid.UUID,
        email: str,
        roles: tuple[str, ...],
        created_by: uuid.UUID,
        token_hash: bytes,
        now: datetime,
    ) -> InviteRecord: ...

    async def list_invites(
        self, *, org_id: uuid.UUID, now: datetime
    ) -> tuple[InviteRecord, ...] | None: ...

    async def revoke_invite(
        self, *, org_id: uuid.UUID, invite_id: uuid.UUID, now: datetime
    ) -> bool: ...

    async def accept_invite(
        self,
        *,
        token_hash: bytes,
        user_id: uuid.UUID,
        email: str,
        now: datetime,
    ) -> MemberRecord: ...

    async def list_members(self, *, org_id: uuid.UUID) -> tuple[MemberRecord, ...] | None: ...

    async def update_member(
        self,
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        roles: tuple[str, ...],
        updated_by: uuid.UUID,
    ) -> MemberRecord | None: ...

    async def remove_member(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> bool: ...


class SqlAlchemyMembershipRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        oidc_organization_id: uuid.UUID | None = None,
    ) -> None:
        self._sessions = sessions
        self._oidc_organization_id = oidc_organization_id

    async def create_invite(
        self,
        *,
        org_id: uuid.UUID,
        email: str,
        roles: tuple[str, ...],
        created_by: uuid.UUID,
        token_hash: bytes,
        now: datetime,
    ) -> InviteRecord:
        try:
            async with self._sessions() as session, session.begin():
                if await session.scalar(
                    select(
                        exists().where(
                            Membership.org_id == org_id,
                            Membership.user_id == User.id,
                            User.email == email,
                        )
                    )
                ):
                    raise AlreadyMember
                expired = (
                    await session.scalars(
                        select(Invite)
                        .where(
                            Invite.org_id == org_id,
                            Invite.email == email,
                            Invite.accepted_at.is_(None),
                            Invite.revoked_at.is_(None),
                            Invite.expires_at <= now,
                        )
                        .with_for_update()
                    )
                ).all()
                for old_invite in expired:
                    old_invite.revoked_at = now
                invite = Invite(
                    id=uuid7(),
                    org_id=org_id,
                    email=email,
                    roles=list(roles),
                    token_hash=token_hash,
                    created_at=now,
                    created_by=created_by,
                    expires_at=now + INVITE_LIFETIME,
                )
                session.add(invite)
                await session.flush()
                return _invite_record(invite)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_invites_pending_org_id_email":
                raise InviteAlreadyPending from None
            raise

    async def list_invites(
        self, *, org_id: uuid.UUID, now: datetime
    ) -> tuple[InviteRecord, ...] | None:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(Invite)
                    .where(
                        Invite.org_id == org_id,
                        Invite.accepted_at.is_(None),
                        Invite.revoked_at.is_(None),
                        Invite.expires_at > now,
                    )
                    .order_by(Invite.created_at, Invite.id)
                )
            ).all()
            if not rows and not await session.scalar(
                select(exists().where(Organization.id == org_id))
            ):
                return None
            return tuple(_invite_record(row) for row in rows)

    async def revoke_invite(
        self, *, org_id: uuid.UUID, invite_id: uuid.UUID, now: datetime
    ) -> bool:
        async with self._sessions() as session, session.begin():
            invite = await session.scalar(
                select(Invite)
                .where(
                    Invite.org_id == org_id,
                    Invite.id == invite_id,
                    Invite.accepted_at.is_(None),
                    Invite.revoked_at.is_(None),
                )
                .with_for_update()
            )
            if invite is None:
                return False
            invite.revoked_at = now
            await session.flush()
            return True

    async def accept_invite(
        self,
        *,
        token_hash: bytes,
        user_id: uuid.UUID,
        email: str,
        now: datetime,
    ) -> MemberRecord:
        async with self._sessions() as session, session.begin():
            invite = await session.scalar(
                select(Invite).where(Invite.token_hash == token_hash).with_for_update()
            )
            if invite is None:
                raise MembershipNotFound
            # Email first so a non-recipient cannot probe a token's used/expired state.
            if normalize_email(invite.email) != normalize_email(email):
                raise InviteEmailMismatch
            if invite.accepted_at is not None or invite.revoked_at is not None:
                raise InviteAlreadyUsed
            if now >= invite.expires_at:
                raise InviteExpired
            existing = await session.scalar(
                select(Membership).where(
                    Membership.org_id == invite.org_id,
                    Membership.user_id == user_id,
                )
            )
            if existing is not None:
                raise AlreadyMember
            membership = Membership(
                id=uuid7(),
                org_id=invite.org_id,
                user_id=user_id,
                roles=list(invite.roles),
                manual_roles=list(invite.roles),
                role_sources_initialized=True,
                status=MembershipStatus.ACTIVE,
                created_by=invite.created_by,
                updated_by=invite.created_by,
            )
            invite.accepted_at = now
            session.add(membership)
            await session.flush()
            return MemberRecord(
                user_id=user_id,
                email=invite.email,
                roles=tuple(invite.roles),
                status=MembershipStatus.ACTIVE,
                signer_roles_active=bool(_SIGNER_ROLES.intersection(invite.roles))
                and bool(
                    await session.scalar(
                        select(
                            exists().where(
                                WalletLink.user_id == user_id,
                                WalletLink.unlinked_at.is_(None),
                            )
                        )
                    )
                ),
            )

    async def list_members(self, *, org_id: uuid.UUID) -> tuple[MemberRecord, ...] | None:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        Membership,
                        User.email,
                        exists().where(
                            WalletLink.user_id == Membership.user_id,
                            WalletLink.unlinked_at.is_(None),
                        ),
                    )
                    .join(User, User.id == Membership.user_id)
                    .where(Membership.org_id == org_id)
                    .order_by(User.email, Membership.user_id)
                )
            ).all()
            if not rows and not await session.scalar(
                select(exists().where(Organization.id == org_id))
            ):
                return None
            return tuple(
                MemberRecord(
                    user_id=membership.user_id,
                    email=email,
                    roles=tuple(membership.roles),
                    status=membership.status,
                    signer_roles_active=bool(_SIGNER_ROLES.intersection(membership.roles))
                    and bool(wallet_linked),
                )
                for membership, email, wallet_linked in rows
            )

    async def update_member(
        self,
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        roles: tuple[str, ...],
        updated_by: uuid.UUID,
    ) -> MemberRecord | None:
        async with self._sessions() as session, session.begin():
            memberships = await self._locked_members(session, org_id)
            membership = next((item for item in memberships if item.user_id == user_id), None)
            if membership is None:
                return None
            oidc_linked = org_id == self._oidc_organization_id and bool(
                await session.scalar(select(exists().where(OIDCIdentity.user_id == user_id)))
            )
            initialize_legacy_role_sources(membership, oidc_identity_linked=oidc_linked)
            managed_roles = set(membership.oidc_roles) | set(membership.scim_roles)
            if managed_roles - set(roles):
                raise RoleSourceManaged
            # Roles an admin sends are explicit grants even if SCIM or SSO also grant them.
            manual_roles = set(roles)
            _guard_last_roles(memberships, membership, manual_roles | managed_roles)
            membership.manual_roles = sorted(manual_roles)
            membership.roles = sorted(manual_roles | managed_roles)
            membership.updated_by = updated_by
            await session.flush()
            user = await session.scalar(select(User).where(User.id == user_id))
            if user is None:  # unreachable: memberships.user_id is a foreign key
                raise RuntimeError("membership user is missing")
            wallet_linked = bool(
                await session.scalar(
                    select(
                        exists().where(
                            WalletLink.user_id == user_id,
                            WalletLink.unlinked_at.is_(None),
                        )
                    )
                )
            )
            return MemberRecord(
                user_id=user_id,
                email=user.email,
                roles=tuple(membership.roles),
                status=membership.status,
                signer_roles_active=bool(_SIGNER_ROLES.intersection(membership.roles))
                and wallet_linked,
            )

    async def remove_member(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        async with self._sessions() as session, session.begin():
            memberships = await self._locked_members(session, org_id)
            membership = next((item for item in memberships if item.user_id == user_id), None)
            if membership is None:
                return False
            _guard_last_roles(memberships, membership, set())
            await session.delete(membership)
            return True

    @staticmethod
    async def _locked_members(session: AsyncSession, org_id: uuid.UUID) -> list[Membership]:
        return list(
            (
                await session.scalars(
                    select(Membership)
                    .where(Membership.org_id == org_id)
                    .order_by(Membership.user_id)
                    .with_for_update()
                )
            ).all()
        )


def _guard_last_roles(
    memberships: list[Membership], target: Membership, new_roles: set[str]
) -> None:
    # Only active members count toward the minimum, so a suspended target may be changed freely.
    if target.status != MembershipStatus.ACTIVE:
        return
    active = [item for item in memberships if item.status == MembershipStatus.ACTIVE]
    current_roles = set(target.roles)
    if (
        OrganizationRole.ORG_ADMIN.value in current_roles
        and OrganizationRole.ORG_ADMIN.value not in new_roles
        and sum(OrganizationRole.ORG_ADMIN.value in item.roles for item in active) <= 1
    ):
        raise LastAdministrator
    if (
        OrganizationRole.OWNER.value in current_roles
        and OrganizationRole.OWNER.value not in new_roles
        and sum(OrganizationRole.OWNER.value in item.roles for item in active) <= 1
    ):
        raise LastOwner


def _invite_record(invite: Invite) -> InviteRecord:
    return InviteRecord(
        id=invite.id,
        org_id=invite.org_id,
        email=invite.email,
        roles=tuple(invite.roles),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


class InviteCreateRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    roles: list[OrganizationRole] = Field(min_length=1, max_length=len(OrganizationRole))

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _SIMPLE_EMAIL.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, values: list[OrganizationRole]) -> list[OrganizationRole]:
        if len(set(values)) != len(values):
            raise ValueError("roles must be unique")
        return values


class RoleUpdateRequest(ApiModel):
    roles: list[OrganizationRole] = Field(min_length=1, max_length=len(OrganizationRole))

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, values: list[OrganizationRole]) -> list[OrganizationRole]:
        if len(set(values)) != len(values):
            raise ValueError("roles must be unique")
        return values


class InviteView(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    roles: list[str]
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_record(cls, record: InviteRecord) -> InviteView:
        return cls(
            id=record.id,
            org_id=record.org_id,
            email=record.email,
            roles=list(record.roles),
            created_at=record.created_at,
            expires_at=record.expires_at,
        )


class InviteCreatedResponse(InviteView):
    token: str


class MemberView(ApiModel):
    user_id: uuid.UUID
    email: str
    roles: list[str]
    status: str
    signer_roles_active: bool

    @classmethod
    def from_record(cls, record: MemberRecord) -> MemberView:
        return cls(
            user_id=record.user_id,
            email=record.email,
            roles=list(record.roles),
            status=record.status,
            signer_roles_active=record.signer_roles_active,
        )


class MembersResponse(ApiModel):
    members: list[MemberView]


class InvitesResponse(ApiModel):
    invites: list[InviteView]


class MemberResponse(ApiModel):
    member: MemberView


router = APIRouter(prefix="/v1", tags=["membership"])
_require_org_admin = require_role(OrganizationRole.ORG_ADMIN)


def _repository(request: Request) -> MembershipRepository:
    repository = getattr(request.app.state, "membership_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="MEMBERSHIP_UNAVAILABLE",
            title="Membership service unavailable",
            detail="Membership storage is not configured.",
        )
    return cast(MembershipRepository, repository)


def _api_failure(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


@router.get(
    "/orgs/{organization_id}/members",
    response_model=MembersResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def list_members(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> MembersResponse:
    records = await _repository(request).list_members(org_id=member.organization_id)
    if records is None:
        raise _api_failure(
            404, "ORG_NOT_FOUND", "Organization not found", "The organization is unavailable."
        )
    return MembersResponse(members=[MemberView.from_record(record) for record in records])


@router.get(
    "/orgs/{organization_id}/invites",
    response_model=InvitesResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def list_invites(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> InvitesResponse:
    records = await _repository(request).list_invites(
        org_id=member.organization_id, now=datetime.now(UTC)
    )
    if records is None:
        raise _api_failure(
            404, "ORG_NOT_FOUND", "Organization not found", "The organization is unavailable."
        )
    return InvitesResponse(invites=[InviteView.from_record(record) for record in records])


@router.post(
    "/orgs/{organization_id}/invites",
    status_code=201,
    response_model=InviteCreatedResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def create_invite(
    payload: InviteCreateRequest,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> InviteCreatedResponse:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    try:
        record = await _repository(request).create_invite(
            org_id=member.organization_id,
            email=payload.email,
            roles=tuple(role.value for role in payload.roles),
            created_by=member.user_id,
            token_hash=hashlib.sha256(token.encode("ascii")).digest(),
            now=now,
        )
    except InviteAlreadyPending:
        raise _api_failure(
            409,
            "INVITE_PENDING",
            "Invitation already pending",
            "Revoke the pending invitation before creating another.",
        ) from None
    except AlreadyMember:
        raise _api_failure(
            409,
            "ALREADY_MEMBER",
            "Already a member",
            "This email already belongs to a member of the organization.",
        ) from None
    return InviteCreatedResponse(**InviteView.from_record(record).model_dump(), token=token)


@router.post("/invites/{token}/accept", response_model=MemberResponse)
async def accept_invite(token: str, request: Request) -> MemberResponse:
    access = await _authenticated(request, require_csrf=True)
    _require_unscoped(access)
    if not token or len(token) > 128:
        raise _api_failure(
            400, "INVITE_INVALID", "Invalid invitation", "The invitation token is invalid."
        )
    try:
        record = await _repository(request).accept_invite(
            token_hash=hashlib.sha256(token.encode("utf-8")).digest(),
            user_id=access.user.id,
            email=access.user.email,
            now=datetime.now(UTC),
        )
    except (MembershipNotFound, InviteAlreadyUsed):
        raise _api_failure(
            400,
            "INVITE_INVALID",
            "Invalid invitation",
            "The invitation token is invalid or already used.",
        ) from None
    except InviteExpired:
        raise _api_failure(
            410, "INVITE_EXPIRED", "Invitation expired", "Request a new invitation."
        ) from None
    except InviteEmailMismatch:
        raise _api_failure(
            403,
            "INVITE_EMAIL_MISMATCH",
            "Invitation email mismatch",
            "Sign in with the email address that was invited.",
        ) from None
    except AlreadyMember:
        raise _api_failure(
            409,
            "ALREADY_MEMBER",
            "Already a member",
            "This account already belongs to the organization.",
        ) from None
    return MemberResponse(member=MemberView.from_record(record))


@router.patch(
    "/orgs/{organization_id}/members/{user_id}",
    response_model=MemberResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def update_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> MemberResponse:
    try:
        record = await _repository(request).update_member(
            org_id=member.organization_id,
            user_id=user_id,
            roles=tuple(role.value for role in payload.roles),
            updated_by=member.user_id,
        )
    except RoleSourceManaged:
        raise _api_failure(
            409,
            "ROLE_SOURCE_MANAGED",
            "Role managed by SCIM or SSO",
            "Remove the role in the identity provider; it cannot be removed here.",
        ) from None
    except LastAdministrator:
        raise _api_failure(
            409,
            "LAST_ADMIN",
            "Last organization admin",
            "Assign another active OrgAdmin before changing this membership.",
        ) from None
    except LastOwner:
        raise _api_failure(
            409,
            "LAST_OWNER",
            "Last organization owner",
            "Assign another active Owner before changing this membership.",
        ) from None
    if record is None:
        raise _api_failure(
            404,
            "MEMBER_NOT_FOUND",
            "Member not found",
            "No member has this user id in the organization.",
        )
    return MemberResponse(member=MemberView.from_record(record))


@router.delete(
    "/orgs/{organization_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
    openapi_extra={"x-organization-scoped": True},
)
async def remove_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> Response:
    try:
        removed = await _repository(request).remove_member(
            org_id=member.organization_id, user_id=user_id
        )
    except LastAdministrator:
        raise _api_failure(
            409,
            "LAST_ADMIN",
            "Last organization admin",
            "Assign another active OrgAdmin before removing this member.",
        ) from None
    except LastOwner:
        raise _api_failure(
            409,
            "LAST_OWNER",
            "Last organization owner",
            "Assign another active Owner before removing this member.",
        ) from None
    if not removed:
        raise _api_failure(
            404,
            "MEMBER_NOT_FOUND",
            "Member not found",
            "No member has this user id in the organization.",
        )
    return Response(status_code=204)


@router.delete(
    "/orgs/{organization_id}/invites/{invite_id}",
    status_code=204,
    response_class=Response,
    openapi_extra={"x-organization-scoped": True},
)
async def revoke_invite(
    organization_id: uuid.UUID,
    invite_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> Response:
    revoked = await _repository(request).revoke_invite(
        org_id=member.organization_id, invite_id=invite_id, now=datetime.now(UTC)
    )
    if not revoked:
        raise _api_failure(
            404, "INVITE_NOT_FOUND", "Invitation not found", "No pending invitation has this id."
        )
    return Response(status_code=204)
