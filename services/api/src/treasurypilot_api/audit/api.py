from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.chain import ChainVerification, verify_chain
from treasurypilot_api.audit.evidence import (
    EvidenceBundle,
    EvidenceBundleInvalid,
    EvidenceForbidden,
    EvidenceNotFound,
    EvidenceRepository,
)
from treasurypilot_api.audit.models import AuditHead, AuditLog
from treasurypilot_api.audit.writer import AuditHeadMissing
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Membership, MembershipStatus, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, organization_not_found, require_role

_READ = (OrganizationRole.AUDITOR, OrganizationRole.OWNER, OrganizationRole.ORG_ADMIN)
_VERIFY = (OrganizationRole.AUDITOR, OrganizationRole.OWNER)
READ_ROLES = frozenset(role.value for role in _READ)
VERIFY_ROLES = frozenset(role.value for role in _VERIFY)


@dataclass(frozen=True, slots=True)
class AuditFilters:
    entity_type: str | None = None
    entity_id: str | None = None
    actor: str | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[AuditLog]
    next_cursor: int | None


class AuditNotFound(Exception):
    """The organization does not exist or is not visible to this user."""


class AuditPermissionDenied(Exception):
    """The member does not hold a role allowed to read or verify the audit log."""


class AuditRepository(Protocol):
    async def list(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        filters: AuditFilters,
        cursor: int | None,
        limit: int,
    ) -> AuditPage: ...

    async def verify(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChainVerification: ...


async def _require_role(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    allowed: Collection[str],
) -> None:
    roles = await session.scalar(
        select(Membership.roles).where(
            Membership.org_id == organization_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    if roles is None:
        raise AuditNotFound
    if not set(roles).intersection(allowed):
        raise AuditPermissionDenied


class SqlAlchemyAuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        filters: AuditFilters,
        cursor: int | None,
        limit: int,
    ) -> AuditPage:
        statement = select(AuditLog).where(AuditLog.org_id == organization_id)
        if filters.entity_type is not None:
            statement = statement.where(AuditLog.entity_type == filters.entity_type)
        if filters.entity_id is not None:
            statement = statement.where(AuditLog.entity_id == filters.entity_id)
        if filters.actor is not None:
            statement = statement.where(AuditLog.actor_id == filters.actor)
        if filters.since is not None:
            statement = statement.where(AuditLog.at >= filters.since)
        if filters.until is not None:
            statement = statement.where(AuditLog.at < filters.until)
        if cursor is not None:
            statement = statement.where(AuditLog.seq > cursor)
        async with self._sessions() as session:
            await _require_role(session, organization_id, user_id, READ_ROLES)
            rows = list(await session.scalars(statement.order_by(AuditLog.seq).limit(limit + 1)))
        items = rows[:limit]
        return AuditPage(items=items, next_cursor=items[-1].seq if len(rows) > limit else None)

    async def verify(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> ChainVerification:
        async with self._sessions() as session, session.begin():
            # One snapshot for the head and the rows, so a concurrent write is not
            # mistaken for a record appended past the head.
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await _require_role(session, organization_id, user_id, VERIFY_ROLES)
            head = await session.get(AuditHead, organization_id)
            if head is None:
                raise AuditHeadMissing(f"organization {organization_id} has no audit head")
            statement = (
                select(AuditLog)
                .where(AuditLog.org_id == organization_id)
                .order_by(AuditLog.seq)
                .execution_options(yield_per=1000)
            )
            return await session.run_sync(
                lambda sync_session: verify_chain(sync_session.scalars(statement), head)
            )


class AuditRecordView(ApiModel):
    """One audit record; JSON Lines of these are the dump that ``chain.py verify`` reads."""

    seq: int
    org_id: uuid.UUID
    at: AwareDatetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    data: dict[str, Any]
    prev_hash: str
    hash: str

    @classmethod
    def from_row(cls, row: AuditLog) -> AuditRecordView:
        return cls(
            seq=row.seq,
            org_id=row.org_id,
            at=row.at,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            data=row.data,
            prev_hash="0x" + row.prev_hash.hex(),
            hash="0x" + row.hash.hex(),
        )


class AuditLogResponse(ApiModel):
    items: list[AuditRecordView]
    next_cursor: str | None


class AuditVerifyResponse(ApiModel):
    status: Literal["INTACT", "BROKEN"]
    checked: int
    broken_at: int | None

    @classmethod
    def from_result(cls, result: ChainVerification) -> AuditVerifyResponse:
        return cls(status=result.status, checked=result.checked, broken_at=result.broken_at)


def _repository(request: Request) -> AuditRepository:
    repository = getattr(request.app.state, "audit_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="AUDIT_UNAVAILABLE",
            title="Audit service unavailable",
            detail="Audit storage is not configured.",
        )
    return cast(AuditRepository, repository)


def _evidence_repository(request: Request) -> EvidenceRepository:
    repository = getattr(request.app.state, "evidence_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="EVIDENCE_UNAVAILABLE",
            title="Evidence export unavailable",
            detail="Request evidence storage and chain verification are not configured.",
        )
    return cast(EvidenceRepository, repository)


def _forbidden() -> AuthFailure:
    return AuthFailure(
        status=403,
        code="FORBIDDEN",
        title="Forbidden",
        detail="An organization role with access to the audit log is required.",
    )


router = APIRouter(prefix="/v1/orgs", tags=["audit"])


@router.get("/{organization_id}/audit-log", response_model=AuditLogResponse)
async def list_audit_log(
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(*_READ))],
    entity_type: Annotated[str | None, Query(alias="entityType", min_length=1)] = None,
    entity_id: Annotated[str | None, Query(alias="entityId", min_length=1)] = None,
    actor: Annotated[str | None, Query(min_length=1)] = None,
    since: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    until: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    cursor: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> AuditLogResponse:
    try:
        page = await _repository(request).list(
            organization_id=member.organization_id,
            user_id=member.user_id,
            filters=AuditFilters(entity_type, entity_id, actor, since, until),
            cursor=cursor,
            limit=limit,
        )
    except AuditNotFound:
        raise organization_not_found() from None
    except AuditPermissionDenied:
        raise _forbidden() from None
    return AuditLogResponse(
        items=[AuditRecordView.from_row(row) for row in page.items],
        next_cursor=str(page.next_cursor) if page.next_cursor is not None else None,
    )


@router.get("/{organization_id}/audit-log/verify", response_model=AuditVerifyResponse)
async def verify_audit_log(
    request: Request, member: Annotated[MemberAccess, Depends(require_role(*_VERIFY))]
) -> AuditVerifyResponse:
    try:
        result = await _repository(request).verify(
            organization_id=member.organization_id, user_id=member.user_id
        )
    except AuditNotFound:
        raise organization_not_found() from None
    except AuditPermissionDenied:
        raise _forbidden() from None
    return AuditVerifyResponse.from_result(result)


@router.get(
    "/{organization_id}/requests/{request_id}/evidence",
    response_model=EvidenceBundle,
    response_model_exclude_none=True,
)
async def get_request_evidence(
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(*_READ, OrganizationRole.FINANCE)),
    ],
    request_id: uuid.UUID,
) -> EvidenceBundle:
    try:
        return await _evidence_repository(request).export_request(
            organization_id=member.organization_id,
            request_id=request_id,
        )
    except EvidenceNotFound:
        raise AuthFailure(
            status=404,
            code="REQUEST_NOT_FOUND",
            title="Request not found",
            detail="The request does not exist or is not available in this organization.",
        ) from None
    except EvidenceForbidden:
        raise AuthFailure(
            status=403,
            code="FORBIDDEN",
            title="Forbidden",
            detail="An organization role with access to financial evidence is required.",
        ) from None
    except EvidenceBundleInvalid as exc:
        raise AuthFailure(
            status=409,
            code="EVIDENCE_INVALID",
            title="Evidence bundle is invalid",
            detail="The bundle failed an integrity check (e.g. an unresolved transaction hash); "
            "it was withheld.",
            extensions={"evidenceStatus": "INVALID"},
        ) from exc
