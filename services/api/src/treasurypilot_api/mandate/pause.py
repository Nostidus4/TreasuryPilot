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
from typing import Annotated, Any, Literal, cast
from urllib.error import URLError

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy import case, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


class PendingTransaction(ApiModel):
    operation_id: str
    request_id: str
    kind: str
    status: str


class SafeCall(ApiModel):
    to: str
    value: str
    data: str
    operation: int


class GuardianTx(ApiModel):
    safe_address: str
    call: SafeCall


class PauseResponse(ApiModel):
    backend_paused: bool
    onchain_status: OnchainPauseStatus
    onchain: Literal[
        "SENTINEL_SUBMITTED", "ALREADY_PAUSED", "SENTINEL_FAILED", "GUARDIAN_SAFE_TX_REQUIRED"
    ]
    sentinel_tx_hash: str | None = None
    guardian_tx: GuardianTx | None = None
    pending_transactions: list[PendingTransaction]


class PauseStatusResponse(ApiModel):
    backend_paused: bool
    onchain_status: OnchainPauseStatus
    effective: bool
    reason: str | None
    treasury_status: TreasuryStatus
    pending_transactions: list[PendingTransaction]
    guardian_tx: GuardianTx | None = None


class PauseCancelResponse(ApiModel):
    backend_paused: bool
    onchain_status: OnchainPauseStatus


