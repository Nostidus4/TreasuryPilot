"""Engine-side inputs of one request (requests, wallets, policy). The validator context is built
by ``planner.context``; this module only prepares what the scheduling engine needs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    LiquidityPolicy,
    PaymentTerms,
    PolicyView,
    Schedule,
    WalletState,
)
from treasurypilot_core.domain import Snapshot as EngineSnapshot
from treasurypilot_core.domain.utc_days import utc_day_number
from treasurypilot_core.eip712 import PAY, REFILL, WITHDRAW, step_id
from treasurypilot_core.engine.liquidity import decide_liquidity
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep
from treasurypilot_worker.chain.snapshot import Snapshot as ChainRead

_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"
_TREASURY_SQL = """
SELECT t.org_id, t.chain_id, t.module_address, t.coverage, t.coverage_ack_at IS NOT NULL AS acked,
       a.address AS asset
FROM treasuries t JOIN assets a ON a.id = t.asset_id WHERE t.id = $1
"""
_WALLETS_SQL = "SELECT role, safe_address FROM treasury_wallets WHERE treasury_id = $1 ORDER BY id"
# The target is always loaded; the others are Approved/Scheduled requests with confirmed terms
# that no open plan covers. The latest valid approval of the current revision is the signed truth.
_REQUESTS_SELECT = """
SELECT pr.id, pr.version, pr.terms, pr.created_by, pr.last_edited_by, pr.fiat_amount_minor_units,
       pr.onchain_request_id, pr.invoice_hash, pr.fingerprint, pr.terms_hash,
       pw.safe_address AS paying, pe.address AS payee,
       ap.typed_data, ap.signature, ap.approver_address, ap.approver_user_id,
       ap.acknowledged_flag_ids, ap.solo_mode, ap.created_at AS approved_at, pr.current_revision
FROM payment_requests pr
JOIN treasury_wallets pw ON pw.id = pr.paying_wallet_id
JOIN payees pe ON pe.id = pr.payee_id
JOIN LATERAL (
    SELECT * FROM approvals a
    WHERE a.request_id = pr.id AND a.revision = pr.current_revision AND a.status = 'Valid'
    ORDER BY a.created_at LIMIT 1
) ap ON true
WHERE pr.treasury_id = $1 AND pr.terms IS NOT NULL AND pr.terms_confirmed_by IS NOT NULL
  AND pr.onchain_request_id IS NOT NULL
