"""Guardian Safe setup and sentinel health (MDT-010, ADR-017, BR-068).

The Guardian Safe is a threshold-1 Safe whose owners are the human guardian(s) and the sentinel
address served by the signer. ``POST /guardian/setup-tx`` builds the Safe Proxy Factory deployment
for an owner's wallet; ``POST /guardian/confirm`` verifies the deployed Safe on-chain and records
the ``guardian_setups`` row, which becomes the default ``mandate.guardian``. ``GET /guardian/health``
re-reads the Safe so a sentinel that was removed (or ran out of gas) shows a warning instead of
silently losing the automatic on-chain pause.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import urllib.request
import uuid
from typing import Annotated, Any, cast
from urllib.error import URLError

from eth_utils import to_checksum_address
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.models import GuardianSetup, GuardianSetupStatus
from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import Treasury
from treasurypilot_api.treasury.safe import (
    RpcSafeVerifier,
    RpcUnavailable,
    SafeDeploymentCodeMismatch,
    SafeDeploymentUnavailable,
    SafeInfo,
    SafeVerificationError,
    SafeVerifier,
    UnsupportedChain,
    build_safe_deployment_transaction,
    verify_safe_deployment_code,
)

router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}/guardian",
    tags=["guardian"],
)

_ADDRESS = r"^0x[0-9a-fA-F]{40}$"


class GuardianSetupRequest(ApiModel):
    human_owners: list[Annotated[str, Field(pattern=_ADDRESS)]] = Field(
        alias="humanOwners", min_length=1, max_length=9
    )


class GuardianDeployTransaction(ApiModel):
    to: str
    data: str
    value: str


class GuardianSetupTxResponse(ApiModel):
    chain_id: int
    sentinel_address: str
    owners: list[str]
    threshold: int
    transaction: GuardianDeployTransaction


class GuardianConfirmRequest(ApiModel):
    guardian_safe: str = Field(alias="guardianSafe", pattern=_ADDRESS)


class GuardianSetupView(ApiModel):
    id: str
    guardian_safe: str
    human_owners: list[str]
    sentinel_address: str
    threshold: int
    status: GuardianSetupStatus


class GuardianConfirmResponse(ApiModel):
    guardian_setup: GuardianSetupView
    # The value a mandate's ``guardian`` field defaults to.
    mandate_guardian: str


class GuardianWarning(ApiModel):
    code: str
    message: str


class GuardianHealthResponse(ApiModel):
    configured: bool
    guardian_setup: GuardianSetupView | None = None
    onchain_owners: list[str] = Field(default_factory=list)
    sentinel_is_owner: bool = False
    sentinel_balance_wei: str | None = None
    min_gas_wei: str
    has_gas: bool = False
    # True only when the sentinel can really pause: it owns the Safe and has gas.
    automatic_pause_available: bool = False
    warnings: list[GuardianWarning]


def _fail(status: int, code: str, title: str, detail: str, retry_after: int | None = None) -> Any:
    return AuthFailure(
        status=status, code=code, title=title, detail=detail, retry_after=retry_after
    )


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _fail(
            503, "GUARDIAN_UNAVAILABLE", "Guardian unavailable", "Storage is not configured."
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


def _configuration(request: Request) -> PlatformConfiguration:
    return cast(PlatformConfiguration, request.app.state.platform_configuration)


def _verifier(request: Request) -> SafeVerifier:
    injected = getattr(request.app.state, "guardian_safe_verifier", None)
    return cast(SafeVerifier, injected or RpcSafeVerifier(_configuration(request)))


def _rpc_unavailable() -> Any:
    return _fail(
        503,
        "RPC_UNAVAILABLE",
        "Chain RPC unavailable",
        "The Guardian Safe could not be read from the configured chain RPCs.",
        retry_after=5,
    )


def _text(raw: bytes) -> str:
    return "0x" + bytes(raw).hex()


def _view(row: GuardianSetup) -> GuardianSetupView:
    return GuardianSetupView(
        id=str(row.id),
        guardian_safe=to_checksum_address(_text(row.guardian_safe)),
        human_owners=[to_checksum_address(_text(owner)) for owner in row.human_owners],
        sentinel_address=to_checksum_address(_text(row.sentinel_address)),
        threshold=row.threshold,
        status=row.status,
    )


async def _load_treasury(
    session: AsyncSession, organization_id: uuid.UUID, treasury_id: uuid.UUID
) -> Treasury:
    treasury = await session.scalar(
        select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
    )
    if treasury is None:
        raise _fail(404, "TREASURY_NOT_FOUND", "Treasury not found", "Treasury not found.")
    return treasury


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


_NO_REDIRECT = urllib.request.build_opener(_RefuseRedirect)


async def _sentinel_address(request: Request) -> str:
    """The sentinel address from the signer (``GET /sentinel/address``)."""
    settings = request.app.state.settings
    secret = settings.signer_shared_secret
    unavailable = _fail(
        503,
        "SENTINEL_UNAVAILABLE",
        "Sentinel unavailable",
        "The signer does not expose a sentinel address. Configure the sentinel key first.",
        retry_after=30,
    )
    if not settings.signer_url or secret is None:
        raise unavailable
    http = urllib.request.Request(  # noqa: S310 - scheme is validated as http(s) in Settings
        settings.signer_url.rstrip("/") + "/sentinel/address",
        headers={"X-Signer-Secret": secret.get_secret_value()},
        method="GET",
    )

    def fetch() -> dict[str, Any]:
        # shortcut: urllib in a thread, as in pause.py; redirects are refused so the secret stays put.
        with _NO_REDIRECT.open(http, timeout=10) as response:
            return cast(dict[str, Any], json.loads(response.read()))

    try:
        address = str((await asyncio.to_thread(fetch)).get("address", ""))
        return to_checksum_address(address)
    except (URLError, OSError, ValueError):
        raise unavailable from None


@router.post("/setup-tx", response_model=GuardianSetupTxResponse)
async def guardian_setup_transaction(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: GuardianSetupRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER))],
) -> GuardianSetupTxResponse:
    """Build the Safe Proxy Factory call that deploys the 1-of-N Guardian Safe."""
    async with _sessions(request)() as session:
        treasury = await _load_treasury(session, member.organization_id, treasury_id)
    sentinel = await _sentinel_address(request)
    owners = [*payload.human_owners, sentinel]
    configuration = _configuration(request)
    try:
        await verify_safe_deployment_code(configuration, treasury.chain_id)
        transaction = build_safe_deployment_transaction(
            configuration, treasury.chain_id, owners, 1, secrets.randbits(256)
        )
    except SafeDeploymentCodeMismatch:
        raise _fail(
            503,
            "SAFE_DEPLOYMENT_VERIFICATION_FAILED",
            "Safe deployment verification failed",
            "The configured Safe deployments do not match their recorded runtime code hashes.",
        ) from None
    except (SafeDeploymentUnavailable, UnsupportedChain):
        raise _fail(
            503,
            "SAFE_DEPLOYMENT_UNAVAILABLE",
            "Safe deployment unavailable",
            "This chain has no verified Safe proxy factory, singleton and fallback handler.",
            retry_after=60,
        ) from None
    except RpcUnavailable:
        raise _rpc_unavailable() from None
    except ValueError as exc:
        raise _fail(422, "INVALID_GUARDIAN_OWNERS", "Guardian owners rejected", str(exc)) from None
    return GuardianSetupTxResponse(
        chain_id=treasury.chain_id,
        sentinel_address=sentinel,
        owners=[to_checksum_address(owner) for owner in owners],
        threshold=1,
        transaction=GuardianDeployTransaction(**transaction),
    )


async def _verified_safe(request: Request, chain_id: int, address: str) -> SafeInfo:
    try:
        (info,) = await _verifier(request).verify(chain_id, [address])
    except RpcUnavailable:
        raise _rpc_unavailable() from None
    except SafeVerificationError as exc:
        raise _fail(422, exc.code, "Guardian Safe rejected", exc.detail) from None
    return info


@router.post("/confirm", status_code=201, response_model=GuardianConfirmResponse)
async def confirm_guardian_safe(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: GuardianConfirmRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> GuardianConfirmResponse:
    """Record a deployed Guardian Safe after checking its owners and threshold on-chain."""
    async with _sessions(request)() as session:
        treasury = await _load_treasury(session, member.organization_id, treasury_id)
    sentinel = await _sentinel_address(request)
    info = await _verified_safe(request, treasury.chain_id, payload.guardian_safe)
    owners = {owner.lower() for owner in info.owners}
    if info.threshold != 1:
        raise _fail(
            422,
            "GUARDIAN_THRESHOLD_INVALID",
            "Guardian Safe rejected",
            "The Guardian Safe must have threshold 1 so any single guardian can pause.",
        )
    if sentinel.lower() not in owners:
        raise _fail(
            422,
            "SENTINEL_NOT_OWNER",
            "Guardian Safe rejected",
            "The sentinel address is not an owner of this Safe.",
        )
    humans = [owner for owner in info.owners if owner.lower() != sentinel.lower()]
    if not humans:
        raise _fail(
            422,
            "GUARDIAN_HUMAN_OWNER_MISSING",
            "Guardian Safe rejected",
            "The Guardian Safe needs at least one human owner besides the sentinel.",
        )
    safe_bytes = bytes.fromhex(info.address[2:])
    async with _sessions(request)() as session, session.begin():
        await _load_treasury(session, member.organization_id, treasury_id)
        # Serialize concurrent confirmations for one treasury on the treasury row.
        await session.execute(
            select(Treasury.id).where(Treasury.id == treasury_id).with_for_update()
        )
        current = await session.scalar(
            select(GuardianSetup).where(
                GuardianSetup.treasury_id == treasury_id,
                GuardianSetup.status == GuardianSetupStatus.ACTIVE,
            )
        )
        if current is not None and bytes(current.guardian_safe) == safe_bytes:
            row = current
            row.human_owners = [bytes.fromhex(owner[2:]) for owner in humans]
            row.sentinel_address = bytes.fromhex(sentinel[2:])
        else:
            await session.execute(
                update(GuardianSetup)
                .where(
                    GuardianSetup.treasury_id == treasury_id,
                    GuardianSetup.status == GuardianSetupStatus.ACTIVE,
                )
                .values(status=GuardianSetupStatus.SUPERSEDED)
            )
            row = GuardianSetup(
                org_id=member.organization_id,
                treasury_id=treasury_id,
                guardian_safe=safe_bytes,
                human_owners=[bytes.fromhex(owner[2:]) for owner in humans],
                sentinel_address=bytes.fromhex(sentinel[2:]),
                threshold=1,
                status=GuardianSetupStatus.ACTIVE,
                created_by=member.user_id,
                updated_by=member.user_id,
            )
            session.add(row)
        await session.flush()
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="treasury.guardian_safe_recorded",
                entity_type="treasury",
                entity_id=treasury_id,
                data={"guardianSafe": info.address, "humanOwners": len(humans)},
            ),
        )
        view = _view(row)
    return GuardianConfirmResponse(guardian_setup=view, mandate_guardian=info.address.lower())


@router.get("/health", response_model=GuardianHealthResponse)
async def guardian_health(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> GuardianHealthResponse:
    """Is the sentinel still an owner of the Guardian Safe, and does it have gas?"""
    minimum = int(request.app.state.settings.sentinel_min_gas_wei)
    async with _sessions(request)() as session:
        treasury = await _load_treasury(session, member.organization_id, treasury_id)
        setup = await session.scalar(
            select(GuardianSetup).where(
                GuardianSetup.treasury_id == treasury_id,
                GuardianSetup.status == GuardianSetupStatus.ACTIVE,
            )
        )
    if setup is None:
        return GuardianHealthResponse(
            configured=False,
            min_gas_wei=str(minimum),
            warnings=[
                GuardianWarning(
                    code="GUARDIAN_NOT_SET_UP",
                    message="No Guardian Safe is set up, so there is no automatic on-chain pause.",
                )
            ],
        )
    view = _view(setup)
    warnings: list[GuardianWarning] = []
    try:
        info = await _verified_safe(request, treasury.chain_id, view.guardian_safe)
    except AuthFailure as failure:
        if failure.status == 503:
            raise
        return GuardianHealthResponse(
            configured=True,
            guardian_setup=view,
            min_gas_wei=str(minimum),
            warnings=[
                GuardianWarning(
                    code="GUARDIAN_SAFE_INVALID",
                    message="The recorded Guardian Safe no longer verifies on-chain. "
                    "Automatic on-chain pause is disabled.",
                )
            ],
        )
    sentinel = view.sentinel_address
    is_owner = sentinel.lower() in {owner.lower() for owner in info.owners}
    balance: int | None = None
    try:
        balance = int(
            str(
                await RpcSafeVerifier(_configuration(request)).call(
                    treasury.chain_id, "eth_getBalance", [sentinel, "latest"]
                )
            ),
            16,
        )
    except RpcUnavailable:
        raise _rpc_unavailable() from None
    has_gas = balance >= minimum
    if not is_owner:
        warnings.append(
            GuardianWarning(
                code="SENTINEL_NOT_OWNER",
                message="The sentinel is no longer an owner of the Guardian Safe. Automatic "
                "on-chain pause is disabled; a human guardian must pause from their wallet.",
            )
        )
    if not has_gas:
        warnings.append(
            GuardianWarning(
                code="SENTINEL_LOW_GAS",
                message="The sentinel address is low on gas and may be unable to pause. "
                "Send it a small ETH balance.",
            )
        )
    if info.threshold != 1:
        warnings.append(
            GuardianWarning(
                code="GUARDIAN_THRESHOLD_CHANGED",
                message="The Guardian Safe threshold is no longer 1, so the sentinel alone "
                "cannot pause.",
            )
        )
    return GuardianHealthResponse(
        configured=True,
        guardian_setup=view,
        onchain_owners=list(info.owners),
        sentinel_is_owner=is_owner,
        sentinel_balance_wei=str(balance),
        min_gas_wei=str(minimum),
        has_gas=has_gas,
        automatic_pause_available=is_owner and has_gas and info.threshold == 1,
        warnings=warnings,
    )
