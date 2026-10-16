"""ERP integration API: connect (OAuth), settings, sync and sync status (REC-L01)."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.integrations.erp.models import ErpConnection, ErpSyncRecord
from treasurypilot_api.integrations.erp.service import Actor, ErpService, ErpServiceError

router = APIRouter(prefix="/v1/orgs/{organization_id}/integrations/erp", tags=["erp"])

_R = OrganizationRole
_read = require_role(_R.FINANCE, _R.OWNER, _R.ORG_ADMIN)
_connect = require_role(_R.OWNER, _R.ORG_ADMIN)
_sync = require_role(_R.FINANCE, _R.OWNER, _R.ORG_ADMIN)
_SCOPED = {"x-organization-scoped": True}


class CallbackRequest(ApiModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=4096)


class SettingsRequest(ApiModel):
    payment_account_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class SyncRequest(ApiModel):
    reconciliation_id: uuid.UUID


def _service(request: Request) -> ErpService:
    service = getattr(request.app.state, "erp_service", None)
    if service is None:
        raise AuthFailure(
            status=503,
            code="ERP_UNAVAILABLE",
            title="Erp Unavailable",
            detail="ERP integrations are not configured.",
        )
    return cast(ErpService, service)


def _fail(error: ErpServiceError) -> AuthFailure:
    return AuthFailure(
        status=error.status,
        code=error.code,
        title=error.code.replace("_", " ").title(),
        detail=error.detail,
    )


def _connection_view(row: ErpConnection) -> dict[str, object]:
    # Tokens never leave the server.
    return {
        "provider": row.provider,
        "status": row.status,
        "tenantName": row.tenant_name,
        "paymentAccountCode": row.payment_account_code,
        "connectedAt": row.created_at.isoformat(),
    }


def _record_view(row: ErpSyncRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "reconciliationId": str(row.reconciliation_id),
        "kind": row.kind,
        "status": row.status,
        "externalId": row.external_id,
        "externalStatus": row.external_status,
        "attempts": row.attempts,
        "nextAttemptAt": row.next_attempt_at.isoformat(),
        "lastError": row.last_error,
    }


@router.get("/providers", openapi_extra=_SCOPED)
async def list_providers(
    request: Request, member: Annotated[MemberAccess, Depends(_read)]
) -> dict[str, object]:
    service: ErpService | None = getattr(request.app.state, "erp_service", None)
    items: list[dict[str, object]] = []
    for key in service.provider_keys() if service else []:
        assert service is not None
        row = await service.get_connection(member.organization_id, key)
        items.append(
            {
                "provider": key,
                "name": service.provider(key).display_name,
                "connection": _connection_view(row) if row else None,
            }
        )
    return {"items": items}


@router.post("/{provider}/authorize", openapi_extra=_SCOPED)
async def authorize(
    provider: str, request: Request, member: Annotated[MemberAccess, Depends(_connect)]
) -> dict[str, str]:
    try:
        url = _service(request).authorize_url(provider, member.organization_id, member.user_id)
    except ErpServiceError as error:
        raise _fail(error) from None
    return {"url": url}


@router.post("/{provider}/callback", openapi_extra=_SCOPED)
async def callback(
    provider: str,
    body: CallbackRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_connect)],
) -> dict[str, object]:
    try:
        row = await _service(request).connect(
            provider, member.organization_id, member.user_id, body.code, body.state
        )
    except ErpServiceError as error:
        raise _fail(error) from None
    return _connection_view(row)


@router.put("/{provider}/settings", openapi_extra=_SCOPED)
async def put_settings(
    provider: str,
    body: SettingsRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_connect)],
) -> dict[str, object]:
    try:
        row = await _service(request).set_payment_account(
            member.organization_id, member.user_id, provider, body.payment_account_code
        )
    except ErpServiceError as error:
        raise _fail(error) from None
    return _connection_view(row)


@router.delete("/{provider}", status_code=204, openapi_extra=_SCOPED)
async def disconnect(
    provider: str, request: Request, member: Annotated[MemberAccess, Depends(_connect)]
) -> None:
    try:
        await _service(request).disconnect(member.organization_id, member.user_id, provider)
    except ErpServiceError as error:
        raise _fail(error) from None


@router.post("/{provider}/sync", openapi_extra=_SCOPED)
async def sync(
    provider: str,
    body: SyncRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_sync)],
) -> dict[str, object]:
    try:
        records = await _service(request).sync(
            member.organization_id, Actor(member.user_id), provider, body.reconciliation_id
        )
    except ErpServiceError as error:
        raise _fail(error) from None
    return {"items": [_record_view(r) for r in records]}


@router.post("/{provider}/retry", openapi_extra=_SCOPED)
async def retry(
    provider: str, request: Request, member: Annotated[MemberAccess, Depends(_sync)]
) -> dict[str, object]:
    service = _service(request)
    try:
        service.provider(provider)
        records = await service.retry_due(member.organization_id)
    except ErpServiceError as error:
        raise _fail(error) from None
    return {"items": [_record_view(r) for r in records]}


@router.get("/{provider}/records", openapi_extra=_SCOPED)
async def list_records(
    provider: str, request: Request, member: Annotated[MemberAccess, Depends(_read)]
) -> dict[str, object]:
    try:
        records = await _service(request).records(member.organization_id, provider)
    except ErpServiceError as error:
        raise _fail(error) from None
    return {"items": [_record_view(r) for r in records]}
