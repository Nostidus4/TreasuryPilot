from __future__ import annotations

import hmac
import ipaddress
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.admin.models import PlatformAdminEvent, SupportGrant
from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import Membership, Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.treasury.models import Treasury

logger = logging.getLogger(__name__)


class TenantView(ApiModel):
    id: uuid.UUID
    name: str
    country: str | None
    created_at: AwareDatetime
    status: str
    active_members: int
    treasuries: int


class TenantList(ApiModel):
    items: list[TenantView]


class TenantHealth(ApiModel):
    tenant_id: uuid.UUID
    status: str
    active_members: int
    treasuries: int


class SupportGrantRequest(ApiModel):
    staff_user: str = Field(min_length=1, max_length=200)
    duration_hours: int = Field(default=24, ge=1, le=72)

    @field_validator("staff_user")
    @classmethod
    def normalize_staff_user(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("staff_user must not be empty")
        return clean


class SupportGrantView(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    staff_user: str
    scope: Literal["read"]
    expires_at: AwareDatetime
    granted_by: uuid.UUID
    created_at: AwareDatetime
    revoked_at: AwareDatetime | None


class SupportSummary(ApiModel):
    tenant: TenantView
    grant_id: uuid.UUID


def _staff_auth(settings: Settings) -> Callable[[Request], Awaitable[str]]:
    networks = settings.admin_networks  # parsed once; validated by Settings at startup

    async def authorize(request: Request) -> str:
        configured = settings.admin_staff_token
        staff_id = settings.admin_staff_id
        if not settings.admin_configured or configured is None or not staff_id:
            raise HTTPException(status_code=503, detail="Platform admin is not configured")
        # Deliberately use the socket peer. Forwarded headers are untrusted unless
        # a separately configured trusted-proxy chain is introduced. The network check
        # runs first so a disallowed caller learns nothing about token validity.
        peer = request.client.host if request.client else None
        try:
            address = ipaddress.ip_address(peer or "")
        except ValueError:
            address = None
        if address is None or not any(address in network for network in networks):
            logger.warning("admin.auth_denied", extra={"reason": "source_address", "peer": peer})
            raise HTTPException(status_code=403, detail="Source address is not allowed")
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        # Encode: compare_digest raises TypeError on non-ASCII str (headers decode as latin-1).
        if (
            scheme.casefold() != "bearer"
            or not supplied
            or not hmac.compare_digest(supplied.encode(), configured.get_secret_value().encode())
        ):
            logger.warning("admin.auth_denied", extra={"reason": "token", "peer": peer})
            raise HTTPException(status_code=401, detail="Staff authentication required")
        return staff_id

    return authorize


async def _counts(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, int]:
    members = await session.scalar(
        select(func.count(Membership.user_id)).where(
            Membership.org_id == tenant_id, Membership.status == "active"
        )
    )
    treasuries = await session.scalar(
        select(func.count(Treasury.id)).where(Treasury.org_id == tenant_id)
    )
    return members or 0, treasuries or 0


def _view(org: Organization, members: int, treasuries: int) -> TenantView:
    return TenantView(
        id=org.id,
        name=org.name,
        country=org.country,
        created_at=org.created_at,
        status=org.platform_status,
        active_members=members,
        treasuries=treasuries,
    )


def create_admin_router(
    settings: Settings, sessions: async_sessionmaker[AsyncSession] | None
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["platform-admin"])
    staff = _staff_auth(settings)

    def require_sessions() -> async_sessionmaker[AsyncSession]:
        if sessions is None:
            raise HTTPException(status_code=503, detail="Platform admin storage is unavailable")
        return sessions

    staff_dependency = Depends(staff)
    sessions_dependency = Depends(require_sessions)

    @router.get("/tenants", response_model=TenantList)
    async def tenants(
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> TenantList:
        async with db_sessions() as session:
            result = await session.execute(
                select(
                    Organization,
                    select(func.count(Membership.user_id))
                    .where(Membership.org_id == Organization.id, Membership.status == "active")
                    .correlate(Organization)
                    .scalar_subquery(),
                    select(func.count(Treasury.id))
                    .where(Treasury.org_id == Organization.id)
                    .correlate(Organization)
                    .scalar_subquery(),
                ).order_by(Organization.created_at.desc(), Organization.id)
            )
            rows = cast(list[tuple[Organization, int, int]], result.all())
        logger.info("admin.tenants_listed", extra={"actor": actor})
        return TenantList(items=[_view(org, m, t) for org, m, t in rows])

    @router.get("/tenants/{tenant_id}/health", response_model=TenantHealth)
    async def tenant_health(
        tenant_id: uuid.UUID,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> TenantHealth:
        async with db_sessions() as session:
            org = await session.get(Organization, tenant_id)
            if org is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            members, treasuries = await _counts(session, tenant_id)
        logger.info("admin.tenant_health_read", extra={"actor": actor, "tenant_id": str(tenant_id)})
        return TenantHealth(
            tenant_id=tenant_id,
            status=org.platform_status,
            active_members=members,
            treasuries=treasuries,
        )

    @router.post("/tenants/{tenant_id}/suspend", response_model=TenantView)
    async def suspend_tenant(
        tenant_id: uuid.UUID,
        request: Request,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> TenantView:
        async with db_sessions() as session, session.begin():
            org = await session.get(Organization, tenant_id, with_for_update=True)
            if org is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            # Idempotent: a retry must not write another audit event.
            if org.platform_status != "suspended":
                org.platform_status = "suspended"
                session.add(
                    PlatformAdminEvent(
                        org_id=tenant_id,
                        actor_id=actor,
                        action="tenant.suspended",
                        data={"source_ip": request.client.host if request.client else None},
                    )
                )
            response = _view(org, *await _counts(session, tenant_id))
        return response

    @router.get("/tenants/{tenant_id}/support", response_model=SupportSummary)
    async def support_summary(
        tenant_id: uuid.UUID,
        request: Request,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> SupportSummary:
        now = datetime.now(UTC)
        async with db_sessions() as session, session.begin():
            grant = await session.scalar(
                select(SupportGrant)
                .where(
                    SupportGrant.org_id == tenant_id,
                    SupportGrant.staff_user == actor,
                    SupportGrant.scope == "read",
                    SupportGrant.revoked_at.is_(None),
                    SupportGrant.expires_at > now,
                )
                .order_by(SupportGrant.expires_at.desc())
                .limit(1)
            )
            if grant is None:
                raise HTTPException(status_code=403, detail="Active support consent is required")
            org = await session.get(Organization, tenant_id)
            if org is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            members, treasuries = await _counts(session, tenant_id)
            session.add(
                PlatformAdminEvent(
                    org_id=tenant_id,
                    actor_id=actor,
                    action="support.read",
                    data={
                        "grant_id": str(grant.id),
                        "scope": grant.scope,
                        "source_ip": request.client.host if request.client else None,
                    },
                )
            )
            result = SupportSummary(tenant=_view(org, members, treasuries), grant_id=grant.id)
        logger.info(
            "admin.support_read",
            extra={"actor": actor, "tenant_id": str(tenant_id), "grant_id": str(grant.id)},
        )
        return result

    return router


def create_support_grant_router(
    sessions: async_sessionmaker[AsyncSession] | None,
) -> APIRouter:
    """Expose tenant-consented support grants to tenant administrators only."""

    router = APIRouter(prefix="/v1/orgs/{organization_id}/support-grants", tags=["support"])
    consent = require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)

    def require_sessions() -> async_sessionmaker[AsyncSession]:
        if sessions is None:
            raise HTTPException(status_code=503, detail="Support grant storage is unavailable")
        return sessions

    consent_dependency = Depends(consent)
    sessions_dependency = Depends(require_sessions)

    @router.post("", response_model=SupportGrantView, status_code=201)
    async def grant_support(
        payload: SupportGrantRequest,
        member: MemberAccess = consent_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> SupportGrantView:
        now = datetime.now(UTC)
        grant = SupportGrant(
            id=uuid.uuid4(),
            org_id=member.organization_id,
            staff_user=payload.staff_user,
            scope="read",
            expires_at=now + timedelta(hours=payload.duration_hours),
            granted_by=member.user_id,
            created_at=now,
        )
        async with db_sessions() as session, session.begin():
            session.add(grant)
            await write_audit(
                session,
                org_id=member.organization_id,
                actor=AuditActor(AuditActorType.USER, member.user_id),
                action="platform.support.granted",
                entity=AuditEntity("support_grant", grant.id),
                data={
                    "staff_user": grant.staff_user,
                    "scope": grant.scope,
                    "expires_at": grant.expires_at,
                },
            )
        return SupportGrantView.model_validate(grant, from_attributes=True)

    @router.get("", response_model=list[SupportGrantView])
    async def list_support_grants(
        organization_id: uuid.UUID,
        member: MemberAccess = consent_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> list[SupportGrantView]:
        async with db_sessions() as session:
            grants = await session.scalars(
                select(SupportGrant)
                .where(SupportGrant.org_id == member.organization_id)
                .order_by(SupportGrant.created_at.desc(), SupportGrant.id)
            )
            return [SupportGrantView.model_validate(grant, from_attributes=True) for grant in grants]

    @router.delete("/{grant_id}", status_code=204)
    async def revoke_support_grant(
        grant_id: uuid.UUID,
        organization_id: uuid.UUID,
        member: MemberAccess = consent_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> Response:
        now = datetime.now(UTC)
        async with db_sessions() as session, session.begin():
            grant = await session.scalar(
                select(SupportGrant)
                .where(
                    SupportGrant.id == grant_id,
                    SupportGrant.org_id == member.organization_id,
                )
                .with_for_update()
            )
            if grant is None:
                raise HTTPException(status_code=404, detail="Support grant not found")
            if grant.revoked_at is None:
                grant.revoked_at = now
                await write_audit(
                    session,
                    org_id=member.organization_id,
                    actor=AuditActor(AuditActorType.USER, member.user_id),
                    action="platform.support.revoked",
                    entity=AuditEntity("support_grant", grant.id),
                    data={"staff_user": grant.staff_user, "scope": grant.scope},
                )
        return Response(status_code=204)

    return router
