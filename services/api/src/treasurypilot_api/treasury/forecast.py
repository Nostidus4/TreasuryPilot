"""Runway forecast read model (WEB-021, API_SPEC section 5): the engine's 7-day projection."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus
from treasurypilot_api.invoices.requests import confirmed_payment_terms
from treasurypilot_api.mandate.configuration import MandateConfig
from treasurypilot_api.mandate.models import MandateVersion, MandateVersionStatus, Payee
from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import WalletRole
from treasurypilot_api.treasury.service import TreasuryNotFound, TreasuryRecord, TreasuryService
from treasurypilot_api.treasury.sync import asset_id
from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import forecast
from treasurypilot_core.money import BaseUnits

router = APIRouter(prefix="/v1", tags=["treasury"])

_DAYS = 7
_BALANCE_OF = "0x70a08231"  # bytes4(keccak256("balanceOf(address)"))
# Same set the web chart treats as committed outflow; drafts are opt-in.
_COMMITTED = (RequestStatus.APPROVED, RequestStatus.SCHEDULED, RequestStatus.AWAITING_APPROVAL)


class ForecastDay(ApiModel):
    date: str
    balance: str
    outflow: str
    buffer: str


class ForecastWalletDay(ApiModel):
    date: str
    balance: str


class ForecastWallet(ApiModel):
    role: str
    label: str
    safe_address: str
    buffer: str
    days: list[ForecastWalletDay]


class ForecastRefill(ApiModel):
    date: str
    source_address: str
    target_address: str
    amount: str
    request_id: str


class ForecastAlert(ApiModel):
    date: str
    message: str


class ForecastResponse(ApiModel):
    days: list[ForecastDay]
    wallets: list[ForecastWallet]
    suggested_refills: list[ForecastRefill]
    alerts: list[ForecastAlert]


def _fail(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=status, code=code, title=code.replace("_", " ").title(), detail=detail
    )


def _iso(day: int) -> str:
    return (date(1970, 1, 1) + timedelta(days=day)).isoformat()


async def _balance(request: Request, chain_id: int, token: str, holder: str) -> int:
    provider = getattr(request.app.state, "fee_history_provider", None)  # the shared RPC client
    if provider is None:
        raise _fail(503, "FORECAST_UNAVAILABLE", "No chain RPC client is configured.")
    data = _BALANCE_OF + holder.removeprefix("0x").lower().rjust(64, "0")
    try:
        result = await provider.call(chain_id, "eth_call", [{"to": token, "data": data}, "latest"])
        return int(result, 16)
    except Exception as error:
        raise _fail(503, "FORECAST_UNAVAILABLE", "Wallet balances could not be read.") from error


def _mandate_inputs(config: MandateConfig) -> tuple[PolicyView, dict[str, tuple[int, int]]]:
    limits = config.limits or {}
    pay = limits.get("PAY")
    if pay is None:
        raise _fail(409, "MANDATE_NOT_ACTIVE", "The active mandate has no PAY limits.")
    refill = limits.get("REFILL", pay)
    policy = PolicyView(
        pay=Limits(per_request=pay.per_request, daily=pay.daily),
        refill=Limits(per_request=refill.per_request, daily=refill.daily),
        cooling_seconds=config.payee_cooling_seconds or 0,
    )
    buffers = {
        item.wallet: (
            int(item.minimum),
            int(item.target if item.target is not None else item.minimum),
        )
        for item in config.buffers or []
    }
    return policy, buffers


@router.get(
    "/orgs/{organization_id}/treasuries/{treasury_id}/forecast",
    response_model=ForecastResponse,
)
async def get_forecast(
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
    include_drafts: Annotated[bool, Query(alias="includeDrafts")] = False,
) -> ForecastResponse:
    service = getattr(request.app.state, "treasury_service", None)
    factory = getattr(request.app.state, "request_sessions", None)
    if service is None or factory is None:
        raise _fail(503, "TREASURY_UNAVAILABLE", "Treasury storage is not configured.")
    try:
        record: TreasuryRecord = await cast(TreasuryService, service).get(
            organization_id=member.organization_id, treasury_id=treasury_id
        )
    except TreasuryNotFound:
        raise _fail(
            404, "TREASURY_NOT_FOUND", "The treasury does not exist in this organization."
        ) from None
    source = next((w for w in record.wallets if w.role == WalletRole.SOURCE), None)
    operational = [w for w in record.wallets if w.role == WalletRole.OPERATIONAL]  # O1, O2 by label
    if source is None or not operational:
        raise _fail(409, "TREASURY_NOT_READY", "The treasury has no source and payments wallet.")
    statuses = [*_COMMITTED, *([RequestStatus.DRAFT] if include_drafts else [])]
    sessions = cast(async_sessionmaker[AsyncSession], factory)
    async with sessions() as session:
        config = await session.scalar(
            select(MandateVersion.config).where(
                MandateVersion.org_id == member.organization_id,
                MandateVersion.treasury_id == treasury_id,
                MandateVersion.status == MandateVersionStatus.ACTIVE,
            )
        )
        if config is None:
            raise _fail(409, "MANDATE_NOT_ACTIVE", "The treasury has no active mandate.")
        rows = list(
            await session.scalars(
                select(PaymentRequest)
                .where(
                    PaymentRequest.org_id == member.organization_id,
                    PaymentRequest.treasury_id == treasury_id,
                    PaymentRequest.status.in_(statuses),
                    PaymentRequest.amount.is_not(None),
                    PaymentRequest.payee_id.is_not(None),
                )
                .order_by(PaymentRequest.id)
            )
        )
        payees = await session.execute(
            select(Payee.id, Payee.active_from).where(Payee.id.in_({r.payee_id for r in rows}))
        )
        active_from = {pid: at for pid, at in payees}
    mandate = MandateConfig.model_validate(config)
    policy, mandate_buffers = _mandate_inputs(mandate)

    configuration: PlatformConfiguration = request.app.state.platform_configuration
    token = next(
        (
            a.address
            for c in configuration.chains
            if c.chain_id == record.chain_id
            for a in c.assets
            if asset_id(c.chain_id, a.address) == record.asset_id
        ),
        None,
    )
    if token is None:
        raise _fail(409, "TREASURY_NOT_READY", "The treasury asset is not configured.")

    def state(address: str, balance: int) -> WalletState:
        minimum, target = mandate_buffers.get(address.lower(), (0, 0))
        return WalletState(
            address=address.lower(),
            balance=BaseUnits(balance),
            buffer=BaseUnits(minimum),
            target=BaseUnits(target),
        )

    source_state = state(
        source.safe_address, await _balance(request, record.chain_id, token, source.safe_address)
    )
    wallets = {
        w.id: state(w.safe_address, await _balance(request, record.chain_id, token, w.safe_address))
        for w in operational
    }
    today = int(datetime.now(UTC).timestamp()) // 86_400
    snapshot = Snapshot(
        day=today,
        source=source_state,
        # The engine keys wallets by address.
        operational={ws.address: ws for ws in wallets.values()},
        # shortcut: today's already-executed pay/refill usage is not counted, add when persisted.
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={
            str(r.payee_id): int(active.timestamp()) // 86_400
            for r in rows
            if r.payee_id is not None and (active := active_from.get(r.payee_id)) is not None
        },
        safe_usdc=source_state.balance,
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )
    approved: list[ApprovedRequest] = []
    for seq, row in enumerate(rows):
        terms = confirmed_payment_terms(row)
        wallet_id = row.paying_wallet_id or operational[0].id  # unassigned requests pay from O1
        if terms is None or row.amount is None or wallet_id not in wallets:
            continue
        approved.append(
            ApprovedRequest(
                id=str(row.id),
                paying_wallet=wallets[wallet_id].address,
                payee=str(row.payee_id),
                amount=BaseUnits(int(row.amount)),
                approved_seq=seq,
                terms=terms,
            )
        )
    result = forecast(snapshot, approved, policy, _DAYS)

    by_address = {w.safe_address.lower(): w for w in record.wallets}

    def checksum(address: str) -> str:
        return by_address[address].safe_address

    first = operational[0]
    o1 = wallets[first.id]
    refills = [r for d in result.days for r in d.suggested_refills]
    previous = int(o1.balance)
    days: list[ForecastDay] = []
    for day in result.days:
        balance = int(day.balances[o1.address])
        inbound = sum(int(r.amount) for r in day.suggested_refills if r.target_wallet == o1.address)
        days.append(
            ForecastDay(
                date=_iso(day.day),
                balance=str(balance),
                outflow=str(previous + inbound - balance),
                buffer=str(int(o1.buffer)),
            )
        )
        previous = balance
    alerts: list[ForecastAlert] = []
    for wallet in operational:
        hit = result.buffer_hit_days[wallets[wallet.id].address]
        if hit:
            alerts.append(
                ForecastAlert(
                    date=_iso(hit[0]),
                    message=f"{wallet.label} drops below its minimum buffer on this day.",
                )
            )
    return ForecastResponse(
        days=days,
        wallets=[
            ForecastWallet(
                role=f"O{index}",
                label=w.label,
                safe_address=w.safe_address,
                buffer=str(int(wallets[w.id].buffer)),
                days=[
                    ForecastWalletDay(
                        date=_iso(d.day), balance=str(int(d.balances[wallets[w.id].address]))
                    )
                    for d in result.days
                ],
            )
            for index, w in enumerate(operational, start=1)
        ],
        suggested_refills=[
            ForecastRefill(
                date=_iso(r.day),
                source_address=checksum(r.source_wallet),
                target_address=checksum(r.target_wallet),
                amount=str(int(r.amount)),
                request_id=r.request_id,
            )
            for r in refills
        ],
        alerts=alerts,
    )
