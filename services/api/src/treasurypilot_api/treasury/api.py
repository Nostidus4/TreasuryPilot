from __future__ import annotations

import secrets
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
from treasurypilot_api.treasury.safe import (
    RpcUnavailable,
    SafeDeploymentCodeMismatch,
    SafeDeploymentUnavailable,
    build_safe_deployment_transaction,
    safe_deployment_available,
    verify_safe_deployment_code,
)
from treasurypilot_api.treasury.service import (
    TreasuryNotFound,
    TreasuryRecord,
    TreasuryRequestError,
    TreasuryService,
    WalletInput,
    coverage_allows_execution,
)
from treasurypilot_api.treasury.state import (
    ActivityView,
    BudgetView,
    MandateSummaryView,
    PositionView,
    QueuesView,
    StalenessView,
    TreasuryExtras,
    load_extras,
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
    safe_deployment_available: bool


class ChainsResponse(ApiModel):
    chains: list[ChainView]


class SafeDeploymentRequest(ApiModel):
    chain_id: int = Field(gt=0)
    owners: list[str] = Field(min_length=1, max_length=10)
    threshold: int = Field(gt=0, le=10)


class SafeDeploymentTransaction(ApiModel):
    to: str
    data: str
    value: str


class SafeDeploymentResponse(ApiModel):
    chain_id: int
    transaction: SafeDeploymentTransaction


router = APIRouter(prefix="/v1", tags=["treasury"])


@router.get("/chains", response_model=ChainsResponse)
async def list_chains(request: Request) -> ChainsResponse:
    # Read-only platform metadata, safe for organization-scoped SSO sessions.
    await _authenticated(request, allow_scoped=True)
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
                safe_deployment_available=safe_deployment_available(configuration, chain.chain_id),
            )
            for chain in configuration.chains
            if chain.enabled
        ]
    )