"""
_ORDER = "ORDER BY ap.created_at, pr.id"
_REQUESTS_SQL = f"""{_REQUESTS_SELECT}
  AND (pr.id = $2 OR (pr.status IN ('Approved', 'Scheduled') AND NOT EXISTS (
      SELECT 1 FROM plans p WHERE p.request_id = pr.id AND p.status IN ({_OPEN}))))
{_ORDER}
"""
# The liquidity reserve (BR-032) counts every approved, unpaid obligation, whatever its plan state.
_RESERVE_SQL = f"{_REQUESTS_SELECT}  AND pr.status IN ('Approved', 'Scheduled')\n{_ORDER}"


class InputsUnavailable(Exception):
    """The request or its snapshot is incomplete, so no plan can be built (fail closed)."""


@dataclass(frozen=True)
class PlanInputs:
    org_id: uuid.UUID
    request_id: uuid.UUID
    request_version: int
    request_hash: bytes
    requests: tuple[ApprovedRequest, ...]
    policy: PolicyView
    snapshot: EngineSnapshot
    today: date


def as_json(value: Any) -> Any:
    """asyncpg hands JSONB back as text unless a codec is installed."""
    return json.loads(value) if isinstance(value, str) else value


def _hex(value: bytes) -> str:
    return "0x" + value.hex()


def plan_steps(
    request_id: bytes,
    *,
    safe_t: str,
    # Scaffolding: production passes None until RefillPathSet wiring lands (#101 follow-up).
    refill_from: str | None = None,
    asset: str,
    wallet: str,
    payee: str,
    refill: int,
    pay: int,
    withdraw: int = 0,
    a_token: str = "",
) -> list[PlanStep]:
    """The WITHDRAW and REFILL (if any) and PAY steps of one request; the single place their ids
    are made. A WITHDRAW (pool -> Safe T) leads a plan whose refill would break the reserve."""

    steps: list[PlanStep] = []
    if withdraw:
        steps.append(
            PlanStep(
                seq=0,
                step_id=step_id(request_id, WITHDRAW, safe_t),
                action=Action.WITHDRAW,
                from_wallet=a_token,
                to=safe_t,
                asset=asset,
                amount=BaseUnits(withdraw),
            )
        )
    if refill:
        steps.append(
            PlanStep(
                seq=len(steps),
                step_id=step_id(request_id, REFILL, wallet),
                action=Action.REFILL,
                from_wallet=refill_from or safe_t,
                to=wallet,
                asset=asset,
                amount=BaseUnits(refill),
            )
        )
    steps.append(
        PlanStep(
            seq=len(steps),
            step_id=step_id(request_id, PAY, wallet),
            action=Action.PAY,
            from_wallet=wallet,
            to=payee,
            asset=asset,
            amount=BaseUnits(pay),
        )
    )
    return steps


async def probe_plan(
    connection: asyncpg.Connection, treasury_id: uuid.UUID, request_id: uuid.UUID
) -> ExecutionPlan:
    """A REFILL + PAY plan carrying the request's ids and addresses, before any snapshot exists.

    It is only used to ask ``planner.context`` for the snapshot scope, the context inputs and the
    fallback context; the plan that is validated and attested is built from the engine's item.
    """

    treasury = await connection.fetchrow(_TREASURY_SQL, treasury_id)
    if treasury is None or treasury["module_address"] is None:
        raise InputsUnavailable("treasury has no module")
    wallets = await connection.fetch(_WALLETS_SQL, treasury_id)
    safe_t = [_hex(w["safe_address"]) for w in wallets if w["role"] == "SOURCE"]
    if len(safe_t) != 1:
        raise InputsUnavailable("treasury needs exactly one source Safe")
    row = await connection.fetchrow(
        """
        SELECT pr.onchain_request_id, pw.safe_address AS paying, pe.address AS payee,
               ap.typed_data
        FROM payment_requests pr
        JOIN treasury_wallets pw ON pw.id = pr.paying_wallet_id
        JOIN payees pe ON pe.id = pr.payee_id
        JOIN approvals ap ON ap.request_id = pr.id AND ap.revision = pr.current_revision
                             AND ap.status = 'Valid'
        WHERE pr.id = $1 AND pr.treasury_id = $2 AND pr.onchain_request_id IS NOT NULL
        ORDER BY ap.created_at LIMIT 1
        """,
        request_id,
        treasury_id,
    )
    if row is None:
        raise InputsUnavailable("request is not plannable")
    amount = int(as_json(row["typed_data"])["message"]["amount"])
    return ExecutionPlan(
        request_id=row["onchain_request_id"],
        treasury=_hex(treasury["module_address"]),
        chain_id=treasury["chain_id"],
        steps=plan_steps(
            row["onchain_request_id"],
            safe_t=safe_t[0],
            asset=_hex(treasury["asset"]),
            wallet=_hex(row["paying"]),
            payee=_hex(row["payee"]),
            refill=amount,
            pay=amount,
        ),
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )


def _exception_granted(raw: dict[str, Any] | None, amount: int, now_ts: int) -> bool:
    """An unused, unexpired Owner exception that covers the amount lets the engine plan it."""
    return bool(
        raw and not raw["used"] and int(raw["expiry"]) > now_ts and int(raw["amount"]) >= amount
    )


def _int(data: dict[str, Any], *path: str) -> int:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise InputsUnavailable(f"snapshot is missing {'/'.join(path)}")
        node = node[key]
    return int(node)


def _limits(raw: dict[str, str]) -> tuple[int, int]:
    return int(raw["per_request"]), int(raw["daily"])


def _wallet(data: dict[str, Any], address: str) -> WalletState:
    buffer = _int(data, "buffers", address)
    target = _int(data, "targets", address)
    return WalletState(
        address=address,
        balance=BaseUnits(_int(data, "balances", address)),
        buffer=BaseUnits(buffer),
        # Safe T has no target of its own; a wallet target below its buffer is not a valid state.
        target=BaseUnits(max(target, buffer)),
    )


def _mandate(data: dict[str, Any]) -> dict[str, Any]:
    mandate = data.get("module", {}).get("mandate")
    if not mandate:
        raise InputsUnavailable("snapshot has no mandate")
    return dict(mandate)


@dataclass(frozen=True)
class LiquidityInputs:
    """Off-chain half of the liquidity reserve: unpaid approved requests and the mandate config."""

    requests: tuple[ApprovedRequest, ...]
    operational: tuple[str, ...]
    config: dict[str, Any]  # the active mandate version's config (minSupply, reserveHorizonDays)


NO_SCHEDULE = Schedule(
    items=(), infeasible=(), objective=(0, 0, 0, 0), binding=(), solver="EDF", status="OPTIMAL"
)


def liquidity_policy(data: dict[str, Any], config: dict[str, Any]) -> LiquidityPolicy:
    """Supply limits from the chain mandate, min supply and horizon from the mandate config.

    shortcut: debt-service reserve and execution holds are 0 until borrowing and holds exist.
    """

    per_request, daily = _limits(_mandate(data)["supply"])
    return LiquidityPolicy(
        supply=Limits(per_request=BaseUnits(per_request), daily=BaseUnits(daily)),
        min_supply=BaseUnits(int(config.get("minSupply", 0))),
        reserve_horizon_days=min(30, max(1, int(config.get("reserveHorizonDays", 30)))),
    )


async def load_liquidity_inputs(
    connection: asyncpg.Connection, treasury_id: uuid.UUID
) -> LiquidityInputs:
    wallets = await connection.fetch(_WALLETS_SQL, treasury_id)
    rows = await connection.fetch(_RESERVE_SQL, treasury_id)
    config = await connection.fetchval(
        "SELECT config FROM mandate_versions WHERE treasury_id = $1 AND status = 'Active' "
        "ORDER BY version DESC LIMIT 1",
        treasury_id,
    )
    return LiquidityInputs(
        # no chain data here: an Owner exception does not change what is owed
        requests=approved_requests(list(rows), {}, 0),
        operational=tuple(_hex(w["safe_address"]) for w in wallets if w["role"] != "SOURCE"),
        config=as_json(config) or {},
    )


def reserve_withdrawal(
    inputs: PlanInputs,
    liquidity: LiquidityInputs,
    data: dict[str, Any],
    refill: int,
    target_id: str,
) -> int:
    """The pool withdrawal that must lead a plan whose REFILL of ``refill`` would break the reserve.

    The reserve is checked on Safe T after the refill, against every obligation except the request
    being paid; 0 when there is no refill, no a-token position, or the reserve holds. A partial
    withdrawal (``INSUFFICIENT_LIQUIDITY``) is still planned: it narrows the gap.
    """

    # the engine's snapshot already carries the aToken and pool figures read at the same block
    if not refill or not (data.get("aave") or {}).get("a_token"):
        return 0
    snapshot = inputs.snapshot
    after = max(0, int(snapshot.safe_usdc) - refill)
    snapshot = snapshot.model_copy(
        update={
            "safe_usdc": BaseUnits(after),
            "source": snapshot.source.model_copy(update={"balance": BaseUnits(after)}),
        }
    )
    decision = decide_liquidity(
        snapshot,
        [r for r in liquidity.requests if r.id != target_id],
        NO_SCHEDULE,
        liquidity_policy(data, liquidity.config),
    )
    if decision.kind in ("WITHDRAW", "INSUFFICIENT_LIQUIDITY"):
        return int(decision.amount)
    return 0


def engine_snapshot(
    data: dict[str, Any], safe_t: str, operational: list[str], *, day: int
) -> EngineSnapshot:
    """The engine's view of a chain snapshot (shared by request and liquidity planning)."""

    aave = data.get("aave") or {}
    debt = int((aave.get("account") or {}).get("total_debt_base", 0))
    reserve = aave.get("reserve") or {}
    used = data["module"]["used_today"]
    return EngineSnapshot(
        day=day,
        source=_wallet(data, safe_t),
        operational={address: _wallet(data, address) for address in operational},
        used_today={
            "pay": BaseUnits(_int(data, "module", "used_today", "PAY")),
            "refill": BaseUnits(_int(data, "module", "used_today", "REFILL")),
            "supply": BaseUnits(int(used.get("SUPPLY", 0))),
        },
        payee_active_day={
            a: int(p["active_from"]) // 86_400
            for a, p in (data.get("payees") or {}).items()
            if int(p["state"]) != 0
        },
        safe_usdc=BaseUnits(_int(data, "balances", safe_t)),
        a_usdc=BaseUnits(int(aave.get("a_token_balance", 0))),
        pool_available=BaseUnits(int(aave.get("available_liquidity", 0))),
        # Aave rates are rays (1e27 = 100 %); basis points are 1e23.
        supply_rate_bps=int(reserve.get("liquidity_rate", 0)) // 10**23,
        borrow_rate_bps=int(reserve.get("variable_borrow_rate", 0)) // 10**23,
        health_factor=(
            int((aave.get("account") or {}).get("health_factor", 0)) if debt > 0 else None
        ),
        debt=BaseUnits(debt),
    )


