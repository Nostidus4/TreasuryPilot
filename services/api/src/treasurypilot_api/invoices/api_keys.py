from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rate_limit import RateLimiterUnavailable
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.invoices.models import InvoiceApiKey

CREATE_SCOPE = "invoices:create"
router = APIRouter(prefix="/v1/orgs/{organization_id}/api-keys", tags=["invoice API keys"])
_require_admin = require_role(OrganizationRole.ORG_ADMIN)


@dataclass(frozen=True, slots=True)
class InvoiceCreateAccess:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    api_key_id: uuid.UUID | None = None


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=1)
    expires_at: datetime | None = None


def _fail(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _fail(
            503,
            "API_KEYS_UNAVAILABLE",
            "API keys unavailable",
            "Key storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


async def require_invoice_create(
    organization_id: uuid.UUID,
    request: Request,
    authorization: str | None = Header(default=None),
) -> InvoiceCreateAccess:
    """Accept an operator session or a narrowly scoped inbound key."""
    if authorization is None:
        member = await require_member(organization_id, request)
        allowed = {OrganizationRole.OPERATOR.value, OrganizationRole.ORG_ADMIN.value}
        if not member.roles.intersection(allowed):
            raise _fail(
                403,
                "FORBIDDEN",
                "Forbidden",
                "Your organization role does not allow request creation.",
            )
        return InvoiceCreateAccess(member.organization_id, member.user_id)

    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.startswith("tp_live_"):
        raise _fail(401, "API_KEY_INVALID", "API key invalid", "The bearer credential is invalid.")
    digest = hashlib.sha256(token.encode()).digest()
    async with _sessions(request)() as session:
        key = await session.scalar(select(InvoiceApiKey).where(InvoiceApiKey.token_hash == digest))
        now = datetime.now(UTC)
        if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at <= now):
            raise _fail(
                401, "API_KEY_INVALID", "API key invalid", "The bearer credential is invalid."
            )
        if key.org_id != organization_id:
            raise _fail(
                403,
                "API_KEY_ORG_MISMATCH",
                "API key organization mismatch",
                "This key is not valid for this organization.",
            )
        if CREATE_SCOPE not in key.scopes:
            raise _fail(
                403,
                "API_KEY_SCOPE_REQUIRED",
                "API key scope required",
                "The key lacks invoices:create.",
            )
        limiter = getattr(request.app.state, "api_key_rate_limiter", None)
        if limiter is not None:
            try:
                result = await limiter.hit(
                    f"invoice-api-key:{key.id}", limit=60, window=timedelta(minutes=1)
                )
            except RateLimiterUnavailable:
                raise _fail(
                    503,
                    "RATE_LIMITER_UNAVAILABLE",
                    "Service unavailable",
                    "Request rate limiting is unavailable.",
                ) from None
            if not result.allowed:
                raise AuthFailure(
                    status=429,
                    code="RATE_LIMITED",
                    title="Too many requests",
                    detail="This API key exceeded its request rate limit.",
                    retry_after=result.retry_after,
                )
        key.last_used_at = now
        access = InvoiceCreateAccess(key.org_id, key.created_by, key.id)
        await session.commit()
        return access


class ApiKeyView(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


def _view(key: InvoiceApiKey) -> ApiKeyView:
    return ApiKeyView(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=list(key.scopes),
        created_at=key.created_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        last_used_at=key.last_used_at,
    )


@router.get("", openapi_extra={"x-organization-scoped": True})
async def list_api_keys(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_admin),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session:
        keys = await session.scalars(
            select(InvoiceApiKey)
            .where(InvoiceApiKey.org_id == member.organization_id)
            .order_by(InvoiceApiKey.created_at.desc())
        )
        return {"keys": [_view(key).model_dump(mode="json", by_alias=True) for key in keys]}


@router.post("", status_code=201, openapi_extra={"x-organization-scoped": True})
async def create_api_key(
    organization_id: uuid.UUID,
    payload: ApiKeyCreate,
    request: Request,
    member: MemberAccess = Depends(_require_admin),  # noqa: B008
) -> dict[str, object]:
    name = payload.name.strip()
    if not name:
        raise _fail(
            422, "API_KEY_NAME_INVALID", "API key name invalid", "Provide a non-empty key name."
        )
    if payload.scopes != [CREATE_SCOPE]:
        raise _fail(
            422,
            "API_KEY_SCOPE_INVALID",
            "API key scope invalid",
            "Only invoices:create can be granted.",
        )
    now = datetime.now(UTC)
    expiry = payload.expires_at
    if expiry is None:
        expiry = now + timedelta(days=90)
    if expiry.tzinfo is None or expiry <= now or expiry > now + timedelta(days=365):
        raise _fail(
            422,
            "API_KEY_EXPIRY_INVALID",
            "API key expiry invalid",
            "Expiry must be within the next 365 days.",
        )
    raw = "tp_live_" + secrets.token_urlsafe(32)
    key = InvoiceApiKey(
        id=uuid7(), org_id=member.organization_id, name=name,
        prefix=raw[:16], token_hash=hashlib.sha256(raw.encode()).digest(),
        scopes=[CREATE_SCOPE], created_by=member.user_id, expires_at=expiry,
    )
    async with _sessions(request)() as session, session.begin():
        session.add(key)
        await session.flush()
    return {"key": _view(key).model_dump(mode="json", by_alias=True), "secret": raw}


@router.delete("/{key_id}", openapi_extra={"x-organization-scoped": True})
async def revoke_api_key(
    organization_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_admin),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        key = await session.scalar(
            select(InvoiceApiKey)
            .where(InvoiceApiKey.id == key_id, InvoiceApiKey.org_id == member.organization_id)
            .with_for_update()
        )
        if key is None:
            raise _fail(404, "API_KEY_NOT_FOUND", "API key not found", "The key is unavailable.")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
    return {"key": _view(key).model_dump(mode="json", by_alias=True)}
