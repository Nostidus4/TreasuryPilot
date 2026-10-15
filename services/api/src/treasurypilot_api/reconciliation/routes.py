"""Finance reconciliation: list, evidence, match, discrepancy and resolve (REC-003, M11 §5-§6)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.reconciliation.models import Reconciliation, ReconciliationLine
from treasurypilot_core.reconciliation_evidence import (
    FACTS_SQL,
    ReconciliationFacts,
    is_finalized,
    missing_evidence,
)

router = APIRouter(prefix="/v1/orgs/{organization_id}/reconciliations", tags=["reconciliation"])

_R = OrganizationRole
_DAY = timedelta(days=1)
_read_roles = require_role(_R.FINANCE, _R.OWNER, _R.ORG_ADMIN)
_detail_roles = require_role(_R.FINANCE, _R.OWNER, _R.ORG_ADMIN, _R.OPERATOR)
_finance = require_role(_R.FINANCE)
_resolve_roles = require_role(_R.FINANCE, _R.OWNER)


class NoteRequest(ApiModel):
    note: str | None = Field(default=None, max_length=4_000)

    @field_validator("note")
    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class ResolveRequest(NoteRequest):
    acknowledge: bool = False


def _failure(status: int, code: str, detail: str, **extensions: object) -> AuthFailure:
    return AuthFailure(
        status=status,
        code=code,
        title=code.replace("_", " ").title(),
        detail=detail,
        extensions=extensions,
    )


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _failure(503, "RECONCILIATION_UNAVAILABLE", "Reconciliation storage is unavailable.")
    return cast(async_sessionmaker[AsyncSession], sessions)


def _hex(value: bytes | None) -> str | None:
    return None if value is None else "0x" + value.hex()


def _view(row: Reconciliation) -> dict[str, object]:
    return {
        "id": str(row.id),
        "treasuryId": str(row.treasury_id),
        "requestId": str(row.request_id),
        "status": row.status,
        "version": row.version,
        "createdAt": row.created_at.isoformat(),
        "matchedBy": row.matched_by,
        "matchedUserId": str(row.matched_user_id) if row.matched_user_id else None,
        "matchedAt": row.matched_at.isoformat() if row.matched_at else None,
        "note": row.note,
        "resolutionNote": row.resolution_note,
        "ownerAckAt": row.owner_ack_at.isoformat() if row.owner_ack_at else None,
        "finalizedAt": row.finalized_at.isoformat() if row.finalized_at else None,
        "easUid": row.eas_uid,
    }


async def _facts(session: AsyncSession, reconciliation_id: uuid.UUID) -> ReconciliationFacts:
    row = (await session.execute(text(FACTS_SQL), {"rid": reconciliation_id})).mappings().one()
    return ReconciliationFacts(**row)


async def _lock(
    session: AsyncSession, member: MemberAccess, reconciliation_id: uuid.UUID, if_match: str | None
) -> Reconciliation:
    row = await session.scalar(
        select(Reconciliation)
        .where(
            Reconciliation.id == reconciliation_id, Reconciliation.org_id == member.organization_id
        )
        .with_for_update()
    )
    if row is None:
        raise _failure(404, "RECONCILIATION_NOT_FOUND", "The reconciliation is unavailable.")
    if if_match is not None and if_match != f'"{row.version}"':
        raise _failure(412, "VERSION_CONFLICT", "The reconciliation changed. Reload it.")
    return row


async def _finalized_block(request: Request, session: AsyncSession, request_id: uuid.UUID) -> int:
    chain_id = await session.scalar(
        text("SELECT chain_id FROM payment_requests WHERE id = :id"), {"id": request_id}
    )
    provider = getattr(request.app.state, "fee_history_provider", None)  # the shared RPC client
    try:
        assert provider is not None
        block = await provider.call(chain_id, "eth_getBlockByNumber", ["finalized", False])
        return int(block["number"], 16)
    except Exception as error:
        raise _failure(
            503, "FINALITY_UNAVAILABLE", "The chain's finalized block could not be read."
        ) from error


async def _audit(
    session: AsyncSession, member: MemberAccess, row: Reconciliation, action: str, **data: object
) -> None:
    await log_audit_event(
        session,
        AuditEvent(
            org_id=member.organization_id,
            actor_id=member.user_id,
            action=f"reconciliation.{action}",
            entity_type="reconciliation",
            entity_id=row.id,
            data={"requestId": str(row.request_id), **data},
        ),
    )


def _bump(row: Reconciliation) -> dict[str, object]:
    row.version += 1
    return {"status": row.status, "version": row.version}


@router.get("", openapi_extra={"x-organization-scoped": True})
async def list_reconciliations(
    request: Request,
    member: Annotated[MemberAccess, Depends(_read_roles)],
    status: Literal["Pending", "Matched", "Discrepancy"] | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> dict[str, object]:
    query = select(Reconciliation).where(Reconciliation.org_id == member.organization_id)
    if status:
        query = query.where(Reconciliation.status == status)
    if from_:
        query = query.where(
            Reconciliation.created_at >= datetime.combine(from_, datetime.min.time(), UTC)
        )
    if to:  # inclusive UTC day
        query = query.where(
            Reconciliation.created_at < datetime.combine(to, datetime.min.time(), UTC) + _DAY
        )
    async with _sessions(request)() as session:
        rows = (await session.scalars(query.order_by(Reconciliation.created_at.desc()))).all()
    return {"items": [_view(row) for row in rows]}


@router.get("/{reconciliation_id}", openapi_extra={"x-organization-scoped": True})
async def get_reconciliation(
    reconciliation_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(_detail_roles)],
) -> dict[str, object]:
    async with _sessions(request)() as session:
        row = await session.scalar(
            select(Reconciliation).where(
                Reconciliation.id == reconciliation_id,
                Reconciliation.org_id == member.organization_id,
            )
        )
        if row is None:
            raise _failure(404, "RECONCILIATION_NOT_FOUND", "The reconciliation is unavailable.")
        lines = (
            await session.scalars(
                select(ReconciliationLine)
                .where(ReconciliationLine.reconciliation_id == row.id)
                .order_by(ReconciliationLine.block_number, ReconciliationLine.classification)
            )
        ).all()
        facts = await _facts(session, row.id)
        params = {"req": row.request_id}
        approvals = await session.execute(
            text("SELECT id, revision, status, expires_at FROM approvals WHERE request_id = :req"),
            params,
        )
        verifications = await session.execute(
            text(
                "SELECT v.operation_id, v.result, v.block_number, v.at FROM verifications v "
                "JOIN operations o ON o.id = v.operation_id WHERE o.request_id = :req ORDER BY v.at"
            ),
            params,
        )
        documents = await session.execute(
            text("SELECT id, sha256, mime FROM documents WHERE request_id = :req"), params
        )
        attestation = (
            await session.execute(
                text(
                    "SELECT DISTINCT at.id, at.plan_hash, at.created_at FROM attestations at "
                    "JOIN operations o ON o.step_id = ANY(at.step_ids) WHERE o.request_id = :req"
                ),
                params,
            )
        ).first()
    return {
        "reconciliation": _view(row),
        "lines": [
            {
                "id": str(line.id),
                "classification": line.classification,
                "operationId": str(line.operation_id),
                "txHash": _hex(line.tx_hash),
                "fromAddress": _hex(line.from_address),
                "toAddress": _hex(line.to_address),
                "assetAddress": _hex(line.asset_address),
                "amount": str(line.amount),  # integer base units; wei for FEE
                "blockNumber": line.block_number,
                "day": line.day.isoformat() if line.day else None,
            }
            for line in lines
        ],
        "evidence": {
            "approval": [
                {"id": str(a.id), "revision": a.revision, "status": a.status} for a in approvals
            ],
            "attestation": (
                {"id": str(attestation.id), "planHash": _hex(attestation.plan_hash)}
                if attestation
                else None
            ),
            "txs": [
                {"txHash": _hex(line.tx_hash), "blockNumber": line.block_number}
                for line in lines
                if line.classification != "FEE"
            ],
            "verifications": [
                {
                    "operationId": str(v.operation_id),
                    "result": v.result,
                    "blockNumber": v.block_number,
                    "at": v.at.isoformat(),
                }
                for v in verifications
            ],
            "document": [
                {"id": str(d.id), "sha256": _hex(d.sha256), "mime": d.mime} for d in documents
            ],
            "easUid": row.eas_uid,
            "missing": missing_evidence(facts, strict=False),
        },
    }


@router.post("/{reconciliation_id}/match", openapi_extra={"x-organization-scoped": True})
async def match_reconciliation(
    reconciliation_id: uuid.UUID,
    payload: NoteRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_finance)],
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        row = await _lock(session, member, reconciliation_id, if_match)
        if row.status != "Pending":
            raise _failure(
                409, "INVALID_STATE", f"A {row.status} reconciliation cannot be matched."
            )
        facts = await _facts(session, row.id)
        if missing := missing_evidence(facts, strict=False):
            raise _failure(409, "EVIDENCE_INCOMPLETE", "Evidence is incomplete.", missing=missing)
        # shortcut: RPC read under the row lock, bounded by the provider's timeout.
        if not is_finalized(facts, await _finalized_block(request, session, row.request_id)):
            raise _failure(409, "NOT_FINALIZED", "The PAY block is not finalized yet.")
        now = datetime.now(UTC)
        row.status, row.matched_by, row.matched_user_id = "Matched", "USER", member.user_id
        row.matched_at = row.finalized_at = now
        row.note = payload.note
        await _audit(session, member, row, "matched", matchedBy="USER")
        return _bump(row)


@router.post("/{reconciliation_id}/discrepancy", openapi_extra={"x-organization-scoped": True})
async def flag_discrepancy(
    reconciliation_id: uuid.UUID,
    payload: NoteRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_finance)],
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if payload.note is None:
        raise _failure(422, "NOTE_REQUIRED", "A discrepancy needs a note.")
    async with _sessions(request)() as session, session.begin():
        row = await _lock(session, member, reconciliation_id, if_match)
        if row.status != "Pending":
            raise _failure(
                409, "INVALID_STATE", f"A {row.status} reconciliation cannot be flagged."
            )
        row.status, row.note = "Discrepancy", payload.note
        await _audit(session, member, row, "discrepancy_flagged")
        return _bump(row)


@router.post("/{reconciliation_id}/resolve", openapi_extra={"x-organization-scoped": True})
async def resolve_discrepancy(
    reconciliation_id: uuid.UUID,
    payload: ResolveRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(_resolve_roles)],
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Finance sends ``note``, an Owner sends ``acknowledge``; Matched once both are on record."""

    if payload.note is None and not payload.acknowledge:
        raise _failure(
            422, "NOTE_OR_ACK_REQUIRED", "Send a Finance note or an Owner acknowledgment."
        )
    if payload.note is not None and _R.FINANCE.value not in member.roles:
        raise _failure(403, "FORBIDDEN", "Only Finance writes the resolution note.")
    if payload.acknowledge and _R.OWNER.value not in member.roles:
        raise _failure(403, "FORBIDDEN", "Only an Owner acknowledges a discrepancy.")
    now = datetime.now(UTC)
    async with _sessions(request)() as session, session.begin():
        row = await _lock(session, member, reconciliation_id, if_match)
        if row.status != "Discrepancy":
            raise _failure(409, "INVALID_STATE", "Only a Discrepancy can be resolved.")
        solo = await session.scalar(
            select(Organization.solo_mode).where(Organization.id == member.organization_id)
        )
        if payload.note is not None:
            row.resolution_note, row.resolved_by = payload.note, member.user_id
            await _audit(session, member, row, "resolution_noted")
        if payload.acknowledge:
            row.owner_ack_by, row.owner_ack_at = member.user_id, now
            await _audit(session, member, row, "owner_acknowledged")
        if row.resolved_by and row.owner_ack_by:
            if row.resolved_by == row.owner_ack_by and not solo:
                raise _failure(
                    409, "SEPARATE_OWNER_REQUIRED", "The Owner acknowledgment needs another user."
                )
            row.status, row.matched_by, row.matched_user_id = "Matched", "USER", row.resolved_by
            row.matched_at = now
            await _audit(session, member, row, "discrepancy_resolved")
        return _bump(row)
