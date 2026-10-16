from __future__ import annotations

import hmac
import ipaddress
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import AwareDatetime, Field, computed_field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.admin.billing import (
    BillingError,
    create_plan,
    generate_invoices,
    subscribe,
)
from treasurypilot_api.admin.billing_api import (
    InvoiceView,
    PlanView,
    SubscriptionView,
    invoice_view,
    plan_view,
    subscription_view,
)
from treasurypilot_api.admin.billing_models import BillingInvoiceLine, BillingPlan
from treasurypilot_api.admin.models import PlatformAdminEvent, SupportGrant, UsageMonthly
from treasurypilot_api.admin.usage import parse_month, recompute_month
from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.compliance.models import OrgDataRegion
from treasurypilot_api.compliance.regions import RegionError
from treasurypilot_api.compliance.residency import ResidencyService
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import Membership, Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.treasury.models import Treasury

logger = logging.getLogger(__name__)

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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


class UsageView(ApiModel):
    org_id: uuid.UUID
    month: str
    asset_id: uuid.UUID
    paid_count: int = Field(description="Requests whose first Paid event is in this UTC month.")
    paid_volume: str = Field(
        description=(
            "Sum of the approved request amount for this asset, in integer base units as a "
            "decimal string. Reconciliation lines are not metered yet."
        )
    )


class UsageList(ApiModel):
    items: list[UsageView]


def _usage_view(row: UsageMonthly) -> UsageView:
    return UsageView(
        org_id=row.org_id,
        month=row.month.strftime("%Y-%m"),
        asset_id=row.asset_id,
        paid_count=row.paid_count,
        paid_volume=str(int(row.paid_volume)),
    )


_MAX_FEE_MINOR = 10**12


