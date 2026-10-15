"""Load the engine and validator inputs of one request from PostgreSQL and a chain snapshot."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    WalletState,
)
from treasurypilot_core.domain import Snapshot as EngineSnapshot
from treasurypilot_core.domain.utc_days import utc_day_number
from treasurypilot_core.eip712 import PAY, REFILL, step_id
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    ApprovalView,
    ChainSnapshot,
    ExceptionView,
    FlagView,
    MandateView,
    PayeeView,
    PolicyState,
    RequestView,
    ValidationContext,
)
from treasurypilot_core.policy import Limits as PolicyLimits
from treasurypilot_worker.chain.snapshot import Snapshot as ChainRead
from treasurypilot_worker.chain.snapshot import SnapshotScope

_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"
_TREASURY_SQL = """
SELECT t.org_id, t.chain_id, t.module_address, t.coverage, t.coverage_ack_at IS NOT NULL AS acked,
       a.address AS asset
FROM treasuries t JOIN assets a ON a.id = t.asset_id WHERE t.id = $1
"""
_WALLETS_SQL = "SELECT role, safe_address FROM treasury_wallets WHERE treasury_id = $1 ORDER BY id"
# The target is always loaded; the others are Approved/Scheduled requests with confirmed terms
# that no open plan covers. The latest valid approval of the current revision is the signed truth.
_REQUESTS_SQL = f"""
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
  AND (pr.id = $2 OR (pr.status IN ('Approved', 'Scheduled') AND NOT EXISTS (
      SELECT 1 FROM plans p WHERE p.request_id = pr.id AND p.status IN ({_OPEN}))))
ORDER BY ap.created_at, pr.id
"""


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
    ctx: ValidationContext
    today: date


def as_json(value: Any) -> Any:
    """asyncpg hands JSONB back as text unless a codec is installed."""
    return json.loads(value) if isinstance(value, str) else value


def _hex(value: bytes) -> str:
    return "0x" + value.hex()


def step_ids(request_hash: bytes, wallet: str) -> tuple[str, ...]:
    """Both step ids of a request's plan, as snapshot scope keys (they depend on nothing else)."""

    return tuple(_hex(step_id(request_hash, action, wallet)) for action in (REFILL, PAY))


