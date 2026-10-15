"""Dashboard read model of one treasury (TRS-009, API_SPEC section 2).

``GET /orgs/{o}/treasuries/{t}`` adds, on top of the stored treasury and its Safes, everything the
dashboard renders: the current mandate, the daily budgets, per-wallet balances, the liquidity
position, the signed-in member's queues and recent activity.

Chain figures (balances, buffers, targets, used-today counters, the Aave position) come from the
latest ``snapshots`` row that the worker's chain reader stored (M06 CHR-002), so every number is
from one block and travels with its ``staleness``. Without any snapshot none of them is returned:
a field is left out instead of being shown as zero. The reserve uses the same ``liquidity_position``
formula as the liquidity cycle (ENG-013).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus
from treasurypilot_api.invoices.requests import confirmed_payment_terms
from treasurypilot_api.mandate.models import MandateVersion, MandateVersionStatus
from treasurypilot_api.treasury.models import WalletRole
from treasurypilot_api.treasury.service import TreasuryRecord
from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    LiquidityPolicy,
    Schedule,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine.liquidity import liquidity_position
from treasurypilot_core.money import BaseUnits, format_base_units

# The worker stores a DASHBOARD snapshot every 60 s. Three missed cycles make the numbers stale.
STALE_AFTER: Final = timedelta(seconds=180)
ACTIVITY_LIMIT: Final = 10
_RAY_PER_BPS: Final = 10**23  # Aave rates are rays (1e27 = 100 %)
_SECONDS_PER_DAY: Final = 86_400
_SUPPLY, _WITHDRAW = 4, 5  # plan_steps.action (eip712)
_R = OrganizationRole
_APPROVAL_ROLES = frozenset({_R.APPROVER.value, _R.OWNER.value})
_RECONCILIATION_ROLES = frozenset({_R.FINANCE.value, _R.OWNER.value, _R.ORG_ADMIN.value})
_NO_SCHEDULE: Final = Schedule(
    items=(), infeasible=(), objective=(0, 0, 0, 0), binding=(), solver="EDF", status="OPTIMAL"
)

_LATEST_SNAPSHOT = text(
    "SELECT block_number, observed_at, data FROM snapshots WHERE treasury_id = :t AND org_id = :o "
    "ORDER BY block_number DESC, observed_at DESC LIMIT 1"
)
# A liquidity plan serves no request (request_id NULL); its SUPPLY / WITHDRAW step is the action.
_LAST_ACTION = text(
    """
    SELECT s.action, s.amount, p.chosen_reason,
           (SELECT '0x' || encode(t.tx_hash, 'hex') FROM operations o
              JOIN transactions t ON t.operation_id = o.id AND t.confirmed_at IS NOT NULL
             WHERE o.plan_step_id = s.id ORDER BY t.confirmed_at DESC LIMIT 1) AS tx_hash,
           COALESCE((SELECT max(t.confirmed_at) FROM operations o
                       JOIN transactions t ON t.operation_id = o.id
                      WHERE o.plan_step_id = s.id), p.updated_at) AS at
    FROM plans p JOIN plan_steps s ON s.plan_id = p.id
    WHERE p.treasury_id = :t AND p.org_id = :o AND p.request_id IS NULL
      AND p.status IN ('Completed', 'PartiallyCompleted') AND s.action IN (4, 5)
    ORDER BY p.updated_at DESC, s.seq DESC LIMIT 1
    """
)
_REVIEW_COUNT = text(
    "SELECT count(*) FROM review_items WHERE org_id = :o AND treasury_id = :t "
    "AND status = 'Open' AND assigned_roles && CAST(:roles AS varchar[])"
)
_GOVERNANCE_COUNT = text(
    "SELECT count(*) FROM governance_txs WHERE org_id = :o AND treasury_id = :t "
    "AND status IN ('Collecting', 'Ready')"
)
_RECONCILIATION_COUNT = text(
    "SELECT count(*) FROM reconciliations WHERE org_id = :o AND treasury_id = :t "
    "AND status IN ('Pending', 'Discrepancy')"
)
_STATUS_ACTIVITY = text(
    """
    SELECT e.id, e.at, e.actor_type, e."from" AS from_status, e."to" AS to_status, e.reason,
           r.id AS request_id, r.invoice_no
    FROM request_status_events e JOIN payment_requests r ON r.id = e.request_id
    WHERE r.org_id = :o AND r.treasury_id = :t ORDER BY e.at DESC LIMIT :n
    """
)
_CHAIN_ACTIVITY = text(
    """
    SELECT id, created_at, direction, amount, "class" AS kind FROM token_movements
    WHERE treasury_id = :t AND NOT removed AND "class" IN ('INFLOW', 'UNEXPECTED_OUTFLOW')
    ORDER BY created_at DESC LIMIT :n
    """
)


class MandateSummaryView(ApiModel):
    version: int
    status: MandateVersionStatus
    expires_at: datetime


class BudgetView(ApiModel):
    action: Literal["PAY", "REFILL"]
    used_today: str
    daily_limit: str
    per_request: str


class StalenessView(ApiModel):
    block_number: int
    observed_at: datetime
    stale: bool


class RequiredReserveView(ApiModel):
    payment_reserve: str
    floor: str
    holds: str
    total: str


class LastActionView(ApiModel):
    kind: Literal["SUPPLY", "WITHDRAW", "NONE"]
    amount: str
    at: datetime | None
    explanation: str
    tx_hash: str | None = None


class PositionView(ApiModel):
    safe_usdc: str
    a_usdc: str
    pool_liquidity: str
    required_reserve: RequiredReserveView
    available_for_supply: str
    supply_apy_bps: int
    last_action: LastActionView


class QueuesView(ApiModel):
    approvals: int
    governance: int
    review: int
    reconciliation: int


class ActivityView(ApiModel):
    id: str
    at: datetime
    actor: Literal["agent", "user", "chain"]
    text: str
    href: str | None = None


@dataclass(frozen=True, slots=True)
class WalletFigures:
    balance: str
    buffer: str
    target: str


@dataclass(frozen=True, slots=True)
class ChainRead:
    block_number: int
    observed_at: datetime
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TreasuryExtras:
    """Only the parts that could be built; a missing part stays unset and is not serialized."""

    staleness: StalenessView | None
    wallets: dict[str, WalletFigures]
    mandate: MandateSummaryView | None
    budgets: list[BudgetView] | None
    position: PositionView | None
    queues: QueuesView
    activity: list[ActivityView]


def _node(data: Mapping[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _amount(data: Mapping[str, Any], *path: str) -> int | None:
    value = _node(data, *path)
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def staleness_of(read: ChainRead, now: datetime) -> StalenessView:
    return StalenessView(
        block_number=read.block_number,
        observed_at=read.observed_at,
        stale=now - read.observed_at > STALE_AFTER,
    )


def wallet_figures(read: ChainRead, addresses: Iterable[str]) -> dict[str, WalletFigures]:
    """Balance, buffer and target per Safe address (lowercase); Safes with a missing read are left
    out. Safe T has no target of its own, and a target below the buffer is not a valid state, so
    the target never falls below the buffer (as in the planner)."""

    figures: dict[str, WalletFigures] = {}
    for address in addresses:
        key = address.lower()
        balance = _amount(read.data, "balances", key)
        buffer = _amount(read.data, "buffers", key)
        target = _amount(read.data, "targets", key)
        if balance is None or buffer is None or target is None:
            continue
        figures[key] = WalletFigures(str(balance), str(buffer), str(max(target, buffer)))
    return figures


def budgets_of(read: ChainRead) -> list[BudgetView]:
    """PAY and REFILL budget of the current UTC day: the on-chain counters against the on-chain
    mandate limits. No mandate on chain, no budgets."""

    mandate = _node(read.data, "module", "mandate")
    if not isinstance(mandate, Mapping):
        return []
    budgets: list[BudgetView] = []
    for action, key in (("PAY", "pay"), ("REFILL", "refill")):
        per_request = _amount(mandate, key, "per_request")
        daily = _amount(mandate, key, "daily")
        used = _amount(read.data, "module", "used_today", action)
        if per_request is None or daily is None or used is None:
            continue
        budgets.append(
            BudgetView(
                action=action,  # type: ignore[arg-type]
                used_today=str(used),
                daily_limit=str(daily),
                per_request=str(per_request),
            )
        )
    return budgets


def position_of(
    read: ChainRead,
    *,
    safe_t: str,
    requests: tuple[ApprovedRequest, ...],
    mandate_config: Mapping[str, Any],
    last_action: LastActionView,
    now: datetime,
) -> PositionView | None:
    """The liquidity position at the snapshot's block, with the liquidity cycle's formula."""

    figures = wallet_figures(read, [safe_t]).get(safe_t.lower())
    if figures is None:
        return None
    aave = _node(read.data, "aave")
    aave = aave if isinstance(aave, Mapping) else {}
    safe_usdc = BaseUnits(int(figures.balance))
    wallet = WalletState(
        address=safe_t.lower(),
        balance=safe_usdc,
        buffer=BaseUnits(int(figures.buffer)),
        target=BaseUnits(int(figures.target)),
    )
    supply = _node(read.data, "module", "mandate", "supply")
    supply = supply if isinstance(supply, Mapping) else {}
    a_usdc = BaseUnits(_amount(aave, "a_token_balance") or 0)
    pool = BaseUnits(_amount(aave, "available_liquidity") or 0)
    rate = _amount(aave, "reserve", "liquidity_rate") or 0
    snapshot = Snapshot(
        day=int(now.timestamp()) // _SECONDS_PER_DAY,
        source=wallet,
        operational={},
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={},
        safe_usdc=safe_usdc,
        a_usdc=a_usdc,
        pool_available=pool,
        supply_rate_bps=rate // _RAY_PER_BPS,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )
    # shortcut: debt service and execution holds are 0 until borrowing and holds exist (as in the
    # liquidity cycle, planner.inputs.liquidity_policy).
    policy = LiquidityPolicy(
        supply=Limits(
            per_request=BaseUnits(_amount(supply, "per_request") or 0),
            daily=BaseUnits(_amount(supply, "daily") or 0),
        ),
        min_supply=BaseUnits(int(mandate_config.get("minSupply", 0))),
        reserve_horizon_days=min(30, max(1, int(mandate_config.get("reserveHorizonDays", 30)))),
    )
    result = liquidity_position(snapshot, requests, _NO_SCHEDULE, policy)
    return PositionView(
        safe_usdc=str(int(safe_usdc)),
        a_usdc=str(int(a_usdc)),
        pool_liquidity=str(int(pool)),
        required_reserve=RequiredReserveView(
            payment_reserve=str(int(result.payment_reserve)),
            floor=str(int(result.safe_floor)),
            holds=str(int(result.debt_service_reserve) + int(result.execution_holds)),
            total=str(int(result.required_safe_reserve)),
        ),
        available_for_supply=str(int(result.available_for_supply)),
        supply_apy_bps=snapshot.supply_rate_bps,
        last_action=last_action,
    )


def queue_roles(roles: Iterable[str]) -> tuple[bool, bool]:
    """(sees approvals, sees reconciliations); the same roles as the inbox endpoints."""

    held = set(roles)
    return bool(held & _APPROVAL_ROLES), bool(held & _RECONCILIATION_ROLES)


async def _snapshot(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID
) -> ChainRead | None:
    row = (await session.execute(_LATEST_SNAPSHOT, {"t": treasury_id, "o": org_id})).first()
    if row is None:
        return None
    data = row.data if isinstance(row.data, dict) else {}
    return ChainRead(int(row.block_number), row.observed_at, data)


async def _mandate(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID
) -> MandateVersion | None:
    """The current version: the Active one, else the latest that is not a draft."""

    return await session.scalar(
        select(MandateVersion)
        .where(
            MandateVersion.org_id == org_id,
            MandateVersion.treasury_id == treasury_id,
            MandateVersion.status != MandateVersionStatus.DRAFT,
        )
        .order_by(
            (MandateVersion.status == MandateVersionStatus.ACTIVE).desc(),
            MandateVersion.version.desc(),
        )
        .limit(1)
    )


async def _reserve_requests(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID
) -> tuple[ApprovedRequest, ...]:
    """Approved, unpaid obligations the liquidity reserve counts (planner.inputs, _RESERVE_SQL)."""

    rows = await session.scalars(
        select(PaymentRequest)
        .where(
            PaymentRequest.org_id == org_id,
            PaymentRequest.treasury_id == treasury_id,
            PaymentRequest.status.in_([RequestStatus.APPROVED, RequestStatus.SCHEDULED]),
            PaymentRequest.amount.is_not(None),
            PaymentRequest.payee_id.is_not(None),
            PaymentRequest.paying_wallet_id.is_not(None),
            PaymentRequest.onchain_request_id.is_not(None),
        )
        .order_by(PaymentRequest.created_at, PaymentRequest.id)
    )
    requests: list[ApprovedRequest] = []
    for seq, row in enumerate(rows):
        try:
            terms = confirmed_payment_terms(row)
        except ValidationError:
            continue
        if (
            terms is None
            or row.amount is None
            or row.payee_id is None
            or row.paying_wallet_id is None
        ):
            continue
        requests.append(
            ApprovedRequest(
                id=str(row.id),
                paying_wallet=str(row.paying_wallet_id),
                payee=str(row.payee_id),
                amount=BaseUnits(int(row.amount)),
                approved_seq=seq,
                terms=terms,
            )
        )
    return tuple(requests)


async def _last_action(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID
) -> LastActionView:
    row = (await session.execute(_LAST_ACTION, {"t": treasury_id, "o": org_id})).first()
    if row is None:
        return LastActionView(
            kind="NONE", amount="0", at=None, explanation="No supply or withdrawal yet."
        )
    return LastActionView(
        kind="SUPPLY" if row.action == _SUPPLY else "WITHDRAW",
        amount=str(int(row.amount)),
        at=row.at,
        explanation=row.chosen_reason or "",
        tx_hash=row.tx_hash,
    )


async def _queues(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID, roles: frozenset[str]
) -> QueuesView:
    params = {"o": org_id, "t": treasury_id}
    approvals_visible, reconciliation_visible = queue_roles(roles)
    approvals = 0
    if approvals_visible:
        approvals = int(
            await session.scalar(
                select(func.count())
                .select_from(PaymentRequest)
                .where(
                    PaymentRequest.org_id == org_id,
                    PaymentRequest.treasury_id == treasury_id,
                    PaymentRequest.status == RequestStatus.AWAITING_APPROVAL,
                )
            )
            or 0
        )
    governance = int(await session.scalar(_GOVERNANCE_COUNT, params) or 0)
    review = int(await session.scalar(_REVIEW_COUNT, {**params, "roles": sorted(roles)}) or 0)
    reconciliation = 0
    if reconciliation_visible:
        reconciliation = int(await session.scalar(_RECONCILIATION_COUNT, params) or 0)
    return QueuesView(
        approvals=approvals, governance=governance, review=review, reconciliation=reconciliation
    )


async def _activity(
    session: AsyncSession, org_id: uuid.UUID, treasury_id: uuid.UUID, *, symbol: str, decimals: int
) -> list[ActivityView]:
    params = {"o": org_id, "t": treasury_id, "n": ACTIVITY_LIMIT}
    items: list[ActivityView] = []
    for row in (await session.execute(_STATUS_ACTIVITY, params)).all():
        label = row.invoice_no or "A request"
        text_ = (
            f"{label} moved from {row.from_status} to {row.to_status}"
            if row.from_status
            else f"{label} was created as {row.to_status}"
        )
        if row.reason:
            text_ = f"{text_}: {row.reason}"
        items.append(
            ActivityView(
                id=f"status:{row.id}",
                at=row.at,
                actor="user" if row.actor_type == "USER" else "agent",
                text=text_,
                href=f"requests/{row.request_id}",
            )
        )
    for row in (await session.execute(_CHAIN_ACTIVITY, params)).all():
        amount = format_base_units(BaseUnits(int(row.amount)), decimals)
        moved = (
            f"Received {amount} {symbol}"
            if row.direction == "IN"
            else f"Unexpected outflow of {amount} {symbol}"
        )
        items.append(
            ActivityView(id=f"chain:{row.id}", at=row.created_at, actor="chain", text=moved)
        )
    items.sort(key=lambda item: item.at, reverse=True)
    return items[:ACTIVITY_LIMIT]


async def load_extras(
    session: AsyncSession,
    record: TreasuryRecord,
    *,
    roles: frozenset[str],
    symbol: str,
    decimals: int,
    now: datetime | None = None,
) -> TreasuryExtras:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    org_id, treasury_id = record.org_id, record.id
    read = await _snapshot(session, org_id, treasury_id)
    version = await _mandate(session, org_id, treasury_id)
    mandate = (
        MandateSummaryView(
            version=version.version, status=version.status, expires_at=version.expires_at
        )
        if version is not None
        else None
    )
    source = next((w for w in record.wallets if w.role == WalletRole.SOURCE), None)
    wallets: dict[str, WalletFigures] = {}
    position: PositionView | None = None
    if read is not None:
        wallets = wallet_figures(read, (w.safe_address for w in record.wallets))
        if source is not None:
            active = await session.scalar(
                select(MandateVersion.config).where(
                    MandateVersion.org_id == org_id,
                    MandateVersion.treasury_id == treasury_id,
                    MandateVersion.status == MandateVersionStatus.ACTIVE,
                )
            )
            position = position_of(
                read,
                safe_t=source.safe_address,
                requests=await _reserve_requests(session, org_id, treasury_id),
                mandate_config=active or {},
                last_action=await _last_action(session, org_id, treasury_id),
                now=current,
            )
    return TreasuryExtras(
        staleness=staleness_of(read, current) if read is not None else None,
        wallets=wallets,
        mandate=mandate,
        budgets=budgets_of(read) if read is not None else None,
        position=position,
        queues=await _queues(session, org_id, treasury_id, roles),
        activity=await _activity(session, org_id, treasury_id, symbol=symbol, decimals=decimals),
    )