@router.post(
    "/orgs/{organization_id}/safes/deploy-tx",
    response_model=SafeDeploymentResponse,
)
async def safe_deployment_transaction(
    organization_id: uuid.UUID,
    payload: SafeDeploymentRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, OrganizationRole.ORG_ADMIN)),
    ],
) -> SafeDeploymentResponse:
    # The organization ID is deliberately bound by require_role; the transaction itself
    # contains no organization data and all signing/broadcasting remains with the owner.
    if organization_id != member.organization_id:
        raise AuthFailure(
            status=404,
            code="ORG_NOT_FOUND",
            title="Organization not found",
            detail="The organization does not exist.",
        )
    configuration: PlatformConfiguration = request.app.state.platform_configuration
    try:
        await verify_safe_deployment_code(configuration, payload.chain_id)
        transaction = build_safe_deployment_transaction(
            configuration,
            payload.chain_id,
            payload.owners,
            payload.threshold,
            secrets.randbits(256),
        )
    except SafeDeploymentCodeMismatch:
        raise AuthFailure(
            status=503,
            code="SAFE_DEPLOYMENT_VERIFICATION_FAILED",
            title="Safe deployment verification failed",
            detail=(
                "The configured Safe deployments do not match their recorded runtime code "
                "hashes on this chain. Contact an operator."
            ),
        ) from None
    except SafeDeploymentUnavailable:
        raise AuthFailure(
            status=503,
            code="SAFE_DEPLOYMENT_UNAVAILABLE",
            title="Safe deployment unavailable",
            detail=(
                "This chain has no verified Safe proxy factory, v1.4.1 singleton, and "
                "fallback handler configured. Use an existing Safe until those deployments "
                "are recorded and verified."
            ),
            retry_after=60,
        ) from None
    except RpcUnavailable:
        raise AuthFailure(
            status=503,
            code="RPC_UNAVAILABLE",
            title="Chain RPC unavailable",
            detail="Safe deployment addresses could not be checked against the configured chain RPCs.",
            retry_after=5,
        ) from None
    except ValueError as exc:
        raise AuthFailure(
            status=422,
            code="INVALID_SAFE_CONFIGURATION",
            title="Safe configuration rejected",
            detail=str(exc),
        ) from None
    return SafeDeploymentResponse(
        chain_id=payload.chain_id,
        transaction=SafeDeploymentTransaction(**transaction),
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
    # Base units from the latest chain snapshot (TRS-009); left out when it has no reading.
    balance: str | None = None
    buffer: str | None = None
    target: str | None = None


class CoverageView(ApiModel):
    status: Coverage
    acknowledged: bool
    details: list[str]
    missing: list[str]
    snapshot_block: int | None
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
            missing=list(record.coverage_missing),
            snapshot_block=record.snapshot_block,
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


class TreasurySummaryView(ApiModel):
    id: uuid.UUID
    chain_id: int
    chain_name: str
    asset_id: uuid.UUID
    asset_symbol: str
    # Null when the asset is no longer in the startup configuration.
    asset_decimals: int | None
    asset_is_test: bool | None
    status: TreasuryStatus
    coverage: Coverage
    coverage_details: list[str]
    created_at: datetime


class TreasuriesResponse(ApiModel):
    items: list[TreasurySummaryView]


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
    # Dashboard parts (TRS-009). Serialized only when set: `mandate` is null for "none set",
    # the chain-backed parts are left out while no chain snapshot exists.
    mandate: MandateSummaryView | None = None
    budgets: list[BudgetView] | None = None
    staleness: StalenessView | None = None
    position: PositionView | None = None
    queues: QueuesView | None = None
    activity: list[ActivityView] | None = None
    # The open borrow proposal, left out when there is none.
    borrow_proposal_id: uuid.UUID | None = None

    @classmethod
    def from_record(
        cls, record: TreasuryRecord, extras: TreasuryExtras | None = None
    ) -> TreasuryResponse:
        parts: dict[str, object] = {}
        if extras is not None:
            parts = {
                "mandate": extras.mandate,
                "queues": extras.queues,
                "activity": extras.activity,
            }
            for name in ("budgets", "staleness", "position"):
                if (value := getattr(extras, name)) is not None:
                    parts[name] = value
            if extras.borrow_proposal_id is not None:
                parts["borrow_proposal_id"] = extras.borrow_proposal_id
        figures = extras.wallets if extras is not None else {}
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
                    **(
                        {
                            "balance": found.balance,
                            "buffer": found.buffer,
                            "target": found.target,
                        }
                        if (found := figures.get(wallet.safe_address.lower()))
                        else {}
                    ),
                )
                for wallet in record.wallets
            ],
            warnings=[
                WarningView(code=w.code, message=w.message, wallets=list(w.wallets))
                for w in record.warnings
            ],
            **parts,  # type: ignore[arg-type]
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
        extensions: dict[str, object] = {}
        if exc.address is not None:
            # Attribute by role and position, never by the client-supplied label.
            slots = {WalletRole.SOURCE: ["T"], WalletRole.OPERATIONAL: ["O1", "O2"]}
            seen = {WalletRole.SOURCE: 0, WalletRole.OPERATIONAL: 0}
            for item in payload.wallets:
                slot = slots[item.role][min(seen[item.role], len(slots[item.role]) - 1)]
                seen[item.role] += 1
                if item.safe_address.lower() == exc.address.lower():
                    extensions["errors"] = [{"field": f"wallets.{slot}", "message": exc.detail}]
                    break
        raise AuthFailure(
            status=422,
            code=exc.code,
            title="Treasury request rejected",
            detail=exc.detail,
            extensions=extensions,
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


@router.get("/orgs/{organization_id}/treasuries", response_model=TreasuriesResponse)
async def list_treasuries(
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> TreasuriesResponse:
    # The organization scope comes from the authenticated membership. Keep each
    # treasury as its own row: balances, limits, and counters have no cross-chain
    # aggregate until a pricing source exists.
    rows = await _service(request).list_for_org(organization_id=member.organization_id)
    configuration: PlatformConfiguration = request.app.state.platform_configuration
    chains = {chain.chain_id: chain for chain in configuration.chains}
    assets_by_chain = {
        chain.chain_id: {asset_id(chain.chain_id, item.address): item for item in chain.assets}
        for chain in configuration.chains
    }
    items: list[TreasurySummaryView] = []
    for row in rows:
        chain = chains.get(row.chain_id)
        asset = assets_by_chain.get(row.chain_id, {}).get(row.asset_id)
        # Persisted assets are validated against this startup configuration. If an
        # operator removes a config entry after deployment, keep the row visible by
        # id without inventing a cross-chain symbol or valuation.
        items.append(
            TreasurySummaryView(
                id=row.id,
                chain_id=row.chain_id,
                chain_name=chain.name if chain is not None else f"Chain {row.chain_id}",
                asset_id=row.asset_id,
                asset_symbol=asset.symbol if asset is not None else "Unknown asset",
                asset_decimals=asset.decimals if asset is not None else None,
                asset_is_test=asset.is_test if asset is not None else None,
                status=row.status,
                coverage=row.coverage,
                coverage_details=list(row.coverage_details),
                created_at=row.created_at,
            )
        )
    return TreasuriesResponse(items=items)


async def _extras(
    request: Request, member: MemberAccess, record: TreasuryRecord
) -> TreasuryExtras | None:
    """The dashboard parts; None where no request storage is configured (the stored treasury
    alone is still served)."""

    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        return None
    configuration: PlatformConfiguration = request.app.state.platform_configuration
    asset = next(
        (
            item
            for chain in configuration.chains
            if chain.chain_id == record.chain_id
            for item in chain.assets
            if asset_id(chain.chain_id, item.address) == record.asset_id
        ),
        None,
    )
    async with sessions() as session:
        return await load_extras(
            session,
            record,
            roles=frozenset(str(role) for role in member.roles),
            symbol=asset.symbol if asset is not None else "tokens",
            decimals=asset.decimals if asset is not None else 0,
        )


@router.get(
    "/orgs/{organization_id}/treasuries/{treasury_id}",
    response_model=TreasuryResponse,
    response_model_exclude_unset=True,
)
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
    return TreasuryResponse.from_record(record, await _extras(request, member, record))


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
