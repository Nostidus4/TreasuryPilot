from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import Coverage, TreasuryStatus, WalletRole
from treasurypilot_api.treasury.safe import RpcUnavailable
from treasurypilot_api.treasury.service import (
    TreasuryNotFound,
    TreasuryRecord,
    TreasuryRequestError,
    TreasuryService,
    WalletInput,
    coverage_allows_execution,
)
from treasurypilot_api.treasury.sync import asset_id


class AssetView(ApiModel):
    id: uuid.UUID
    symbol: str
    decimals: int
    address: str
    is_test: bool


class ChainView(ApiModel):
    chain_id: int
    name: str
    explorer_url: str
    assets: list[AssetView]


class ChainsResponse(ApiModel):
    chains: list[ChainView]


router = APIRouter(prefix="/v1", tags=["treasury"])


@router.get("/chains", response_model=ChainsResponse)
async def list_chains(request: Request) -> ChainsResponse:
    await _authenticated(request)
    # Served from the startup configuration: config is read-only at runtime (M02-D8)
    # and startup fails unless every asset was synced with verified decimals.
    configuration: PlatformConfiguration = request.app.state.platform_configuration
    return ChainsResponse(
        chains=[
            ChainView(
                chain_id=chain.chain_id,
                name=chain.name,
                explorer_url=str(chain.explorer_url),
                assets=[
                    AssetView(
                        id=asset_id(chain.chain_id, asset.address),
                        symbol=asset.symbol,
                        decimals=asset.decimals,
                        address=asset.address,
                        is_test=asset.is_test,
                    )
                    for asset in chain.assets
                ],
            )
            for chain in configuration.chains
            if chain.enabled
        ]
    )


class WalletRequest(ApiModel):
    role: WalletRole
    safe_address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    label: str | None = Field(default=None, max_length=120)


class CreateTreasuryRequest(ApiModel):
    chain_id: int = Field(gt=0)
    asset_id: uuid.UUID
    wallets: list[WalletRequest] = Field(min_length=2, max_length=3)


class WalletView(ApiModel):
    id: uuid.UUID
    role: WalletRole
    label: str
    safe_address: str
    owners: list[str]
    threshold: int


class CoverageView(ApiModel):
    status: Coverage
    acknowledged: bool
    details: list[str]
    execution_allowed: bool
    acknowledged_at: datetime | None = None
    acknowledged_by: uuid.UUID | None = None
    acknowledgment_reason: str | None = None

    @classmethod
    def from_record(cls, record: TreasuryRecord) -> CoverageView:
        return cls(
            status=record.coverage,
            acknowledged=record.coverage_acknowledged,
            details=list(record.coverage_details),
            execution_allowed=coverage_allows_execution(
                record.coverage, record.coverage_acknowledged
            ),
            acknowledged_at=record.coverage_acknowledged_at,
            acknowledged_by=record.coverage_acknowledged_by,
            acknowledgment_reason=record.coverage_ack_reason,
        )


class TreasuryView(ApiModel):
    id: uuid.UUID
    chain_id: int
    asset_id: uuid.UUID
    status: TreasuryStatus
    coverage: CoverageView
    module_address: str | None
    created_at: datetime


class CoverageResponse(ApiModel):
    coverage: CoverageView


class CoverageAcknowledgeRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)


class WarningView(ApiModel):
    code: str
    message: str
    wallets: list[str]


class TreasuryResponse(ApiModel):
    treasury: TreasuryView
    wallets: list[WalletView]
    warnings: list[WarningView]

    @classmethod
    def from_record(cls, record: TreasuryRecord) -> TreasuryResponse:
        return cls(
            treasury=TreasuryView(
                id=record.id,
                chain_id=record.chain_id,
                asset_id=record.asset_id,
                status=record.status,
                coverage=CoverageView.from_record(record),
                module_address=record.module_address,
                created_at=record.created_at,
            ),
            wallets=[
                WalletView(
                    id=wallet.id,
                    role=wallet.role,
                    label=wallet.label,
                    safe_address=wallet.safe_address,
                    owners=list(wallet.owners),
                    threshold=wallet.threshold,
                )
                for wallet in record.wallets
            ],
            warnings=[
                WarningView(code=w.code, message=w.message, wallets=list(w.wallets))
                for w in record.warnings
            ],
        )


