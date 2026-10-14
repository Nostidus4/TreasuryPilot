"""In-app Safe governance transaction and signature endpoints (FR-225)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator, model_validator

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


class ModuleLimitInput(ApiModel):
    per_request: str = Field(alias="perRequest", pattern=r"^(0|[1-9][0-9]*)$", max_length=78)
    daily: str = Field(pattern=r"^(0|[1-9][0-9]*)$", max_length=78)

    @model_validator(mode="after")
    def valid_limit(self) -> ModuleLimitInput:
        if int(self.per_request) > int(self.daily):
            raise ValueError("perRequest must not exceed daily")
        if int(self.daily) > (1 << 128) - 1:
            raise ValueError("limits must fit uint128")
        return self


class ModuleMandateInput(ApiModel):
    valid_from: datetime = Field(alias="validFrom")
    expires_at: datetime = Field(alias="expiresAt")
    payee_cooling_seconds: int = Field(alias="payeeCoolingSeconds", ge=1, le=2**32 - 1)
    executor: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    guardian: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    pay: ModuleLimitInput
    refill: ModuleLimitInput
    supply: ModuleLimitInput
    approval_max_age: int = Field(alias="approvalMaxAge", ge=1, le=2**32 - 1)
    approvers: list[Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$")]] = Field(
        min_length=1, max_length=32
    )

    @field_validator("executor", "guardian")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @field_validator("executor")
    @classmethod
    def executor_nonzero(cls, value: str) -> str:
        if int(value[2:], 16) == 0:
            raise ValueError("executor must be nonzero")
        return value

    @field_validator("approvers")
    @classmethod
    def normalize_approvers(cls, values: list[str]) -> list[str]:
        normalized = [item.lower() for item in values]
        if len(set(normalized)) != len(normalized) or "0x" + "00" * 20 in normalized:
            raise ValueError("approvers must be unique and nonzero")
        return normalized

    @model_validator(mode="after")
    def valid_window(self) -> ModuleMandateInput:
        start = (
            self.valid_from.replace(tzinfo=UTC)
            if self.valid_from.tzinfo is None
            else self.valid_from
        )
        end = (
            self.expires_at.replace(tzinfo=UTC)
            if self.expires_at.tzinfo is None
            else self.expires_at
        )
        if end <= start:
            raise ValueError("expiresAt must be after validFrom")
        if start.timestamp() < 0 or end.timestamp() > (1 << 64) - 1:
            raise ValueError("mandate timestamps must fit uint64")
        if int(self.supply.per_request) == 0 and int(self.supply.daily) != 0:
            raise ValueError("supply perRequest and daily must both be zero or nonzero")
        if int(self.supply.daily) == 0 and int(self.supply.per_request) != 0:
            raise ValueError("supply perRequest and daily must both be zero or nonzero")
        return self


class ModuleBufferInput(ApiModel):
    wallet: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    minimum: str = Field(pattern=r"^(0|[1-9][0-9]*)$", max_length=78)
    target: str = Field(pattern=r"^(0|[1-9][0-9]*)$", max_length=78)

    @field_validator("wallet")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def valid_buffer_amounts(self) -> ModuleBufferInput:
        maximum = (1 << 256) - 1
        if int(self.minimum) > maximum or int(self.target) > maximum:
            raise ValueError("buffer amounts must fit uint256")
        return self


class CreateModuleSetupRequest(ApiModel):
    mandate: ModuleMandateInput
    buffers: list[ModuleBufferInput] = Field(min_length=2, max_length=3)

    @field_validator("buffers")
    @classmethod
    def unique_wallets(cls, values: list[ModuleBufferInput]) -> list[ModuleBufferInput]:
        if len({item.wallet for item in values}) != len(values):
            raise ValueError("buffers must list each wallet once")
        return values


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


@router.post("/orgs/{organization_id}/treasuries/{treasury_id}/module/deploy-tx", status_code=201)
async def create_module_setup(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: CreateModuleSetupRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER))],
) -> dict[str, Any]:
    mandate = payload.mandate

    def utc_timestamp(value: datetime) -> int:
        return int((value.replace(tzinfo=UTC) if value.tzinfo is None else value).timestamp())

    setup = {
        "mandate": {
            "validFrom": utc_timestamp(mandate.valid_from),
            "expiresAt": utc_timestamp(mandate.expires_at),
            "payeeCoolingSeconds": mandate.payee_cooling_seconds,
            "executor": mandate.executor,
            "guardian": mandate.guardian,
            "pay": mandate.pay.model_dump(by_alias=True),
            "refill": mandate.refill.model_dump(by_alias=True),
            "supply": mandate.supply.model_dump(by_alias=True),
            "approvalMaxAge": mandate.approval_max_age,
            "approvers": mandate.approvers,
        },
        "buffers": [item.model_dump() for item in payload.buffers],
    }
    try:
        return await _service(request).create_module_setup(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            setup=setup,
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
