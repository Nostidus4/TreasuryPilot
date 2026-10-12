from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationRole,
    User,
    WalletLink,
    uuid7,
)
from treasurypilot_api.treasury.models import Treasury


@dataclass(frozen=True, slots=True)
class OrganizationRecord:
    id: uuid.UUID
    name: str
    legal_name: str | None
    country: str | None
    display_tz: str
    solo_mode: bool
    auto_match: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OnboardingChecklist:
    member_count: int
    wallet_linked: bool
    treasury_created: bool
    module_enabled: bool


@dataclass(frozen=True, slots=True)
class OrganizationOverview:
    organization: OrganizationRecord
    checklist: OnboardingChecklist


class OrganizationNotFound(Exception):
    """The organization does not exist or is not visible to this user."""


class OrganizationPermissionDenied(Exception):
    """The member does not hold a role allowed to change the requested setting."""


class OrganizationRepository(Protocol):
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        legal_name: str | None,
        country: str | None,
        display_tz: str,
    ) -> OrganizationRecord: ...

    async def get_for_member(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationOverview: ...

    async def update_settings(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        solo_mode: bool | None,
        auto_match: bool | None,
    ) -> OrganizationRecord: ...


def _record(organization: Organization) -> OrganizationRecord:
    return OrganizationRecord(
        id=organization.id,
        name=organization.name,
        legal_name=organization.legal_name,
        country=organization.country,
        display_tz=organization.display_tz,
        solo_mode=organization.solo_mode,
        auto_match=organization.auto_match,
        created_at=organization.created_at,
    )


class SqlAlchemyOrganizationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        legal_name: str | None,
        country: str | None,
        display_tz: str,
    ) -> OrganizationRecord:
        async with self._sessions() as session, session.begin():
            user_exists = await session.scalar(select(User.id).where(User.id == user_id))
            if user_exists is None:
                raise AuthFailure(
                    status=401,
                    code="AUTH_REQUIRED",
                    title="Authentication required",
                    detail="A valid session is required.",
                )
            organization = Organization(
                id=uuid7(),
                name=name,
                legal_name=legal_name,
                country=country,
                display_tz=display_tz,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                Membership(
                    id=uuid7(),
                    org_id=organization.id,
                    user_id=user_id,
                    roles=[OrganizationRole.ORG_ADMIN.value],
                    status=MembershipStatus.ACTIVE,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            await session.flush()
            return _record(organization)

    async def get_for_member(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationOverview:
        async with self._sessions() as session:
            member = await session.scalar(
                select(Membership.id).where(
                    Membership.org_id == organization_id,
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
            if member is None:
                raise OrganizationNotFound
            organization = await session.get(Organization, organization_id)
            if organization is None:
                raise OrganizationNotFound
            member_count = await session.scalar(
                select(func.count(Membership.id)).where(
                    Membership.org_id == organization_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
            wallet_linked = await session.scalar(
                select(WalletLink.id)
                .join(Membership, Membership.user_id == WalletLink.user_id)
                .where(
                    Membership.org_id == organization_id,
                    Membership.status == MembershipStatus.ACTIVE,
                    WalletLink.unlinked_at.is_(None),
                )
                .limit(1)
            )
            treasury = await session.scalar(
                select(Treasury).where(Treasury.org_id == organization_id).limit(1)
            )
            return OrganizationOverview(
                organization=_record(organization),
                checklist=OnboardingChecklist(
                    member_count=int(member_count or 0),
                    wallet_linked=wallet_linked is not None,
                    treasury_created=treasury is not None,
                    module_enabled=treasury is not None and treasury.module_address is not None,
                ),
            )

    async def update_settings(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        solo_mode: bool | None,
        auto_match: bool | None,
    ) -> OrganizationRecord:
        async with self._sessions() as session, session.begin():
            membership = await session.scalar(
                select(Membership)
                .where(
                    Membership.org_id == organization_id,
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .with_for_update()
            )
            if membership is None:
                raise OrganizationNotFound
            roles = set(membership.roles)
            if solo_mode is not None and OrganizationRole.OWNER.value not in roles:
                raise OrganizationPermissionDenied
            if auto_match is not None and not roles.intersection(
                {OrganizationRole.ORG_ADMIN.value, OrganizationRole.OWNER.value}
            ):
                raise OrganizationPermissionDenied
            organization = await session.scalar(
                select(Organization).where(Organization.id == organization_id).with_for_update()
            )
            if organization is None:
                raise OrganizationNotFound
            if solo_mode is not None:
                organization.solo_mode = solo_mode
            if auto_match is not None:
                organization.auto_match = auto_match
            organization.updated_by = user_id
            await session.flush()
            return _record(organization)


class OrganizationView(ApiModel):
    id: uuid.UUID
    name: str
    legal_name: str | None
    country: str | None
    display_tz: str
    solo_mode: bool
    auto_match: bool
    created_at: datetime

    @classmethod
    def from_record(cls, organization: OrganizationRecord) -> OrganizationView:
        return cls(
            id=organization.id,
            name=organization.name,
            legal_name=organization.legal_name,
            country=organization.country,
            display_tz=organization.display_tz,
            solo_mode=organization.solo_mode,
            auto_match=organization.auto_match,
            created_at=organization.created_at,
        )


class CreateOrganizationRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    display_tz: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("name", "display_tz")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("legal_name")
    @classmethod
    def strip_legal_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()


class OrganizationResponse(ApiModel):
    org: OrganizationView


class OrganizationChecklist(ApiModel):
    member_count: int
    wallet_linked: bool
    treasury_created: bool
    module_enabled: bool


class OrganizationDetailsResponse(ApiModel):
    org: OrganizationView
    checklist: OrganizationChecklist


class OrganizationSettingsRequest(ApiModel):
    solo_mode: bool | None = None
    auto_match: bool | None = None


def _repository(request: Request) -> OrganizationRepository:
    repository = getattr(request.app.state, "organization_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="AUTH_UNAVAILABLE",
            title="Organization service unavailable",
            detail="Organization storage is not configured.",
        )
    return repository


def _current_user(access: SessionAccess) -> uuid.UUID:
    return access.user.id


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
        detail="An organization role with permission to change these settings is required.",
    )


router = APIRouter(prefix="/v1/orgs", tags=["organizations"])


@router.post("", status_code=201, response_model=OrganizationResponse)
async def create_organization(
    payload: CreateOrganizationRequest, request: Request, response: Response
) -> OrganizationResponse:
    access = await _authenticated(request, require_csrf=True)
    organization = await _repository(request).create(
        user_id=_current_user(access),
        name=payload.name,
        legal_name=payload.legal_name,
        country=payload.country,
        display_tz=payload.display_tz,
    )
    response.headers["Location"] = f"/v1/orgs/{organization.id}"
    return OrganizationResponse(org=OrganizationView.from_record(organization))


@router.get("/{organization_id}", response_model=OrganizationDetailsResponse)
async def get_organization(
    organization_id: uuid.UUID, request: Request
) -> OrganizationDetailsResponse:
    access = await _authenticated(request)
    try:
        overview = await _repository(request).get_for_member(
            organization_id=organization_id,
            user_id=_current_user(access),
        )
    except OrganizationNotFound:
        raise _not_found() from None
    return OrganizationDetailsResponse(
        org=OrganizationView.from_record(overview.organization),
        checklist=OrganizationChecklist(
            member_count=overview.checklist.member_count,
            wallet_linked=overview.checklist.wallet_linked,
            treasury_created=overview.checklist.treasury_created,
            module_enabled=overview.checklist.module_enabled,
        ),
    )


@router.patch("/{organization_id}/settings", response_model=OrganizationResponse)
async def update_organization_settings(
    organization_id: uuid.UUID,
    payload: OrganizationSettingsRequest,
    request: Request,
) -> OrganizationResponse:
    if payload.solo_mode is None and payload.auto_match is None:
        raise AuthFailure(
            status=422,
            code="SETTINGS_EMPTY",
            title="No settings provided",
            detail="At least one supported setting must be provided.",
        )
    access = await _authenticated(request, require_csrf=True)
    try:
        organization = await _repository(request).update_settings(
            organization_id=organization_id,
            user_id=_current_user(access),
            solo_mode=payload.solo_mode,
            auto_match=payload.auto_match,
        )
    except OrganizationNotFound:
        raise _not_found() from None
    except OrganizationPermissionDenied:
        raise _forbidden() from None
    return OrganizationResponse(org=OrganizationView.from_record(organization))
