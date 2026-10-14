from __future__ import annotations

import hmac
import ipaddress
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.admin.models import PlatformAdminEvent
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import Membership, Organization
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

    return router