class PlanRequest(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    base_fee_minor: int = Field(ge=0, le=_MAX_FEE_MINOR)
    per_request_fee_minor: int = Field(ge=0, le=_MAX_FEE_MINOR)


class SubscribeRequest(ApiModel):
    plan_id: uuid.UUID
    payment_method: Literal["card", "bank_transfer"] = "card"


class InvoiceRunView(ApiModel):
    month: str
    created: list[InvoiceView]


def _billing_http_error(error: BillingError) -> HTTPException:
    status = 404 if error.code.endswith("NOT_FOUND") else 409
    return HTTPException(status_code=status, detail=error.detail)


class SupportGrantRequest(ApiModel):
    staff_user: str = Field(min_length=1, max_length=200)
    duration_hours: int = Field(default=24, ge=1, le=72)

    @field_validator("staff_user")
    @classmethod
    def normalize_staff_user(cls, value: str) -> str:
        clean = value.strip().lower()  # staff ids are matched case-insensitively
        if not _EMAIL.fullmatch(clean):
            raise ValueError("staff_user must be an email address")
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["active", "expired", "revoked"]:
        if self.revoked_at is not None:
            return "revoked"
        return "expired" if self.expires_at <= datetime.now(UTC) else "active"


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


class DataRegionRequest(ApiModel):
    region: str = Field(min_length=2, max_length=32)


class DataRegionView(ApiModel):
    org_id: uuid.UUID
    region: str | None = Field(description="Pinned data region; null when the org is unpinned.")
    pinned_by: str | None = None
    pinned_at: AwareDatetime | None = None
    available_regions: list[str]


def _region_http_error(error: RegionError) -> HTTPException:
    return HTTPException(
        status_code=error.status, detail={"code": error.code, "detail": str(error)}
    )


async def _data_region_view(
    session: AsyncSession, residency: ResidencyService, org_id: uuid.UUID
) -> DataRegionView:
    pin = await session.get(OrgDataRegion, org_id)
    return DataRegionView(
        org_id=org_id,
        region=pin.region if pin else None,
        pinned_by=pin.pinned_by if pin else None,
        pinned_at=pin.pinned_at if pin else None,
        available_regions=list(residency.registry.names),
    )


def create_admin_router(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession] | None,
    residency: ResidencyService | None = None,
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

    @router.get("/tenants/{tenant_id}/data-region", response_model=DataRegionView)
    async def tenant_data_region(
        tenant_id: uuid.UUID,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> DataRegionView:
        if residency is None:
            raise HTTPException(status_code=503, detail="Data residency is not configured")
        async with db_sessions() as session:
            if await session.get(Organization, tenant_id) is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            return await _data_region_view(session, residency, tenant_id)

    @router.put("/tenants/{tenant_id}/data-region", response_model=DataRegionView)
    async def pin_tenant_data_region(
        tenant_id: uuid.UUID,
        payload: DataRegionRequest,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> DataRegionView:
        """Pin a tenant's stored data to one region. A pin is permanent (409 to change)."""
        if residency is None:
            raise HTTPException(status_code=503, detail="Data residency is not configured")
        try:
            async with db_sessions() as session, session.begin():
                try:
                    await residency.pin(session, tenant_id, payload.region, actor)
                except LookupError:
                    raise HTTPException(status_code=404, detail="Tenant not found") from None
                return await _data_region_view(session, residency, tenant_id)
        except RegionError as error:
            raise _region_http_error(error) from error

    @router.get("/usage", response_model=UsageList)
    async def usage(
        month: str = Query(pattern=_MONTH_PATTERN),
        org_id: uuid.UUID | None = None,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> UsageList:
        query = select(UsageMonthly).where(UsageMonthly.month == parse_month(month))
        if org_id is not None:
            query = query.where(UsageMonthly.org_id == org_id)
        async with db_sessions() as session:
            rows = await session.scalars(query.order_by(UsageMonthly.org_id, UsageMonthly.asset_id))
            result = UsageList(items=[_usage_view(r) for r in rows])
        logger.info("admin.usage_read", extra={"actor": actor, "month": month})
        return result

    @router.post("/usage/{month}/recompute", response_model=UsageList)
    async def recompute_usage(
        request: Request,
        month: str = Path(pattern=_MONTH_PATTERN),
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> UsageList:
        async with db_sessions() as session, session.begin():
            rows = await recompute_month(session, parse_month(month))
            result = UsageList(items=[_usage_view(r) for r in rows])
            orgs = sorted({str(r.org_id) for r in rows})
            # platform_admin_events.org_id is NOT NULL: one event per affected org.
            for org_id in sorted({r.org_id for r in rows}):
                session.add(
                    PlatformAdminEvent(
                        org_id=org_id,
                        actor_id=actor,
                        action="usage.recomputed",
                        data={
                            "month": month,
                            "source_ip": request.client.host if request.client else None,
                            "orgs": orgs,
                        },
                    )
                )
        logger.info("admin.usage_recomputed", extra={"actor": actor, "month": month})
        return result

    @router.post("/billing/plans", response_model=PlanView, status_code=201)
    async def create_billing_plan(
        payload: PlanRequest,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> PlanView:
        try:
            async with db_sessions() as session, session.begin():
                plan = await create_plan(session, **payload.model_dump())
                view = plan_view(plan)
        except BillingError as error:
            raise _billing_http_error(error) from error
        logger.info("admin.billing_plan_created", extra={"actor": actor, "plan": payload.code})
        return view

    @router.get("/billing/plans", response_model=list[PlanView])
    async def list_billing_plans(
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> list[PlanView]:
        async with db_sessions() as session:
            plans = await session.scalars(select(BillingPlan).order_by(BillingPlan.code))
            return [plan_view(plan) for plan in plans]

    @router.put("/tenants/{tenant_id}/subscription", response_model=SubscriptionView)
    async def set_subscription(
        request: Request,
        tenant_id: uuid.UUID,
        payload: SubscribeRequest,
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> SubscriptionView:
        try:
            async with db_sessions() as session, session.begin():
                if await session.get(Organization, tenant_id) is None:
                    raise HTTPException(status_code=404, detail="Tenant not found")
                subscription = await subscribe(
                    session,
                    org_id=tenant_id,
                    plan_id=payload.plan_id,
                    payment_method=payload.payment_method,
                    now=datetime.now(UTC),
                )
                plan = await session.get(BillingPlan, payload.plan_id)
                assert plan is not None
                session.add(
                    PlatformAdminEvent(
                        org_id=tenant_id,
                        actor_id=actor,
                        action="billing.subscription_set",
                        data={
                            "plan_id": str(plan.id),
                            "payment_method": payload.payment_method,
                            "source_ip": request.client.host if request.client else None,
                        },
                    )
                )
                view = subscription_view(subscription, plan)
        except BillingError as error:
            raise _billing_http_error(error) from error
        return view

    @router.post("/billing/{month}/invoices", response_model=InvoiceRunView)
    async def run_invoices(
        request: Request,
        month: str = Path(pattern=_MONTH_PATTERN),
        actor: str = staff_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> InvoiceRunView:
        """Invoice a completed UTC month. Idempotent: existing invoices are never changed."""
        try:
            async with db_sessions() as session, session.begin():
                invoices = await generate_invoices(
                    session, parse_month(month), now=datetime.now(UTC)
                )
                lines = {
                    invoice.id: list(
                        await session.scalars(
                            select(BillingInvoiceLine)
                            .where(BillingInvoiceLine.invoice_id == invoice.id)
                            .order_by(BillingInvoiceLine.kind)
                        )
                    )
                    for invoice in invoices
                }
                for invoice in invoices:
                    session.add(
                        PlatformAdminEvent(
                            org_id=invoice.org_id,
                            actor_id=actor,
                            action="billing.invoice_issued",
                            data={
                                "month": month,
                                "invoice_id": str(invoice.id),
                                "total_minor": invoice.total_minor,
                                "currency": invoice.currency,
                                "source_ip": request.client.host if request.client else None,
                            },
                        )
                    )
                result = InvoiceRunView(
                    month=month, created=[invoice_view(i, lines[i.id]) for i in invoices]
                )
        except BillingError as error:
            raise _billing_http_error(error) from error
        return result

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
                    func.lower(SupportGrant.staff_user) == actor.strip().lower(),
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
            await write_audit(
                session,
                org_id=tenant_id,
                actor=AuditActor(AuditActorType.SYSTEM, actor),
                action="platform.support.read",
                entity=AuditEntity("support_grant", grant.id),
                data={"staff_user": actor, "grant_id": str(grant.id), "scope": grant.scope},
            )
            result = SupportSummary(tenant=_view(org, members, treasuries), grant_id=grant.id)
        logger.info(
            "admin.support_read",
            extra={"actor": actor, "tenant_id": str(tenant_id), "grant_id": str(grant.id)},
        )
        return result

    return router


def create_data_region_router(
    sessions: async_sessionmaker[AsyncSession] | None, residency: ResidencyService | None
) -> APIRouter:
    """Let tenant administrators see where their data is pinned (read-only)."""

    router = APIRouter(prefix="/v1/orgs/{organization_id}/data-region", tags=["compliance"])
    reader = Depends(
        require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER, OrganizationRole.AUDITOR)
    )

    @router.get("", response_model=DataRegionView, openapi_extra={"x-organization-scoped": True})
    async def get_data_region(member: MemberAccess = reader) -> DataRegionView:
        if sessions is None or residency is None:
            raise HTTPException(status_code=503, detail="Data residency is not configured")
        async with sessions() as session:
            return await _data_region_view(session, residency, member.organization_id)

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
        expires_at = now + timedelta(hours=payload.duration_hours)
        async with db_sessions() as session, session.begin():
            # Idempotent: reuse (and at most extend) the active grant for this staff member.
            # shortcut: no unique index, so two concurrent first-time POSTs can still both insert.
            grant = await session.scalar(
                select(SupportGrant)
                .where(
                    SupportGrant.org_id == member.organization_id,
                    func.lower(SupportGrant.staff_user) == payload.staff_user,
                    SupportGrant.revoked_at.is_(None),
                    SupportGrant.expires_at > now,
                )
                .order_by(SupportGrant.expires_at.desc())
                .limit(1)
                .with_for_update()
            )
            if grant is None:
                grant = SupportGrant(
                    id=uuid.uuid4(),
                    org_id=member.organization_id,
                    staff_user=payload.staff_user,
                    scope="read",
                    expires_at=expires_at,
                    granted_by=member.user_id,
                    created_at=now,
                )
                session.add(grant)
            elif expires_at > grant.expires_at:
                grant.expires_at = expires_at
            else:
                return SupportGrantView.model_validate(grant, from_attributes=True)
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
        limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
        member: MemberAccess = consent_dependency,
        db_sessions: async_sessionmaker[AsyncSession] = sessions_dependency,
    ) -> list[SupportGrantView]:
        async with db_sessions() as session:
            grants = await session.scalars(
                select(SupportGrant)
                .where(SupportGrant.org_id == member.organization_id)
                .order_by(SupportGrant.created_at.desc(), SupportGrant.id)
                .limit(limit)
            )
            return [
                SupportGrantView.model_validate(grant, from_attributes=True) for grant in grants
            ]

    @router.delete("/{grant_id}", status_code=204)
    async def revoke_support_grant(
        grant_id: uuid.UUID,
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