def approved_requests(
    rows: list[Any], data: dict[str, Any], now_ts: int
) -> tuple[ApprovedRequest, ...]:
    requests: list[ApprovedRequest] = []
    for seq, row in enumerate(rows):
        message = as_json(row["typed_data"])["message"]
        granted = _exception_granted(
            (data.get("requests") or {}).get(_hex(row["onchain_request_id"]), {}).get("exception"),
            int(message["amount"]),
            now_ts,
        )
        requests.append(
            ApprovedRequest(
                id=str(row["id"]),
                paying_wallet=_hex(row["paying"]),
                payee=_hex(row["payee"]),
                amount=BaseUnits(int(message["amount"])),
                approved_seq=seq,
                terms=PaymentTerms.model_validate(as_json(row["terms"])),
                exception_granted=granted,
            )
        )
    return tuple(requests)


async def load_inputs(
    connection: asyncpg.Connection,
    treasury_id: uuid.UUID,
    request_id: uuid.UUID,
    chain: ChainRead,
    *,
    now: datetime,
) -> PlanInputs:
    now = now.astimezone(UTC)
    now_ts = int(now.timestamp())
    treasury = await connection.fetchrow(_TREASURY_SQL, treasury_id)
    if treasury is None or treasury["module_address"] is None:
        raise InputsUnavailable("treasury has no module")
    wallets = await connection.fetch(_WALLETS_SQL, treasury_id)
    safe_t = [_hex(w["safe_address"]) for w in wallets if w["role"] == "SOURCE"]
    if len(safe_t) != 1:
        raise InputsUnavailable("treasury needs exactly one source Safe")
    operational = [_hex(w["safe_address"]) for w in wallets if w["role"] != "SOURCE"]
    rows = await connection.fetch(_REQUESTS_SQL, treasury_id, request_id)
    target = next((r for r in rows if r["id"] == request_id), None)
    if target is None:
        raise InputsUnavailable("request has no valid approval or confirmed terms")

    data = chain.data
    mandate = _mandate(data)
    pay_limits, refill_limits = _limits(mandate["pay"]), _limits(mandate["refill"])
    policy = PolicyView(
        pay=Limits(per_request=BaseUnits(pay_limits[0]), daily=BaseUnits(pay_limits[1])),
        refill=Limits(per_request=BaseUnits(refill_limits[0]), daily=BaseUnits(refill_limits[1])),
        cooling_seconds=int(mandate["payee_cooling_seconds"]),
    )

    engine = engine_snapshot(data, safe_t[0], operational, day=utc_day_number(now))

    return PlanInputs(
        org_id=treasury["org_id"],
        request_id=request_id,
        request_version=int(target["version"]),
        request_hash=target["onchain_request_id"],
        requests=approved_requests(rows, data, now_ts),
        policy=policy,
        snapshot=engine,
        today=now.date(),
    )