class GovernanceTxResponse(ApiModel):
    governance_tx: dict[str, Any]


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
) -> list[PendingTransaction]:
    rows = await session.execute(
        select(Operation.id, Operation.request_id, Operation.kind, Operation.status)
        .where(Operation.treasury_id == treasury_id, Operation.status.in_(_PENDING))
        .order_by(Operation.created_at, Operation.id)
    )
    return [
        PendingTransaction(
            operation_id=str(r.id),
            request_id=str(r.request_id or ""),  # a liquidity operation has no request
            kind=r.kind.value,
            status=r.status.value,
        )
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


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


_NO_REDIRECT = urllib.request.build_opener(_RefuseRedirect)


async def _call_sentinel(request: Request, treasury_id: uuid.UUID) -> dict[str, Any] | None:
    """POST the signer's sentinel endpoint; ``None`` when no sentinel is configured."""
    settings = request.app.state.settings
    secret = settings.signer_shared_secret
    if not settings.signer_url or secret is None:
        return None
    http = urllib.request.Request(  # noqa: S310 - scheme is validated as http(s) in Settings
        settings.signer_url.rstrip("/") + "/sentinel/pause",
        data=json.dumps({"treasuryId": str(treasury_id)}).encode(),
        headers={"Content-Type": "application/json", "X-Signer-Secret": secret.get_secret_value()},
        method="POST",
    )

    def send() -> dict[str, Any]:
        # shortcut: urllib in a thread (httpx is dev-only here); redirects are refused so the
        # secret header never follows one. Move to httpx if it becomes a runtime dependency.
        with _NO_REDIRECT.open(http, timeout=10) as response:
            return cast(dict[str, Any], json.loads(response.read()))

    try:
        return await asyncio.to_thread(send)
    except (URLError, OSError, ValueError):
        # NOT_CONFIGURED (503) for this treasury, a refusal or an outage: all fall back to the Safe tx.
        return {"error": True}


async def _upsert_pause(
    session: AsyncSession,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
) -> OnchainPauseStatus:
    """Set the flag atomically: two first pauses cannot collide on the primary key."""
    # Keep in sync with the worker's _PAUSE in recovery/circuit.py (raw-SQL twin of this upsert).
    table = BackendPause.__table__
    status_type = table.c.onchain_status.type
    insert = pg_insert(BackendPause).values(
        treasury_id=treasury_id,
        org_id=organization_id,
        paused=True,
        reason=reason,
        onchain_status=OnchainPauseStatus.REQUESTED,
        created_by=user_id,
        updated_by=user_id,
    )
    stmt = insert.on_conflict_do_update(
        index_elements=[table.c.treasury_id],
        set_={
            # a repeat pause keeps the first reason
            "reason": case((table.c.paused, table.c.reason), else_=insert.excluded.reason),
            "paused": True,
            "onchain_status": case(
                (
                    table.c.onchain_status == OnchainPauseStatus.NOT_REQUESTED,
                    literal(OnchainPauseStatus.REQUESTED, status_type),
                ),
                else_=table.c.onchain_status,
            ),
            "updated_by": user_id,
            "updated_at": func.now(),
            "version": table.c.version + 1,
        },
    ).returning(table.c.onchain_status)
    return cast(OnchainPauseStatus, (await session.execute(stmt)).scalar_one())


async def _guardian_safe(session: AsyncSession, treasury_id: uuid.UUID) -> str | None:
    safe = await session.scalar(
        select(GuardianSetup.guardian_safe).where(
            GuardianSetup.treasury_id == treasury_id,
            GuardianSetup.status == GuardianSetupStatus.ACTIVE,
        )
    )
    return "0x" + bytes(safe).hex() if safe else None


def _guardian_tx(safe: str | None, module: bytes) -> GuardianTx:
    if safe is None:
        raise _fail(
            409,
            "GUARDIAN_SAFE_MISSING",
            "The backend pause is active, but no active Guardian Safe is set up to submit the "
            "on-chain pause. Ask an Owner to complete Guardian setup.",
        )
    return GuardianTx(safe_address=safe, call=SafeCall(**build_pause_call(module).as_json()))


@router.post("/pause", status_code=202, response_model=PauseResponse)
async def pause_treasury(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: PauseRequest,
    request: Request,
    member: Annotated[
        MemberAccess, Depends(require_role(OrganizationRole.OWNER, OrganizationRole.GUARDIAN))
    ],
) -> PauseResponse:
    async with _sessions(request)() as session, session.begin():
        treasury = await _load(session, member.organization_id, treasury_id)
        module = _module(treasury)
        guardian_safe = await _guardian_safe(session, treasury_id)
        onchain_status = await _upsert_pause(
            session, member.organization_id, treasury_id, member.user_id, payload.reason
        )
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
    # The flag is committed above; the sentinel call can only add the on-chain pause.
    sentinel = await _call_sentinel(request, treasury_id)
    body = PauseResponse(
        backend_paused=True,
        onchain_status=onchain_status,
        onchain="GUARDIAN_SAFE_TX_REQUIRED",
        pending_transactions=pending,
    )
    if sentinel is not None and "error" not in sentinel:
        body.onchain = "ALREADY_PAUSED" if sentinel.get("alreadyPaused") else "SENTINEL_SUBMITTED"
        body.sentinel_tx_hash = sentinel.get("txHash")
        return body
    if sentinel is not None:
        body.onchain = "SENTINEL_FAILED"
    body.guardian_tx = _guardian_tx(guardian_safe, module)
    return body


@router.get("/pause", response_model=PauseStatusResponse)
async def pause_status(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> PauseStatusResponse:
    async with _sessions(request)() as session:
        treasury = await _load(session, member.organization_id, treasury_id)
        row = await session.get(BackendPause, treasury_id)
        pending = await _pending_operations(session, treasury_id) if row and row.paused else []
        status = row.onchain_status if row else OnchainPauseStatus.NOT_REQUESTED
        safe = (
            await _guardian_safe(session, treasury_id)
            if status == OnchainPauseStatus.REQUESTED
            else None
        )
    return PauseStatusResponse(
        backend_paused=bool(row and row.paused),
        onchain_status=status,
        # Effective only once the indexer has seen the module's Paused event.
        effective=status == OnchainPauseStatus.EFFECTIVE
        or treasury.status == TreasuryStatus.PAUSED,
        reason=row.reason if row else None,
        treasury_status=treasury.status,
        pending_transactions=pending,
        # Still Requested: the Guardian can submit the pause themselves. Omitted without a Safe.
        guardian_tx=_guardian_tx(safe, _module(treasury)) if safe else None,
    )


@router.post("/pause/cancel", response_model=PauseCancelResponse)
async def cancel_pause(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> PauseCancelResponse:
    """Lift a backend-only pause that never became effective on-chain (resume-tx needs Effective)."""
    async with _sessions(request)() as session, session.begin():
        treasury = await _load(session, member.organization_id, treasury_id)
        table = BackendPause.__table__
        # One conditional UPDATE: an indexer that makes the pause Effective meanwhile wins.
        cancelled = await session.scalar(
            update(BackendPause)
            .where(
                table.c.treasury_id == treasury_id,
                table.c.paused,
                table.c.onchain_status != OnchainPauseStatus.EFFECTIVE,
            )
            .values(
                paused=False,
                onchain_status=OnchainPauseStatus.NOT_REQUESTED,
                updated_by=member.user_id,
                updated_at=func.now(),
                version=table.c.version + 1,
            )
            .returning(table.c.treasury_id)
            .execution_options(synchronize_session=False)
        )
        if cancelled is None or treasury.status in (TreasuryStatus.PAUSED, TreasuryStatus.REVOKED):
            raise _fail(
                409,
                "PAUSE_NOT_CANCELLABLE",
                "There is no backend-only pause to cancel; use resume-tx for an effective pause.",
            )
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="treasury.pause_cancelled",
                entity_type="treasury",
                entity_id=treasury_id,
                data={},
            ),
        )
    return PauseCancelResponse(
        backend_paused=False, onchain_status=OnchainPauseStatus.NOT_REQUESTED
    )


async def _governance_tx(
    request: Request,
    member: MemberAccess,
    treasury_id: uuid.UUID,
    purpose: GovernanceTxPurpose,
    action: str,
    check: Any,
) -> GovernanceTxResponse:
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
    return GovernanceTxResponse(governance_tx=governance)


@router.post("/resume-tx", status_code=201, response_model=GovernanceTxResponse)
async def resume_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    # Owner only: a Guardian may pause but never lift the pause (403).
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> GovernanceTxResponse:
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


@router.post("/revoke-tx", status_code=201, response_model=GovernanceTxResponse)
async def revoke_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: RevokeRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> GovernanceTxResponse:
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
