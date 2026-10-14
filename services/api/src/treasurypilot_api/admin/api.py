from __future__ import annotations

import hmac
import ipaddress
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.admin.models import PlatformAdminEvent
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import Membership, Organization
from treasurypilot_api.treasury.models import Treasury


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
    async def authorize(request: Request) -> str:
        configured = settings.admin_staff_token
        staff_id = settings.admin_staff_id
        try:
            networks = [
                ipaddress.ip_network(value.strip(), strict=False)
                for value in settings.admin_ip_allowlist.split(",")
                if value.strip()
            ]
        except ValueError:
            networks = []
        if (
            configured is None
            or len(configured.get_secret_value().encode()) < 32
            or not staff_id
            or not networks
        ):
            raise HTTPException(status_code=503, detail="Platform admin is not configured")
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not supplied:
            raise HTTPException(status_code=401, detail="Staff authentication required")
        if not hmac.compare_digest(supplied, configured.get_secret_value()):
            raise HTTPException(status_code=401, detail="Staff authentication required")
        # Deliberately use the socket peer. Forwarded headers are untrusted unless
        # a separately configured trusted-proxy chain is introduced.
        peer = request.client.host if request.client else None
        try:
            address = ipaddress.ip_address(peer or "")
        except ValueError:
            raise HTTPException(status_code=403, detail="Source address is not allowed") from None
        if not any(address in network for network in networks):
            raise HTTPException(status_code=403, detail="Source address is not allowed")
        return staff_id

    return authorize


def create_admin_router(
    settings: Settings, sessions: async_sessionmaker[AsyncSession] | None
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["platform-admin"])
    staff = _staff_auth(settings)

    def require_sessions() -> async_sessionmaker[AsyncSession]:
        if sessions is None:
            raise HTTPException(status_code=503, detail="Platform admin storage is unavailable")
        return sessions

    @router.get("/tenants", response_model=TenantList)
    async def tenants(
        _: Annotated[str, Depends(staff)],
        db_sessions: Annotated[async_sessionmaker[AsyncSession], Depends(require_sessions)],
    ) -> TenantList:
        async with db_sessions() as session:
            result = await session.execute(
                select(
                    Organization,
                    select(func.count(Membership.user_id))
                    .where(Membership.org_id == Organization.id, Membership.status == "active")
                    .correlate(Organization).scalar_subquery(),
                    select(func.count(Treasury.id))
                    .where(Treasury.org_id == Organization.id)
                    .correlate(Organization).scalar_subquery(),
                ).order_by(Organization.created_at.desc(), Organization.id)
            )
            rows = cast(list[tuple[Organization, int, int]], result.all())
        return TenantList(items=[
            TenantView(
                id=org.id, name=org.name, country=org.country, created_at=org.created_at,
                status=org.platform_status, active_members=members, treasuries=treasuries,
            ) for org, members, treasuries in rows
        ])

    @router.get("/tenants/{tenant_id}/health", response_model=TenantHealth)
    async def tenant_health(
        tenant_id: uuid.UUID,
        _: Annotated[str, Depends(staff)],
        db_sessions: Annotated[async_sessionmaker[AsyncSession], Depends(require_sessions)],
    ) -> TenantHealth:
        async with db_sessions() as session:
            org = await session.get(Organization, tenant_id)
            if org is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            members = await session.scalar(select(func.count(Membership.user_id)).where(
                Membership.org_id == tenant_id, Membership.status == "active"
            )) or 0
            treasuries = await session.scalar(select(func.count(Treasury.id)).where(
                Treasury.org_id == tenant_id
            )) or 0
        return TenantHealth(
            tenant_id=tenant_id, status=org.platform_status,
            active_members=members, treasuries=treasuries,
        )

    @router.post("/tenants/{tenant_id}/suspend", response_model=TenantView)
    async def suspend_tenant(
        tenant_id: uuid.UUID,
        request: Request,
        actor: Annotated[str, Depends(staff)],
        db_sessions: Annotated[async_sessionmaker[AsyncSession], Depends(require_sessions)],
    ) -> TenantView:
        async with db_sessions() as session, session.begin():
            org = await session.get(Organization, tenant_id, with_for_update=True)
            if org is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            org.platform_status = "suspended"
            members = await session.scalar(select(func.count(Membership.user_id)).where(
                Membership.org_id == tenant_id, Membership.status == "active"
            )) or 0
            treasuries = await session.scalar(select(func.count(Treasury.id)).where(
                Treasury.org_id == tenant_id
            )) or 0
            session.add(PlatformAdminEvent(
                org_id=tenant_id,
                actor_id=actor,
                action="tenant.suspended",
                data={"source_ip": request.client.host if request.client else None},
            ))
            response = TenantView(
                id=org.id, name=org.name, country=org.country, created_at=org.created_at,
                status=org.platform_status, active_members=members, treasuries=treasuries,
            )
        return response

    return router
