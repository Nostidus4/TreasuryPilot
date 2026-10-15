from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.chain.models import TokenMovement
from treasurypilot_api.execution.models import ObservedEvent
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.treasury.models import Treasury

router = APIRouter(prefix="/v1", tags=["chain"])


class AcknowledgeTokenMovementRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class TokenMovementView(ApiModel):
    id: uuid.UUID
    treasury_id: uuid.UUID
    transaction_hash: str
    block_number: int
    block_hash: str
    wallet: str
    direction: Literal["IN", "OUT"]
    counterparty: str
    amount: str
    classification: Literal["AGENT", "INTERNAL_REFILL", "INFLOW", "UNEXPECTED_OUTFLOW", "LENDING"]
    operation_id: uuid.UUID | None
    removed: bool
    created_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    acknowledgement_reason: str | None


class TokenMovementListResponse(ApiModel):
    items: list[TokenMovementView]


class AcknowledgeTokenMovementResponse(ApiModel):
    movement: TokenMovementView


@dataclass(frozen=True)
class TokenMovementRecord:
    id: uuid.UUID
    treasury_id: uuid.UUID
    transaction_hash: bytes
    block_number: int
    block_hash: bytes
    wallet: bytes
    direction: str
    counterparty: bytes
    amount: str
    classification: str
    operation_id: uuid.UUID | None
    removed: bool
    created_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    acknowledgement_reason: str | None


class TokenMovementNotFound(Exception):
    pass


class TokenMovementConflict(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class TokenMovementRepository(Protocol):
    async def list_recent(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, limit: int
    ) -> tuple[TokenMovementRecord, ...] | None: ...

    async def acknowledge(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        movement_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> TokenMovementRecord: ...


class SqlAlchemyTokenMovementRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _record(movement: TokenMovement, event: ObservedEvent) -> TokenMovementRecord:
        return TokenMovementRecord(
            id=movement.id,
            treasury_id=movement.treasury_id,
            transaction_hash=event.tx_hash,
            block_number=event.block_number,
            block_hash=event.block_hash,
            wallet=movement.wallet,
            direction=movement.direction,
            counterparty=movement.counterparty,
            amount=str(movement.amount),
            classification=movement.classification,
            operation_id=movement.operation_id,
            removed=movement.removed,
            created_at=movement.created_at,
            acknowledged_by=movement.acknowledged_by,
            acknowledged_at=movement.acknowledged_at,
            acknowledgement_reason=movement.acknowledgement_reason,
        )

    async def list_recent(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, limit: int
    ) -> tuple[TokenMovementRecord, ...] | None:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Treasury.id).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if exists is None:
                return None
            rows = (
                await session.execute(
                    select(TokenMovement, ObservedEvent)
                    .join(ObservedEvent, ObservedEvent.id == TokenMovement.event_id)
                    .where(TokenMovement.treasury_id == treasury_id)
                    .order_by(TokenMovement.created_at.desc(), TokenMovement.id)
                    .limit(limit)
                )
            ).all()
        return tuple(self._record(movement, event) for movement, event in rows)

    async def acknowledge(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        movement_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> TokenMovementRecord:
        async with self._sessions() as session, session.begin():
            row = await session.execute(
                select(TokenMovement, ObservedEvent)
                .join(ObservedEvent, ObservedEvent.id == TokenMovement.event_id)
                .join(Treasury, Treasury.id == TokenMovement.treasury_id)
                .where(
                    Treasury.org_id == organization_id,
                    TokenMovement.treasury_id == treasury_id,
                    TokenMovement.id == movement_id,
                )
                .with_for_update(of=TokenMovement)
            )
            found = row.one_or_none()
            if found is None:
                raise TokenMovementNotFound
            movement, event = found
            if movement.classification != "UNEXPECTED_OUTFLOW":
                raise TokenMovementConflict(
                    "MOVEMENT_NOT_ACKNOWLEDGEABLE",
                    "Only unexpected outflows can be acknowledged.",
                )
            if movement.removed:
                raise TokenMovementConflict(
                    "MOVEMENT_REMOVED", "A reorg removed this token movement."
                )
            if movement.acknowledged_at is not None:
                if movement.acknowledged_by == user_id:
                    return self._record(movement, event)
                raise TokenMovementConflict(
                    "MOVEMENT_ALREADY_ACKNOWLEDGED",
                    "This outflow was already acknowledged by another owner.",
                )
            movement.acknowledged_by = user_id
            movement.acknowledged_at = datetime.now(UTC)
            movement.acknowledgement_reason = reason
            await session.flush()
            # Signals stay pending: acknowledging records an owner decision for #61/#65 to read.
            await write_audit(
                session,
                org_id=organization_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action="token_movement.acknowledged",
                entity=AuditEntity("token_movement", movement.id),
                data={
                    "treasuryId": str(treasury_id),
                    "reason": reason,
                    "transactionHash": "0x" + event.tx_hash.hex(),
                    "amount": str(movement.amount),
                },
            )
            return self._record(movement, event)


def _repository(request: Request) -> TokenMovementRepository:
    repository = getattr(request.app.state, "token_movement_repository", None)
    if repository is not None:
        return cast(TokenMovementRepository, repository)
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise AuthFailure(
            status=503,
            code="CHAIN_UNAVAILABLE",
            title="Chain movement service unavailable",
            detail="Token movement storage is not configured.",
        )
    return SqlAlchemyTokenMovementRepository(cast(async_sessionmaker[AsyncSession], sessions))


def _movement_view(record: TokenMovementRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "treasuryId": record.treasury_id,
        "transactionHash": "0x" + record.transaction_hash.hex(),
        "blockNumber": record.block_number,
        "blockHash": "0x" + record.block_hash.hex(),
        "wallet": "0x" + record.wallet.hex(),
        "direction": record.direction,
        "counterparty": "0x" + record.counterparty.hex(),
        "amount": record.amount,
        "classification": record.classification,
        "operationId": record.operation_id,
        "removed": record.removed,
        "createdAt": record.created_at,
        "acknowledgedBy": record.acknowledged_by,
        "acknowledgedAt": record.acknowledged_at,
        "acknowledgementReason": record.acknowledgement_reason,
    }


def _failure(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=status,
        code=code,
        title=code.replace("_", " ").title(),
        detail=detail,
    )


@router.get(
    "/orgs/{organization_id}/treasuries/{treasury_id}/token-movements",
    response_model=TokenMovementListResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def list_token_movements(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    rows = await _repository(request).list_recent(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        limit=limit,
    )
    if rows is None:
        raise _failure(404, "TREASURY_NOT_FOUND", "The treasury does not exist.")
    return {"items": [_movement_view(row) for row in rows]}


@router.post(
    "/orgs/{organization_id}/treasuries/{treasury_id}/token-movements/{movement_id}/acknowledge",
    response_model=AcknowledgeTokenMovementResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def acknowledge_token_movement(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    movement_id: uuid.UUID,
    payload: AcknowledgeTokenMovementRequest,
    request: Request,
    member: MemberAccess = Depends(require_role(OrganizationRole.OWNER)),  # noqa: B008
) -> dict[str, object]:
    try:
        record = await _repository(request).acknowledge(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            movement_id=movement_id,
            user_id=member.user_id,
            reason=payload.reason,
        )
    except TokenMovementNotFound:
        raise _failure(
            404, "TOKEN_MOVEMENT_NOT_FOUND", "The token movement is unavailable."
        ) from None
    except TokenMovementConflict as exc:
        raise _failure(409, exc.code, exc.detail) from None
    return {"movement": _movement_view(record)}
