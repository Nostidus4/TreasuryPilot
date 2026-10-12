from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.access import MemberContext, require_member, require_role
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import uuid7
from treasurypilot_api.mandate.configuration import (
    MandateConfig,
    MandateValidationError,
    build_bundle_preview,
    build_diff,
    build_summary,
    validate_mandate_config,
)
from treasurypilot_api.mandate.models import MandateVersion
from treasurypilot_api.treasury.models import Asset, Treasury, TreasuryWallet


@dataclass(frozen=True, slots=True)
class MandateContext:
    asset_decimals: int
    asset_symbol: str
    wallets: dict[str, str]
    active_config: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class MandateVersionRecord:
    id: uuid.UUID
    treasury_id: uuid.UUID
    version: int
    status: str
    config: dict[str, object]
    config_hash: bytes
    created_at: datetime


class MandateRepository(Protocol):
    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> MandateContext | None: ...

    async def list_versions(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[MandateVersionRecord, ...]: ...

    async def get_version(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None: ...

    async def create_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        config: dict[str, object],
    ) -> MandateVersionRecord | None: ...

    async def discard_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None: ...


def _record(row: MandateVersion) -> MandateVersionRecord:
    return MandateVersionRecord(
        id=row.id,
        treasury_id=row.treasury_id,
        version=row.version,
        status=row.status,
        config=dict(row.config),
        config_hash=row.config_hash,
        created_at=row.created_at,
    )


class SqlAlchemyMandateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> MandateContext | None:
        async with self._sessions() as session:
            row = await session.execute(
                select(Treasury.id, Asset.decimals, Asset.symbol)
                .join(
                    Asset, (Asset.id == Treasury.asset_id) & (Asset.chain_id == Treasury.chain_id)
                )
                .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
            )
            treasury = row.one_or_none()
            if treasury is None:
                return None
            wallets = await session.scalars(
                select(TreasuryWallet).where(
                    TreasuryWallet.treasury_id == treasury_id,
                    TreasuryWallet.org_id == organization_id,
                )
            )
            wallet_roles = {
                f"0x{wallet.safe_address.hex()}": wallet.role.value for wallet in wallets
            }
            active = await session.scalar(
                select(MandateVersion)
                .where(
                    MandateVersion.treasury_id == treasury_id,
                    MandateVersion.status == "Active",
                )
                .order_by(MandateVersion.version.desc())
                .limit(1)
            )
            return MandateContext(
                asset_decimals=treasury.decimals,
                asset_symbol=treasury.symbol,
                wallets=wallet_roles,
                active_config=dict(active.config) if active is not None else None,
            )

    async def list_versions(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[MandateVersionRecord, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MandateVersion)
                .join(Treasury, Treasury.id == MandateVersion.treasury_id)
                .where(
                    Treasury.org_id == organization_id,
                    Treasury.id == treasury_id,
                )
                .order_by(MandateVersion.version.desc())
            )
            return tuple(_record(row) for row in rows)

    async def get_version(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(MandateVersion)
                .join(Treasury, Treasury.id == MandateVersion.treasury_id)
                .where(
                    Treasury.org_id == organization_id,
                    Treasury.id == treasury_id,
                    MandateVersion.id == mandate_id,
                )
            )
            return _record(row) if row is not None else None

    async def create_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        config: dict[str, object],
    ) -> MandateVersionRecord | None:
        async with self._sessions() as session, session.begin():
            treasury = await session.scalar(
                select(Treasury)
                .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
                .with_for_update()
            )
            if treasury is None:
                return None
            latest_version = await session.scalar(
                select(func.max(MandateVersion.version)).where(
                    MandateVersion.treasury_id == treasury_id
                )
            )
            canonical_config = json.dumps(
                config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            row = MandateVersion(
                id=uuid7(),
                treasury_id=treasury_id,
                version=int(latest_version or 0) + 1,
                status="Draft",
                config=config,
                config_hash=hashlib.sha256(canonical_config).digest(),
                created_by=user_id,
            )
            session.add(row)
            await session.flush()
            return _record(row)

    async def discard_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(MandateVersion)
                .join(Treasury, Treasury.id == MandateVersion.treasury_id)
                .where(
                    Treasury.org_id == organization_id,
                    Treasury.id == treasury_id,
                    MandateVersion.id == mandate_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            if row.status == "Draft":
                row.status = "Discarded"
                await session.flush()
            return _record(row)


class MandateView(ApiModel):
    id: uuid.UUID
    treasury_id: uuid.UUID
    version: int
    status: str
    config: dict[str, object]
    config_hash: str
    created_at: datetime

    @classmethod
    def from_record(cls, row: MandateVersionRecord) -> MandateView:
        return cls(
            id=row.id,
            treasury_id=row.treasury_id,
            version=row.version,
            status=row.status,
            config=row.config,
            config_hash=f"0x{row.config_hash.hex()}",
            created_at=row.created_at,
        )


class MandateDraftResponse(ApiModel):
    draft: MandateView
    summary: list[dict[str, str]]
    diff: list[dict[str, object]]
    requires_confirmation: bool
    bundle_preview: dict[str, object]


class MandateListResponse(ApiModel):
    items: list[MandateView]


def _repository(request: Request) -> MandateRepository:
    repository = getattr(request.app.state, "mandate_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="MANDATE_UNAVAILABLE",
            title="Mandate service unavailable",
            detail="Mandate storage is not configured.",
        )
    return cast(MandateRepository, repository)


def _not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="TREASURY_NOT_FOUND",
        title="Treasury not found",
        detail="The treasury or mandate is not available to this user.",
    )


def _validation_failure(error: MandateValidationError) -> AuthFailure:
    extensions: dict[str, object] | None = (
        {"fields": error.fields} if error.fields is not None else None
    )
    return AuthFailure(
        status=422,
        code=error.code,
        title="Mandate validation failed",
        detail=error.detail,
        extensions=extensions,
    )


def _draft_response(
    row: MandateVersionRecord,
    config: MandateConfig,
    *,
    context: MandateContext,
) -> MandateDraftResponse:
    diff = build_diff(context.active_config, row.config)
    return MandateDraftResponse(
        draft=MandateView.from_record(row),
        summary=build_summary(config, decimals=context.asset_decimals, symbol=context.asset_symbol),
        diff=diff,
        requires_confirmation=any(item["requiresConfirmation"] for item in diff),
        bundle_preview=build_bundle_preview(context.active_config, row.config),
    )


router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}/mandates", tags=["mandates"]
)


