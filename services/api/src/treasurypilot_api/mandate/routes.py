from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.configuration import (
    MandateConfig,
    MandateValidationError,
    build_bundle_preview,
    build_diff,
    build_summary,
    validate_mandate_config,
)
from treasurypilot_api.mandate.models import MandateVersion, MandateVersionStatus
from treasurypilot_api.treasury.models import Asset, Treasury, TreasuryWallet


@dataclass(frozen=True, slots=True)
class MandateContext:
    asset_decimals: int
    asset_symbol: str
    wallets: dict[str, str]
    active_config: dict[str, object] | None
    primary_asset_id: uuid.UUID | None = None
    asset_metadata: dict[str, dict[str, object]] | None = None


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
    ) -> tuple[MandateVersionRecord, ...] | None:
        """Return the versions newest first, or ``None`` if the treasury is not visible."""
        ...

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
        build_config: Callable[[MandateContext], dict[str, object]],
    ) -> tuple[MandateVersionRecord, MandateContext] | None:
        """Insert a draft built from the context read under the treasury row lock."""
        ...

    async def discard_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None: ...


def _config_time(config: dict[str, object], key: str) -> datetime | None:
    value = config.get(key)
    return datetime.fromisoformat(value) if isinstance(value, str) else None


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


async def _load_context(
    session: AsyncSession, organization_id: uuid.UUID, treasury_id: uuid.UUID
) -> MandateContext | None:
    row = await session.execute(
        select(Treasury.id, Treasury.asset_id, Treasury.chain_id, Asset.decimals, Asset.symbol)
        .join(Asset, (Asset.id == Treasury.asset_id) & (Asset.chain_id == Treasury.chain_id))
        .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
    )
    treasury = row.one_or_none()
    if treasury is None:
        return None
    chain_assets = await session.scalars(select(Asset).where(Asset.chain_id == treasury.chain_id))
    asset_metadata = {
        str(item.id): {
            "symbol": item.symbol,
            "decimals": item.decimals,
            "address": "0x" + item.address.hex(),
        }
        for item in chain_assets
        if item.address is not None and not item.is_native
    }
    wallets = await session.scalars(
        select(TreasuryWallet).where(
            TreasuryWallet.treasury_id == treasury_id,
            TreasuryWallet.org_id == organization_id,
        )
    )
    wallet_roles = {f"0x{wallet.safe_address.hex()}": wallet.role.value for wallet in wallets}
    active = await session.scalar(
        select(MandateVersion)
        .where(
            MandateVersion.treasury_id == treasury_id,
            MandateVersion.status == MandateVersionStatus.ACTIVE,
        )
        .order_by(MandateVersion.version.desc())
        .limit(1)
    )
    return MandateContext(
        asset_decimals=treasury.decimals,
        asset_symbol=treasury.symbol,
        wallets=wallet_roles,
        active_config=dict(active.config) if active is not None else None,
        primary_asset_id=treasury.asset_id,
        asset_metadata=asset_metadata,
    )


class SqlAlchemyMandateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> MandateContext | None:
        async with self._sessions() as session:
            return await _load_context(session, organization_id, treasury_id)

    async def list_versions(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[MandateVersionRecord, ...] | None:
        # One round trip: the outer join yields a single NULL row for a visible
        # treasury without versions and no row at all for an invisible one.
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(MandateVersion)
                    .select_from(Treasury)
                    .outerjoin(MandateVersion, MandateVersion.treasury_id == Treasury.id)
                    .where(Treasury.org_id == organization_id, Treasury.id == treasury_id)
                    .order_by(MandateVersion.version.desc())
                )
            ).scalars()
            found = rows.all()
            if not found:
                return None
            return tuple(_record(row) for row in found if row is not None)

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
        build_config: Callable[[MandateContext], dict[str, object]],
    ) -> tuple[MandateVersionRecord, MandateContext] | None:
        async with self._sessions() as session, session.begin():
            treasury = await session.scalar(
                select(Treasury)
                .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
                .with_for_update()
            )
            if treasury is None:
                return None
            # Read under the row lock so validation and the diff see a consistent state.
            context = await _load_context(session, organization_id, treasury_id)
            if context is None:
                return None
            config = build_config(context)
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
                org_id=organization_id,
                treasury_id=treasury_id,
                version=int(latest_version or 0) + 1,
                status=MandateVersionStatus.DRAFT,
                config=config,
                config_hash=hashlib.sha256(canonical_config).digest(),
                valid_from=_config_time(config, "validFrom"),
                expires_at=_config_time(config, "expiresAt"),
                created_by=user_id,
            )
            session.add(row)
            await session.flush()
            return _record(row), context

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
            if row.status == MandateVersionStatus.DRAFT:
                await session.delete(row)
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
        summary=build_summary(
            config,
            decimals=context.asset_decimals,
            symbol=context.asset_symbol,
            asset_metadata=context.asset_metadata,
        ),
        diff=diff,
        requires_confirmation=any(item["requiresConfirmation"] for item in diff),
        bundle_preview=build_bundle_preview(
            context.active_config, row.config, asset_metadata=context.asset_metadata
        ),
    )


router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}/mandates", tags=["mandates"]
)


@router.get("", response_model=MandateListResponse, openapi_extra={"x-organization-scoped": True})
async def list_mandates(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> MandateListResponse:
    rows = await _repository(request).list_versions(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
    )
    if rows is None:
        raise _not_found()
    return MandateListResponse(items=[MandateView.from_record(row) for row in rows])


async def _create_draft(
    *,
    request: Request,
    response: Response,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    member: MemberAccess,
    payload: MandateConfig,
    enforce_future_expiry: bool,
) -> MandateDraftResponse:
    environment = request.app.state.settings.environment

    def build_config(context: MandateContext) -> dict[str, object]:
        validate_mandate_config(
            payload,
            known_wallets=context.wallets,
            environment=environment,
            asset_decimals=context.asset_decimals,
            now=datetime.now(UTC),
            enforce_future_expiry=enforce_future_expiry,
            primary_asset_id=context.primary_asset_id,
            asset_metadata=context.asset_metadata,
        )
        return payload.json_config(environment=environment, asset_decimals=context.asset_decimals)

    try:
        created = await _repository(request).create_draft(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            build_config=build_config,
        )
    except MandateValidationError as error:
        raise _validation_failure(error) from None
    if created is None:
        raise _not_found()
    row, context = created
    response.headers["Location"] = (
        f"/v1/orgs/{organization_id}/treasuries/{treasury_id}/mandates/{row.id}"
    )
    return _draft_response(row, MandateConfig.model_validate(row.config), context=context)


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
    member: MemberAccess = Depends(require_role(OrganizationRole.OWNER, step_up=True)),  # noqa: B008
) -> MandateDraftResponse:
    return await _create_draft(
        request=request,
        response=response,
        organization_id=organization_id,
        treasury_id=treasury_id,
        member=member,
        payload=payload,
        enforce_future_expiry=True,
    )


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
    member: MemberAccess = Depends(require_role(OrganizationRole.OWNER, step_up=True)),  # noqa: B008
) -> MandateDraftResponse:
    source = await _repository(request).get_version(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        mandate_id=mandate_id,
    )
    if source is None:
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
    # Cloning is how an expired mandate is renewed, so the old expiry is not rejected here.
    return await _create_draft(
        request=request,
        response=response,
        organization_id=organization_id,
        treasury_id=treasury_id,
        member=member,
        payload=config_model,
        enforce_future_expiry=False,
    )


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
    member: MemberAccess = Depends(require_role(OrganizationRole.OWNER, step_up=True)),  # noqa: B008
) -> Response:
    row = await _repository(request).discard_draft(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        mandate_id=mandate_id,
    )
    if row is None:
        raise _not_found()
    if row.status != MandateVersionStatus.DRAFT:
        raise AuthFailure(
            status=409,
            code="NOT_DRAFT",
            title="Mandate is not a draft",
            detail="Only a Draft mandate version can be discarded.",
        )
    return Response(status_code=204)
