"""In-app Safe governance transaction and signature endpoints (FR-225)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.governance import GovernanceCall
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.mandate.models import GovernanceTxPurpose
from treasurypilot_api.treasury.safe import RpcUnavailable

router = APIRouter(prefix="/v1", tags=["governance"])


class CallInput(ApiModel):
    to: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    value: str = Field(default="0", pattern=r"^(0|[1-9][0-9]*)$", max_length=78)
    data: str = Field(pattern=r"^0x(?:[0-9a-fA-F]{2})*$", max_length=131_074)
    operation: int = Field(default=0, ge=0, le=1)

    @field_validator("to")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        return value.lower()


class CreateGovernanceTxRequest(ApiModel):
    purpose: GovernanceTxPurpose
    calls: list[CallInput] = Field(min_length=1, max_length=32)


class SignatureRequest(ApiModel):
    signature: str = Field(pattern=r"^0x(?:[0-9a-fA-F]{2}){65}$")


class SubmittedRequest(ApiModel):
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")


def _service(request: Request) -> GovernanceService:
    service = getattr(request.app.state, "governance_service", None)
    if service is None:
        raise AuthFailure(
            status=503,
            code="GOVERNANCE_UNAVAILABLE",
            title="Governance unavailable",
            detail="Governance storage is not configured.",
        )
    return cast(GovernanceService, service)


def _failure(exc: GovernanceFailure) -> AuthFailure:
    return AuthFailure(
        status=exc.status, code=exc.code, title="Governance request rejected", detail=exc.detail
    )


def _rpc_failure() -> AuthFailure:
    return AuthFailure(
        status=503,
        code="RPC_UNAVAILABLE",
        title="Chain RPC unavailable",
        detail="Safe state could not be read because no RPC provider answered.",
        retry_after=5,
    )


@router.post("/orgs/{organization_id}/treasuries/{treasury_id}/governance-txs", status_code=201)
async def create_governance_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: CreateGovernanceTxRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER)),
    ],
) -> dict[str, Any]:
    calls = [
        GovernanceCall(
            bytes.fromhex(item.to[2:]),
            int(item.value),
            bytes.fromhex(item.data[2:]),
            item.operation,
        )
        for item in payload.calls
    ]
    try:
        return await _service(request).create(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            purpose=payload.purpose,
            calls=calls,
        )
    except GovernanceFailure as exc:
        raise _failure(exc) from None
    except RpcUnavailable:
        raise _rpc_failure() from None


@router.get("/orgs/{organization_id}/governance-txs/{governance_tx_id}")
async def get_governance_tx(
    governance_tx_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> dict[str, Any]:
    try:
        return await _service(request).get(
            organization_id=member.organization_id, governance_tx_id=governance_tx_id
        )
    except GovernanceFailure as exc:
        raise _failure(exc) from None
    except RpcUnavailable:
        raise _rpc_failure() from None


@router.post("/orgs/{organization_id}/governance-txs/{governance_tx_id}/signatures")
async def add_governance_signature(
    governance_tx_id: uuid.UUID,
    payload: SignatureRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER)),
    ],
) -> dict[str, Any]:
    try:
        return await _service(request).sign(
            organization_id=member.organization_id,
            governance_tx_id=governance_tx_id,
            user_id=member.user_id,
            signature=bytes.fromhex(payload.signature[2:]),
        )
    except GovernanceFailure as exc:
        raise _failure(exc) from None
    except RpcUnavailable:
        raise _rpc_failure() from None


@router.get("/orgs/{organization_id}/governance-txs/{governance_tx_id}/exec-call")
async def get_exec_call(
    governance_tx_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER)),
    ],
) -> dict[str, str]:
    try:
        return await _service(request).exec_call(
            organization_id=member.organization_id, governance_tx_id=governance_tx_id
        )
    except GovernanceFailure as exc:
        raise _failure(exc) from None
    except RpcUnavailable:
        raise _rpc_failure() from None


@router.post("/orgs/{organization_id}/governance-txs/{governance_tx_id}/submitted")
async def report_submission(
    governance_tx_id: uuid.UUID,
    payload: SubmittedRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER)),
    ],
) -> dict[str, Any]:
    try:
        return await _service(request).submitted(
            organization_id=member.organization_id,
            governance_tx_id=governance_tx_id,
            user_id=member.user_id,
            transaction_hash=bytes.fromhex(payload.transaction_hash[2:]),
        )
    except GovernanceFailure as exc:
        raise _failure(exc) from None