@router.get("", response_model=MandateListResponse, openapi_extra={"x-organization-scoped": True})
async def list_mandates(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> MandateListResponse:
    context = await _repository(request).get_context(
        organization_id=organization_id, treasury_id=treasury_id
    )
    if context is None:
        raise _not_found()
    rows = await _repository(request).list_versions(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
    )
    return MandateListResponse(items=[MandateView.from_record(row) for row in rows])


@router.post(
    "",
    status_code=201,
    response_model=MandateDraftResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def create_mandate_draft(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: MandateConfig,
    request: Request,
    response: Response,
    member: MemberContext = Depends(require_role("Owner")),  # noqa: B008
) -> MandateDraftResponse:
    repository = _repository(request)
    context = await repository.get_context(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
    )
    if context is None:
        raise _not_found()
    environment = request.app.state.settings.environment
    try:
        validate_mandate_config(
            payload,
            known_wallets=context.wallets,
            environment=environment,
            asset_decimals=context.asset_decimals,
        )
    except MandateValidationError as error:
        raise _validation_failure(error) from None
    config = payload.json_config(environment=environment, asset_decimals=context.asset_decimals)
    normalized_config = MandateConfig.model_validate(config)
    row = await repository.create_draft(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        user_id=member.user_id,
        config=config,
    )
    if row is None:
        raise _not_found()
    response.headers["Location"] = (
        f"/v1/orgs/{organization_id}/treasuries/{treasury_id}/mandates/{row.id}"
    )
    return _draft_response(row, normalized_config, context=context)


@router.post(
    "/{mandate_id}/clone",
    status_code=201,
    response_model=MandateDraftResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def clone_mandate_draft(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    mandate_id: uuid.UUID,
    request: Request,
    response: Response,
    member: MemberContext = Depends(require_role("Owner")),  # noqa: B008
) -> MandateDraftResponse:
    repository = _repository(request)
    context = await repository.get_context(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
    )
    source = await repository.get_version(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        mandate_id=mandate_id,
    )
    if context is None or source is None:
        raise _not_found()
    try:
        config_model = MandateConfig.model_validate(source.config)
    except ValueError:
        raise AuthFailure(
            status=409,
            code="MANDATE_CONFIG_UNSUPPORTED",
            title="Mandate cannot be cloned",
            detail="The stored mandate configuration is incompatible with the current schema.",
        ) from None
    environment = request.app.state.settings.environment
    try:
        validate_mandate_config(
            config_model,
            known_wallets=context.wallets,
            environment=environment,
            asset_decimals=context.asset_decimals,
        )
    except MandateValidationError as error:
        raise _validation_failure(error) from None
    config = config_model.json_config(
        environment=environment, asset_decimals=context.asset_decimals
    )
    normalized_config = MandateConfig.model_validate(config)
    row = await repository.create_draft(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        user_id=member.user_id,
        config=config,
    )
    if row is None:
        raise _not_found()
    response.headers["Location"] = (
        f"/v1/orgs/{organization_id}/treasuries/{treasury_id}/mandates/{row.id}"
    )
    return _draft_response(row, normalized_config, context=context)


@router.delete(
    "/{mandate_id}",
    status_code=204,
    response_model=None,
    openapi_extra={"x-organization-scoped": True},
)
async def discard_mandate_draft(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    mandate_id: uuid.UUID,
    request: Request,
    member: MemberContext = Depends(require_role("Owner")),  # noqa: B008
) -> Response:
    row = await _repository(request).discard_draft(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        mandate_id=mandate_id,
    )
    if row is None:
        raise _not_found()
    if row.status != "Discarded":
        raise AuthFailure(
            status=409,
            code="NOT_DRAFT",
            title="Mandate is not a draft",
            detail="Only a Draft mandate version can be discarded.",
        )
    return Response(status_code=204)
