"""Organization-admin controls for outbound webhook endpoints and dead letters."""

from __future__ import annotations

import ipaddress
import secrets
import uuid
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.notifications.models import WebhookDelivery, WebhookEndpoint
from treasurypilot_core.privacy import (
    EncryptionConfigurationError,
    FieldCipher,
    FieldEncryptionKey,
)

router = APIRouter(prefix="/v1/orgs/{organization_id}/webhooks", tags=["webhooks"])
_ADMIN = require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)
_SECRET_CONTEXT = "webhook_endpoints:{}:secret"


class CreateWebhookRequest(ApiModel):
    url: str = Field(min_length=9, max_length=2048)
    event_types: list[str] = Field(min_length=1, max_length=100)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("webhook URL must be an HTTPS URL without credentials")
        if parsed.fragment:
            raise ValueError("webhook URL cannot contain a fragment")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("webhook URL cannot target a non-public IP address")
        return value.strip()

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        result = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 80 for value in result):
            raise ValueError("event types must be non-empty names of at most 80 characters")
        return result


class UpdateWebhookRequest(ApiModel):
    enabled: bool


class WebhookEndpointView(ApiModel):
    id: uuid.UUID
    url: str
    event_types: list[str]
    enabled: bool
    created_at: datetime
    secret: str | None = None


class WebhookDeliveryView(ApiModel):
    id: uuid.UUID
    event_id: uuid.UUID
    endpoint_id: uuid.UUID
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error: str | None
    created_at: datetime


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "review_sessions", None)
    if sessions is None:
        raise AuthFailure(
            status=503,
            code="WEBHOOKS_UNAVAILABLE",
            title="Webhooks unavailable",
            detail="Webhook storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


def _cipher(request: Request) -> FieldCipher:
    cipher = getattr(request.app.state, "webhook_cipher", None)
    if cipher is None:
        try:
            cipher = FieldCipher(FieldEncryptionKey.from_environment())
        except EncryptionConfigurationError:
            cipher = None
    if cipher is None:
        raise AuthFailure(
            status=503,
            code="WEBHOOK_ENCRYPTION_UNAVAILABLE",
            title="Webhooks unavailable",
            detail="Encrypted webhook secret storage is not configured.",
        )
    return cast(FieldCipher, cipher)


@router.post(
    "",
    response_model=WebhookEndpointView,
    status_code=201,
    openapi_extra={"x-organization-scoped": True},
)
async def create_endpoint(
    payload: CreateWebhookRequest,
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> WebhookEndpointView:
    endpoint_id = uuid.uuid4()
    secret = secrets.token_urlsafe(32)
    ciphertext = _cipher(request).encrypt(
        secret.encode(), context=_SECRET_CONTEXT.format(endpoint_id).encode()
    )
    endpoint = WebhookEndpoint(
        id=endpoint_id,
        org_id=member.organization_id,
        url=payload.url,
        secret_ciphertext=str(ciphertext).encode(),
        event_types=payload.event_types,
    )
    async with _sessions(request)() as session, session.begin():
        session.add(endpoint)
        await session.flush()
    return WebhookEndpointView(
        id=endpoint.id,
        url=endpoint.url,
        event_types=endpoint.event_types,
        enabled=endpoint.enabled,
        created_at=endpoint.created_at,
        secret=secret,
    )


@router.get(
    "", response_model=list[WebhookEndpointView], openapi_extra={"x-organization-scoped": True}
)
async def list_endpoints(
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> list[WebhookEndpointView]:
    async with _sessions(request)() as session:
        rows = await session.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.org_id == member.organization_id)
            .order_by(WebhookEndpoint.created_at, WebhookEndpoint.id)
        )
        return [
            WebhookEndpointView(
                id=row.id,
                url=row.url,
                event_types=row.event_types,
                enabled=row.enabled,
                created_at=row.created_at,
            )
            for row in rows
        ]


@router.delete("/{endpoint_id}", status_code=204, openapi_extra={"x-organization-scoped": True})
async def disable_endpoint(
    endpoint_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> Response:
    async with _sessions(request)() as session, session.begin():
        disabled_id = await session.scalar(
            update(WebhookEndpoint)
            .where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.org_id == member.organization_id,
                WebhookEndpoint.enabled.is_(True),
            )
            .values(enabled=False)
            .returning(WebhookEndpoint.id)
        )
        if disabled_id is None:
            raise AuthFailure(
                status=404,
                code="WEBHOOK_NOT_FOUND",
                title="Not found",
                detail="Webhook endpoint not found.",
            )
    return Response(status_code=204)


@router.patch(
    "/{endpoint_id}",
    response_model=WebhookEndpointView,
    openapi_extra={"x-organization-scoped": True},
)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: UpdateWebhookRequest,
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> WebhookEndpointView:
    async with _sessions(request)() as session, session.begin():
        endpoint = await session.scalar(
            select(WebhookEndpoint)
            .where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.org_id == member.organization_id,
            )
            .with_for_update()
        )
        if endpoint is None:
            raise AuthFailure(
                status=404,
                code="WEBHOOK_NOT_FOUND",
                title="Not found",
                detail="Webhook endpoint not found.",
            )
        endpoint.enabled = payload.enabled
        await session.flush()
        return WebhookEndpointView(
            id=endpoint.id,
            url=endpoint.url,
            event_types=endpoint.event_types,
            enabled=endpoint.enabled,
            created_at=endpoint.created_at,
        )


@router.get(
    "/dead-letters",
    response_model=list[WebhookDeliveryView],
    openapi_extra={"x-organization-scoped": True},
)
async def list_dead_letters(
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> list[WebhookDeliveryView]:
    async with _sessions(request)() as session:
        rows = await session.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.org_id == member.organization_id, WebhookDelivery.status == "dead"
            )
            .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
            .limit(100)
        )
        return [WebhookDeliveryView.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "/dead-letters/{delivery_id}/replay",
    response_model=WebhookDeliveryView,
    openapi_extra={"x-organization-scoped": True},
)
async def replay_dead_letter(
    delivery_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_ADMIN),  # noqa: B008
) -> WebhookDeliveryView:
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.org_id == member.organization_id,
                WebhookDelivery.status == "dead",
            )
            .with_for_update()
        )
        if row is None:
            raise AuthFailure(
                status=404,
                code="WEBHOOK_DELIVERY_NOT_FOUND",
                title="Not found",
                detail="Dead-letter delivery not found.",
            )
        endpoint_enabled = await session.scalar(
            select(WebhookEndpoint.enabled).where(
                WebhookEndpoint.id == row.endpoint_id,
                WebhookEndpoint.org_id == member.organization_id,
            )
        )
        if not endpoint_enabled:
            raise AuthFailure(
                status=409,
                code="WEBHOOK_DISABLED",
                title="Webhook disabled",
                detail="Enable the endpoint before replaying this delivery.",
            )
        row.status = "pending"
        row.attempt_count = 0
        row.next_attempt_at = datetime.now(UTC)
        row.last_error = None
        row.last_status_code = None
        await session.flush()
        return WebhookDeliveryView.model_validate(row, from_attributes=True)