def _service(request: Request) -> TreasuryService:
    service = getattr(request.app.state, "treasury_service", None)
    if service is None:
        raise AuthFailure(
            status=503,
            code="TREASURY_UNAVAILABLE",
            title="Treasury service unavailable",
            detail="Treasury storage is not configured.",
        )
    return cast(TreasuryService, service)


@router.post("/orgs/{organization_id}/treasuries", status_code=201, response_model=TreasuryResponse)
async def create_treasury(
    payload: CreateTreasuryRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, OrganizationRole.ORG_ADMIN)),
    ],
) -> TreasuryResponse:
    try:
        record = await _service(request).create(
            organization_id=member.organization_id,
            user_id=member.user_id,
            chain_id=payload.chain_id,
            asset=payload.asset_id,
            wallets=[
                WalletInput(item.role, item.safe_address, item.label) for item in payload.wallets
            ],
        )
    except TreasuryRequestError as exc:
        raise AuthFailure(
            status=422, code=exc.code, title="Treasury request rejected", detail=exc.detail
        ) from None
    except RpcUnavailable:
        raise AuthFailure(
            status=503,
            code="RPC_UNAVAILABLE",
            title="Chain RPC unavailable",
            detail="The Safes could not be verified because no RPC provider answered.",
            retry_after=5,
        ) from None
    return TreasuryResponse.from_record(record)


@router.get("/orgs/{organization_id}/treasuries/{treasury_id}", response_model=TreasuryResponse)
async def get_treasury(
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> TreasuryResponse:
    try:
        record = await _service(request).get(
            organization_id=member.organization_id, treasury_id=treasury_id
        )
    except TreasuryNotFound:
        raise AuthFailure(
            status=404,
            code="TREASURY_NOT_FOUND",
            title="Treasury not found",
            detail="The treasury does not exist in this organization.",
        ) from None
    return TreasuryResponse.from_record(record)


@router.post(
    "/orgs/{organization_id}/treasuries/{treasury_id}/coverage/refresh",
    response_model=CoverageResponse,
)
async def refresh_coverage(
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, OrganizationRole.ORG_ADMIN)),
    ],
) -> CoverageResponse:
    try:
        record = await _service(request).refresh_coverage(
            organization_id=member.organization_id, treasury_id=treasury_id
        )
    except TreasuryNotFound:
        raise AuthFailure(
            status=404,
            code="TREASURY_NOT_FOUND",
            title="Treasury not found",
            detail="The treasury does not exist in this organization.",
        ) from None
    return CoverageResponse(coverage=CoverageView.from_record(record))


@router.post(
    "/orgs/{organization_id}/treasuries/{treasury_id}/coverage/acknowledge",
    response_model=CoverageResponse,
)
async def acknowledge_coverage(
    treasury_id: uuid.UUID,
    payload: CoverageAcknowledgeRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER))],
) -> CoverageResponse:
    try:
        record = await _service(request).acknowledge_coverage(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            reason=payload.reason,
        )
    except TreasuryNotFound:
        raise AuthFailure(
            status=404,
            code="TREASURY_NOT_FOUND",
            title="Treasury not found",
            detail="The treasury does not exist in this organization.",
        ) from None
    except TreasuryRequestError as exc:
        status = 409 if exc.code in {"COVERAGE_COMPLETE", "COVERAGE_UNKNOWN"} else 422
        raise AuthFailure(
            status=status,
            code=exc.code,
            title="Coverage acknowledgment rejected",
            detail=exc.detail,
        ) from None
    return CoverageResponse(coverage=CoverageView.from_record(record))
