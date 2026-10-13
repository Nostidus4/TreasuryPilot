from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.common.repository import OrgScopedRepository
from treasurypilot_api.identity.api import ApiModel, _authenticated, _wallet_service
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationRole,
    WalletLink,
    uuid7,
)
from treasurypilot_api.identity.rbac import (
    MemberAccess,
    organization_not_found,
    require_member,
    require_role,
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


class OrganizationPermissionDenied(Exception):
    """The member does not hold a role allowed to change the requested setting."""


class OrganizationOwnerNotOnchain(Exception):
    """The Owner role is inactive because no linked wallet owns Safe T on-chain."""


class OrganizationRepository(Protocol):
    async def member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None: ...

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


class MembershipRepository(OrgScopedRepository[Membership]):
    model = Membership

    async def active_for_user(self, user_id: uuid.UUID) -> Membership | None:
        membership: Membership | None = await self.session.scalar(
            self.select().where(
                Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE
            )
        )
        return membership


class SqlAlchemyOrganizationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        async with self._sessions() as session:
            membership = await MembershipRepository(session, organization_id).active_for_user(
                user_id
            )
            return None if membership is None else frozenset(membership.roles)

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

    async def get_for_member(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationOverview:
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
                Membership.user_id == user_id,
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
                MembershipRepository(session, organization_id)
                .select()
                .where(
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .with_for_update()
            )
            if membership is None:
                raise OrganizationNotFound
            roles = set(membership.roles)
            owner_authorized = OrganizationRole.OWNER.value in roles and membership.owner_is_onchain
            # Owner is granted only through role assignment (#107), never at org
            # creation: it means the user's linked wallet owns Safe T (M01-D5, M01-D7).
            if solo_mode is not None and OrganizationRole.OWNER.value not in roles:
                raise OrganizationPermissionDenied
            if solo_mode is not None and not owner_authorized:
                raise OrganizationOwnerNotOnchain
            if auto_match is not None and not roles.intersection(
                {OrganizationRole.ORG_ADMIN.value}
            ):
                if OrganizationRole.OWNER.value not in roles:
                    raise OrganizationPermissionDenied
                if not owner_authorized:
                    raise OrganizationOwnerNotOnchain
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


def _repository(request: Request) -> OrganizationRepository:
    repository = getattr(request.app.state, "organization_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="ORG_UNAVAILABLE",
            title="Organization service unavailable",
            detail="Organization storage is not configured.",
        )
    return cast(OrganizationRepository, repository)


def _current_user(access: SessionAccess) -> uuid.UUID:
    return access.user.id


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
    request: Request, member: Annotated[MemberAccess, Depends(require_member)]
) -> OrganizationDetailsResponse:
    try:
        overview = await _repository(request).get_for_member(
            organization_id=member.organization_id,
            user_id=member.user_id,
        )
    except OrganizationNotFound:
        raise organization_not_found() from None
    return OrganizationDetailsResponse(
        org=OrganizationView.from_record(overview.organization),
        checklist=OrganizationChecklist.model_validate(overview.checklist, from_attributes=True),
    )


@router.patch("/{organization_id}/settings", response_model=OrganizationResponse)
async def update_organization_settings(
    payload: OrganizationSettingsRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)),
    ],
) -> OrganizationResponse:
    if payload.solo_mode is None and payload.auto_match is None:
        raise AuthFailure(
            status=422,
            code="SETTINGS_EMPTY",
            title="No settings provided",
            detail="At least one supported setting must be provided.",
        )
    try:
        if getattr(request.app.state, "wallet_repository", None) is not None:
            wallet_service = _wallet_service(request)
            if payload.solo_mode is not None:
                await wallet_service.require_onchain_owner(
                    org_id=organization_id,
                    user_id=_current_user(access),
                )
            else:
                await wallet_service.refresh_org_owner_status(
                    org_id=organization_id,
                    user_id=_current_user(access),
                )
        organization = await _repository(request).update_settings(
            organization_id=member.organization_id,
            user_id=member.user_id,
            solo_mode=payload.solo_mode,
            auto_match=payload.auto_match,
        )
    except OrganizationNotFound:
        raise organization_not_found() from None
    except OrganizationOwnerNotOnchain:
        raise AuthFailure(
            status=403,
            code="OWNER_NOT_ONCHAIN",
            title="On-chain owner required",
            detail="Your linked wallet is not an on-chain owner of Safe T.",
        ) from None
    except OrganizationPermissionDenied:
        raise _forbidden() from None
    return OrganizationResponse(org=OrganizationView.from_record(organization))
