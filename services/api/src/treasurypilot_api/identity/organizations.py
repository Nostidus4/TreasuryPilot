from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.access import (
    MemberContext,
    forbidden,
    not_found,
    organization_repository,
    require_member,
    require_role,
)
from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationRole,
    WalletLink,
    uuid7,
)
from treasurypilot_api.treasury.models import Treasury, TreasuryStatus


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

    async def get_for_member(self, member: MemberContext) -> OrganizationOverview: ...

    async def get_member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[str, ...] | None: ...

    async def has_active_signer_wallet(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool: ...

    async def update_settings(
        self,
        member: MemberContext,
        *,
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

    async def get_for_member(self, member: MemberContext) -> OrganizationOverview:
        organization_id = member.organization_id
        active_member = Membership.status == MembershipStatus.ACTIVE
        # One statement so the membership check and every checklist flag come
        # from the same snapshot.
        statement = select(
            Organization,
            select(func.count(Membership.id))
            .where(Membership.org_id == organization_id, active_member)
            .scalar_subquery(),
            exists().where(
                WalletLink.user_id == Membership.user_id,
                Membership.org_id == organization_id,
                active_member,
                WalletLink.unlinked_at.is_(None),
            ),
            exists().where(Treasury.org_id == organization_id),
            exists().where(
                Treasury.org_id == organization_id,
                Treasury.module_address.is_not(None),
                Treasury.status == TreasuryStatus.READY,
            ),
        ).where(
            Organization.id == organization_id,
            exists().where(
                Membership.org_id == organization_id,
                Membership.user_id == member.user_id,
                active_member,
            ),
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).one_or_none()
            if row is None:
                raise OrganizationNotFound
            organization, member_count, wallet_linked, treasury_created, module_enabled = row
            return OrganizationOverview(
                organization=_record(cast(Organization, organization)),
                checklist=OnboardingChecklist(
                    member_count=cast(int | None, member_count) or 0,
                    wallet_linked=bool(wallet_linked),
                    treasury_created=bool(treasury_created),
                    module_enabled=bool(module_enabled),
                ),
            )

    async def get_member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[str, ...] | None:
        async with self._sessions() as session:
            membership = await session.scalar(
                select(Membership).where(
                    Membership.org_id == organization_id,
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
            return tuple(membership.roles) if membership is not None else None

    async def has_active_signer_wallet(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(
                        exists().where(
                            Membership.org_id == organization_id,
                            Membership.user_id == user_id,
                            Membership.status == MembershipStatus.ACTIVE,
                            WalletLink.user_id == user_id,
                            WalletLink.unlinked_at.is_(None),
                        )
                    )
                )
            )

    async def update_settings(
        self,
        member: MemberContext,
        *,
        solo_mode: bool | None,
        auto_match: bool | None,
    ) -> OrganizationRecord:
        # Roles are checked by the route; this only re-checks, under lock, that the
        # membership is still active so a concurrent revocation cannot slip through.
        async with self._sessions() as session, session.begin():
            organization = await session.scalar(
                select(Organization)
                .join(
                    Membership,
                    (Membership.org_id == Organization.id)
                    & (Membership.user_id == member.user_id)
                    & (Membership.status == MembershipStatus.ACTIVE),
                )
                .where(Organization.id == member.organization_id)
                .with_for_update()
            )
            if organization is None:
                raise OrganizationNotFound
            if solo_mode is not None:
                organization.solo_mode = solo_mode
            if auto_match is not None:
                organization.auto_match = auto_match
            organization.updated_by = member.user_id
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
        return cls.model_validate(organization, from_attributes=True)


class CreateOrganizationRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    display_tz: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("name", "display_tz")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("display_tz")
    @classmethod
    def known_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError("must be an IANA time zone") from None
        return value

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


router = APIRouter(prefix="/v1/orgs", tags=["organizations"])
_require_settings_role = require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)


@router.post("", status_code=201, response_model=OrganizationResponse)
async def create_organization(
    payload: CreateOrganizationRequest, request: Request, response: Response
) -> OrganizationResponse:
    access = await _authenticated(request, require_csrf=True)
    organization = await organization_repository(request).create(
        user_id=access.user.id,
        name=payload.name,
        legal_name=payload.legal_name,
        country=payload.country,
        display_tz=payload.display_tz,
    )
    response.headers["Location"] = f"/v1/orgs/{organization.id}"
    return OrganizationResponse(org=OrganizationView.from_record(organization))


@router.get(
    "/{organization_id}",
    response_model=OrganizationDetailsResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def get_organization(
    request: Request,
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> OrganizationDetailsResponse:
    try:
        overview = await organization_repository(request).get_for_member(member)
    except OrganizationNotFound:
        raise not_found() from None
    return OrganizationDetailsResponse(
        org=OrganizationView.from_record(overview.organization),
        checklist=OrganizationChecklist.model_validate(overview.checklist, from_attributes=True),
    )


@router.patch(
    "/{organization_id}/settings",
    response_model=OrganizationResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def update_organization_settings(
    payload: OrganizationSettingsRequest,
    request: Request,
    member: MemberContext = Depends(_require_settings_role),  # noqa: B008
) -> OrganizationResponse:
    if payload.solo_mode is None and payload.auto_match is None:
        raise AuthFailure(
            status=422,
            code="SETTINGS_EMPTY",
            title="No settings provided",
            detail="At least one supported setting must be provided.",
        )
    # Owner is granted only through role assignment (#107), never at org creation:
    # it means the user's linked wallet owns Safe T (M01-D5, M01-D7).
    if payload.solo_mode is not None and not member.has_any(OrganizationRole.OWNER):
        raise forbidden()
    try:
        organization = await organization_repository(request).update_settings(
            member,
            solo_mode=payload.solo_mode,
            auto_match=payload.auto_match,
        )
    except OrganizationNotFound:
        raise not_found() from None
    return OrganizationResponse(org=OrganizationView.from_record(organization))
