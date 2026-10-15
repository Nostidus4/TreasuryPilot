"""Emergency pause, resume and revoke (MDT-007).

POST /pause sets the backend flag in its own committed transaction before any on-chain step, so the
worker stops acting at once. ``onchainStatus`` stays ``Requested`` until the indexer sees the
module's ``Paused`` event, which makes it ``Effective``. Resume and revoke are Safe T governance
transactions: Owner only, so a Guardian is refused with 403.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
import uuid
from typing import Annotated, Any, cast
from urllib.error import URLError

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.execution.models import Operation, OperationStatus
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.governance import (
    build_pause_call,
    build_resume_call,
    build_revoke_call,
)
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.mandate.models import (
    BackendPause,
    GovernanceTxPurpose,
    GuardianSetup,
    GuardianSetupStatus,
    OnchainPauseStatus,
)
from treasurypilot_api.treasury.models import Treasury, TreasuryStatus
from treasurypilot_api.treasury.safe import RpcUnavailable

router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}",
    tags=["pause"],
)

# Operations that may still reach the chain; a pause cannot recall them, so they are listed.
_PENDING = (
    OperationStatus.NOT_SUBMITTED,
    OperationStatus.SUBMITTED,
    OperationStatus.PENDING,
    OperationStatus.UNKNOWN,
)


class PauseRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class RevokeRequest(ApiModel):
    # The owner types the organization name (a treasury has none); a click-through is not enough for an irreversible act.
    confirm_name: str = Field(alias="confirmName", min_length=1, max_length=200)


def _fail(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title="Pause request rejected", detail=detail)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _fail(503, "PAUSE_UNAVAILABLE", "Pause storage is not configured.")
    return cast(async_sessionmaker[AsyncSession], sessions)


def _governance(request: Request) -> GovernanceService:
    service = getattr(request.app.state, "governance_service", None)
    if service is None:
        raise _fail(503, "GOVERNANCE_UNAVAILABLE", "Governance storage is not configured.")
    return cast(GovernanceService, service)


def _module(treasury: Treasury) -> bytes:
    if treasury.module_address is None or len(treasury.module_address) != 20:
        raise _fail(409, "MODULE_NOT_READY", "Treasury module is not configured.")
    return bytes(treasury.module_address)


async def _pending_operations(
    session: AsyncSession, treasury_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Operation.id, Operation.request_id, Operation.kind, Operation.status)
        .where(Operation.treasury_id == treasury_id, Operation.status.in_(_PENDING))
        .order_by(Operation.created_at, Operation.id)
    )
    return [
        {
            "operationId": str(r.id),
            "requestId": str(r.request_id),
            "kind": r.kind.value,
            "status": r.status.value,
        }
        for r in rows
    ]


async def _load(
    session: AsyncSession, organization_id: uuid.UUID, treasury_id: uuid.UUID
) -> Treasury:
    treasury = await session.scalar(
        select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
    )
    if treasury is None:
        raise _fail(404, "TREASURY_NOT_FOUND", "Treasury not found.")
    return treasury


async def _org_name(session: AsyncSession, organization_id: uuid.UUID) -> str | None:
    return await session.scalar(select(Organization.name).where(Organization.id == organization_id))


async def _call_sentinel(request: Request, treasury_id: uuid.UUID) -> dict[str, Any] | None:
    """POST the signer's sentinel endpoint; ``None`` when no sentinel is configured."""
    settings = request.app.state.settings
    secret = settings.signer_shared_secret
    if not settings.signer_url or secret is None:
        return None
    http = urllib.request.Request(  # noqa: S310 - operator-configured URL
        settings.signer_url.rstrip("/") + "/sentinel/pause",
        data=json.dumps({"treasuryId": str(treasury_id)}).encode(),
        headers={"Content-Type": "application/json", "X-Signer-Secret": secret.get_secret_value()},
        method="POST",
    )

    def send() -> dict[str, Any]:
        # shortcut: urllib in a thread to avoid a new HTTP dependency, move to httpx if reused.
        with urllib.request.urlopen(http, timeout=10) as response:  # noqa: S310
            return cast(dict[str, Any], json.loads(response.read()))

    try:
        return await asyncio.to_thread(send)
    except (URLError, OSError, ValueError):
        # NOT_CONFIGURED (503) for this treasury, a refusal or an outage: all fall back to the Safe tx.
        return {"error": True}