async def scope_for(
    connection: asyncpg.Connection, treasury_id: uuid.UUID, request_id: uuid.UUID
) -> SnapshotScope:
    row = await connection.fetchrow(
        """
        SELECT pr.onchain_request_id, pr.fingerprint, pw.safe_address AS paying,
               pe.address AS payee, ap.approver_address
        FROM payment_requests pr
        JOIN treasury_wallets pw ON pw.id = pr.paying_wallet_id
        JOIN payees pe ON pe.id = pr.payee_id
        LEFT JOIN approvals ap ON ap.request_id = pr.id AND ap.revision = pr.current_revision
                                  AND ap.status = 'Valid'
        WHERE pr.id = $1 AND pr.treasury_id = $2 AND pr.onchain_request_id IS NOT NULL
        """,
        request_id,
        treasury_id,
    )
    if row is None:
        raise InputsUnavailable("request is not plannable")
    return SnapshotScope(
        approvers=(_hex(row["approver_address"]),) if row["approver_address"] else (),
        payees=(_hex(row["payee"]),),
        request_ids=(_hex(row["onchain_request_id"]),),
        step_ids=step_ids(row["onchain_request_id"], _hex(row["paying"])),
        fingerprints=(_hex(row["fingerprint"]),) if row["fingerprint"] else (),
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


async def load_inputs(
    connection: asyncpg.Connection,
    treasury_id: uuid.UUID,
    request_id: uuid.UUID,
    chain: ChainRead,
    *,
    executor: str,
    now: datetime,
    head_block: int,
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
    module = _hex(treasury["module_address"])
    asset = _hex(treasury["asset"])
    pay_limits, refill_limits = _limits(mandate["pay"]), _limits(mandate["refill"])
    supply_limits = _limits(mandate["supply"])
    policy = PolicyView(
        pay=Limits(per_request=BaseUnits(pay_limits[0]), daily=BaseUnits(pay_limits[1])),
        refill=Limits(per_request=BaseUnits(refill_limits[0]), daily=BaseUnits(refill_limits[1])),
        cooling_seconds=int(mandate["payee_cooling_seconds"]),
    )

    payees = {
        address: PayeeView(active=int(p["state"]) == 2, active_from=int(p["active_from"]))
        for address, p in (data.get("payees") or {}).items()
        if int(p["state"]) != 0
    }
    aave = data.get("aave") or {}
    debt = int((aave.get("account") or {}).get("total_debt_base", 0))
    reserve = aave.get("reserve") or {}
    engine = EngineSnapshot(
        day=utc_day_number(now),
        source=_wallet(data, safe_t[0]),
        operational={address: _wallet(data, address) for address in operational},
        used_today={
            "pay": BaseUnits(_int(data, "module", "used_today", "PAY")),
            "refill": BaseUnits(_int(data, "module", "used_today", "REFILL")),
        },
        payee_active_day={a: p.active_from // 86_400 for a, p in payees.items()},
        safe_usdc=BaseUnits(_int(data, "balances", safe_t[0])),
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

    rid = _hex(target["onchain_request_id"])
    msg = as_json(target["typed_data"])["message"]
    request_view = RequestView(
        request_id=target["onchain_request_id"],
        status="Approved",
        invoice_hash=target["invoice_hash"],
        fingerprint=target["fingerprint"],
        terms_hash=target["terms_hash"],
        paying_wallet=_hex(target["paying"]),
        payee=_hex(target["payee"]),
        amount=BaseUnits(int(msg["amount"])),
        fiat_amount_minor_units=(
            None
            if target["fiat_amount_minor_units"] is None
            else int(target["fiat_amount_minor_units"])
        ),
        early_amount=BaseUnits(int(msg["earlyAmount"])),
        early_pay_by=int(msg["earlyPayBy"]),
        deadline=int(msg["deadline"]),
    )
    paying = request_view.paying_wallet
    req_data = (data.get("requests") or {}).get(rid, {})
    raw_exception = req_data.get("exception")
    exception = (
        ExceptionView(
            amount=BaseUnits(int(raw_exception["amount"])),
            payee=raw_exception["payee"],
            expiry=int(raw_exception["expiry"]),
            mandate_version=int(raw_exception["mandate_version"]),
            used=bool(raw_exception["used"]),
        )
        if raw_exception and int(raw_exception["expiry"]) > 0
        else None
    )
    fingerprint = _hex(target["fingerprint"])
    fp_data = (data.get("fingerprints") or {}).get(fingerprint, {})
    wallets_all = [safe_t[0], *operational]
    ids = step_ids(target["onchain_request_id"], paying)
    state = PolicyState(
        pay_limits=PolicyLimits(per_request=pay_limits[0], daily=pay_limits[1]),
        refill_limits=PolicyLimits(per_request=refill_limits[0], daily=refill_limits[1]),
        supply_limits=PolicyLimits(per_request=supply_limits[0], daily=supply_limits[1]),
        balances={w: BaseUnits(_int(data, "balances", w)) for w in wallets_all},
        buffers={w: BaseUnits(_int(data, "buffers", w)) for w in wallets_all},
        targets={w: BaseUnits(_int(data, "targets", w)) for w in wallets_all},
        used_today={
            "PAY": BaseUnits(_int(data, "module", "used_today", "PAY")),
            "REFILL": BaseUnits(_int(data, "module", "used_today", "REFILL")),
            "SUPPLY": BaseUnits(0),
        },
        request_paid=bool(req_data.get("paid")),
        step_used=[
            bytes.fromhex(s.removeprefix("0x"))
            for s in ids
            if (data.get("steps") or {}).get(s, {}).get("used")
        ],
        fingerprint_paid=bool(fp_data.get("paid")),
        duplicate_allowed=str(fp_data.get("allowed_for", "")).lower() == rid,
        refilled_for_request=bool((req_data.get("refilled") or {}).get(paying)),
        exception=exception,
    )
    mandate_view = MandateView(
        status=("Active", "Paused", "Revoked")[_int(data, "module", "status")],
        version=int(mandate["version"]),
        valid_from=int(mandate["valid_from"]),
        expires_at=int(mandate["expires_at"]),
        executor=mandate["executor"],
    )
    approvals = (data.get("module") or {}).get("approvers") or {}
    chain_view = ChainSnapshot(
        chain_id=int(treasury["chain_id"]),
        treasury=module,
        block_number=chain.block_number,
        read_at=now_ts,
        safe_t=safe_t[0],
        asset=asset,
        mandate=mandate_view,
        approvers=[a for a, ok in approvals.items() if ok],
        payees=payees,
        request_cancelled=bool(req_data.get("cancelled")),
    )
    flags = await connection.fetch(
        "SELECT id, code, severity, created_at FROM flags WHERE request_id = $1 "
        "AND revision = $2 AND status IN ('Open', 'Acknowledged')",
        request_id,
        target["current_revision"],
    )
    screening = await connection.fetchrow(
        "SELECT result, ttl_until FROM screenings WHERE org_id = $1 AND address = $2 "
        "AND chain_id = $3 ORDER BY checked_at DESC LIMIT 1",
        treasury["org_id"],
        target["payee"],
        treasury["chain_id"],
    )
    unknown = await connection.fetchval(
        "SELECT count(*) FROM operations WHERE treasury_id = $1 AND status = 'Unknown'",
        treasury_id,
    )
    coverage: Literal["COMPLETE", "PARTIAL_ACK", "PARTIAL", "NONE"] = (
        "COMPLETE"
        if treasury["coverage"] == "COMPLETE"
        else ("PARTIAL_ACK" if treasury["coverage"] == "PARTIAL" and treasury["acked"] else "NONE")
    )
    approval = ApprovalView(
        typed=msg,
        signature=bytes(target["signature"]),
        signer=_hex(target["approver_address"]),
        approved_at=target["approved_at"],
        created_by=target["created_by"] or uuid.UUID(int=0),
        last_edited_by=target["last_edited_by"] or target["created_by"] or uuid.UUID(int=0),
        approved_by_user=target["approver_user_id"] or uuid.UUID(int=0),
        acknowledged_flag_ids=list(target["acknowledged_flag_ids"]),
        solo_mode=bool(target["solo_mode"]),
    )
    ctx = ValidationContext(
        now=now_ts,
        head_block=head_block,
        executor=executor,
        snapshot=chain_view,
        request=request_view,
        approval=approval,
        flags=[
            FlagView(id=f["id"], code=f["code"], severity=f["severity"], raised_at=f["created_at"])
            for f in flags
        ],
        coverage=coverage,
        unknown_operations=int(unknown),
        pause_requested=False,  # the cycle gates already refused a paused treasury
        circuit_open=False,
        screening_hit=bool(screening and screening["result"] == "HIT"),
        screening_clear=bool(
            screening
            and screening["result"] == "CLEAR"
            and (screening["ttl_until"] is None or screening["ttl_until"] > now)
        ),
        policy_state=state,
    )
    return PlanInputs(
        org_id=treasury["org_id"],
        request_id=request_id,
        request_version=int(target["version"]),
        request_hash=target["onchain_request_id"],
        requests=tuple(requests),
        policy=policy,
        snapshot=engine,
        ctx=ctx,
        today=now.date(),
    )