@router.post("/pause", status_code=202)
async def pause_treasury(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: PauseRequest,
    request: Request,
    member: Annotated[
        MemberAccess, Depends(require_role(OrganizationRole.OWNER, OrganizationRole.GUARDIAN))
    ],
) -> dict[str, Any]:
    async with _sessions(request)() as session, session.begin():
        treasury = await _load(session, member.organization_id, treasury_id)
        module = _module(treasury)
        guardian_safe = await session.scalar(
            select(GuardianSetup.guardian_safe).where(
                GuardianSetup.treasury_id == treasury_id,
                GuardianSetup.status == GuardianSetupStatus.ACTIVE,
            )
        )
        row = await session.get(BackendPause, treasury_id)
        if row is None:
            row = BackendPause(
                treasury_id=treasury_id,
                org_id=member.organization_id,
                paused=True,
                reason=payload.reason,
                onchain_status=OnchainPauseStatus.REQUESTED,
                created_by=member.user_id,
                updated_by=member.user_id,
            )
            session.add(row)
        else:
            if not row.paused:  # a repeat pause keeps the first reason
                row.reason = payload.reason
            row.paused = True
            if row.onchain_status == OnchainPauseStatus.NOT_REQUESTED:
                row.onchain_status = OnchainPauseStatus.REQUESTED
            row.updated_by = member.user_id
        pending = await _pending_operations(session, treasury_id)
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="treasury.pause_requested",
                entity_type="treasury",
                entity_id=treasury_id,
                data={"reason": payload.reason, "pendingOperations": len(pending)},
            ),
        )
        onchain_status = row.onchain_status
    # The flag is committed above; the sentinel call can only add the on-chain pause.
    sentinel = await _call_sentinel(request, treasury_id)
    body: dict[str, Any] = {
        "backendPaused": True,
        "onchainStatus": onchain_status.value,
        "pendingTransactions": pending,
    }
    if sentinel is not None and "error" not in sentinel:
        body["onchain"] = (
            "ALREADY_PAUSED" if sentinel.get("alreadyPaused") else "SENTINEL_SUBMITTED"
        )
        body["sentinelTxHash"] = sentinel.get("txHash")
        return body
    body["onchain"] = "SENTINEL_FAILED" if sentinel is not None else "GUARDIAN_SAFE_TX_REQUIRED"
    call = build_pause_call(module)
    body["guardianTx"] = {
        "safeAddress": "0x" + bytes(guardian_safe).hex() if guardian_safe else None,
        "call": call.as_json(),
    }
    return body


@router.get("/pause")
async def pause_status(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> dict[str, Any]:
    async with _sessions(request)() as session:
        treasury = await _load(session, member.organization_id, treasury_id)
        row = await session.get(BackendPause, treasury_id)
        pending = await _pending_operations(session, treasury_id) if row and row.paused else []
    status = row.onchain_status if row else OnchainPauseStatus.NOT_REQUESTED
    return {
        "backendPaused": bool(row and row.paused),
        "onchainStatus": status.value,
        # Effective only once the indexer has seen the module's Paused event.
        "effective": status == OnchainPauseStatus.EFFECTIVE
        or treasury.status == TreasuryStatus.PAUSED,
        "reason": row.reason if row else None,
        "treasuryStatus": treasury.status.value,
        "pendingTransactions": pending,
    }


async def _governance_tx(
    request: Request,
    member: MemberAccess,
    treasury_id: uuid.UUID,
    purpose: GovernanceTxPurpose,
    action: str,
    check: Any,
) -> dict[str, Any]:
    async with _sessions(request)() as session:
        treasury = await _load(session, member.organization_id, treasury_id)
        row = await session.get(BackendPause, treasury_id)
        check(treasury, row, await _org_name(session, member.organization_id))
    module = _module(treasury)
    call = (
        build_resume_call(module)
        if purpose == GovernanceTxPurpose.RESUME
        else build_revoke_call(module)
    )
    try:
        governance = await _governance(request).create(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            purpose=purpose,
            calls=[call],
            entity_type="treasury",
            entity_id=treasury_id,
        )
    except GovernanceFailure as exc:
        raise _fail(exc.status, exc.code, exc.detail) from None
    except RpcUnavailable:
        raise _fail(503, "RPC_UNAVAILABLE", "Safe state could not be read from chain.") from None
    async with _sessions(request)() as session, session.begin():
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action=action,
                entity_type="treasury",
                entity_id=treasury_id,
                data={"governanceTxId": str(governance.get("governanceTx", governance).get("id"))},
            ),
        )
    return {"governanceTx": governance}


@router.post("/resume-tx", status_code=201)
async def resume_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    # Owner only: a Guardian may pause but never lift the pause (403).
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> dict[str, Any]:
    def check(treasury: Treasury, row: BackendPause | None, _org: str | None) -> None:
        if treasury.status == TreasuryStatus.REVOKED:
            raise _fail(409, "TREASURY_REVOKED", "A revoked treasury cannot be resumed.")
        if not (row and row.paused):
            raise _fail(409, "NOT_PAUSED", "The treasury is not paused.")
        if row.onchain_status != OnchainPauseStatus.EFFECTIVE:
            raise _fail(409, "PAUSE_NOT_EFFECTIVE", "The pause is not yet effective on-chain.")

    return await _governance_tx(
        request, member, treasury_id, GovernanceTxPurpose.RESUME, "treasury.resume_requested", check
    )


@router.post("/revoke-tx", status_code=201)
async def revoke_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: RevokeRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> dict[str, Any]:
    def check(treasury: Treasury, _row: BackendPause | None, org_name: str | None) -> None:
        if treasury.status == TreasuryStatus.REVOKED:
            raise _fail(409, "TREASURY_REVOKED", "The treasury is already revoked.")
        if payload.confirm_name != org_name:
            raise _fail(
                422, "CONFIRMATION_MISMATCH", "Type the exact organization name to confirm."
            )

    return await _governance_tx(
        request, member, treasury_id, GovernanceTxPurpose.REVOKE, "treasury.revoke_requested", check
    )
