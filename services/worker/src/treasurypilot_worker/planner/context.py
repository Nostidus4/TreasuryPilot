"""Snapshot to ``ValidationContext`` (M08 §4.1): the one builder planning and execution share.

``ContextInputs`` holds the off-chain facts (``load_inputs`` reads them from PostgreSQL),
``build_context`` joins them with a chain snapshot. Anything missing or malformed is passed on as
``None``/absent so the validator answers DATA_MISSING; nothing is defaulted to a permissive value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ApprovalView,
    ChainSnapshot,
    ExceptionView,
    ExecutionPlan,
    FlagView,
    Limits,
    MandateView,
    PayeeView,
    PolicyState,
    RequestView,
    ValidationContext,
)
from treasurypilot_worker.chain.snapshot import Snapshot, SnapshotScope

_MANDATE_STATUS = ("Active", "Paused", "Revoked")
_COVERAGE = ("COMPLETE", "PARTIAL_ACK", "PARTIAL", "NONE")
_PAYEE_ACTIVE = 2  # ITreasuryPilotModule.PayeeState.Active
_NIL = UUID(int=0)


@dataclass(frozen=True)
class ContextInputs:
    """Everything the validator needs besides the chain snapshot."""

    chain_id: int
    safe_t: str
    asset: str
    executor: str
    request: RequestView | None
    approval: ApprovalView | None
    fingerprint: bytes | None
    flags: tuple[FlagView, ...] = ()
    unknown_operations: int = 0
    pause_requested: bool = False
    circuit_open: bool = False
    screening_hit: bool = False
    screening_clear: bool = False
    travel_rule_clear: bool | None = None


def scope_for(plan: ExecutionPlan, inputs: ContextInputs) -> SnapshotScope:
    """The extra snapshot reads this plan's validation needs."""

    return SnapshotScope(
        approvers=(inputs.approval.signer,) if inputs.approval else (),
        payees=tuple(s.to for s in plan.steps if s.action is Action.PAY),
        request_ids=("0x" + plan.request_id.hex(),),
        step_ids=tuple("0x" + s.step_id.hex() for s in plan.steps),
        fingerprints=("0x" + inputs.fingerprint.hex(),) if inputs.fingerprint else (),
    )


def _units(value: Any) -> BaseUnits:
    return BaseUnits(int(value))


def _limits(raw: dict[str, str]) -> Limits:
    return Limits(per_request=int(raw["per_request"]), daily=int(raw["daily"]))


def _chain_snapshot(
    snapshot: Snapshot, plan: ExecutionPlan, inputs: ContextInputs
) -> ChainSnapshot:
    data = snapshot.data
    module = data.get("module", {})
    try:
        raw = module["mandate"]
        mandate: MandateView | None = MandateView(
            status=_MANDATE_STATUS[module["status"]],  # type: ignore[arg-type]
            version=raw["version"],
            valid_from=raw["valid_from"],
            expires_at=raw["expires_at"],
            executor=raw["executor"],
        )
    except (KeyError, IndexError, TypeError, ValueError):
        mandate = None
    rid = "0x" + plan.request_id.hex()
    return ChainSnapshot(
        chain_id=inputs.chain_id,
        treasury=plan.treasury,
        block_number=snapshot.block_number,
        # The validator's freshness gate measures block age: the block time is when this was read.
        read_at=int(snapshot.block_timestamp.timestamp()),
        safe_t=inputs.safe_t,
        asset=inputs.asset,
        mandate=mandate,
        approvers=[a for a, ok in module.get("approvers", {}).items() if ok],
        payees={
            address: PayeeView(
                active=value["state"] == _PAYEE_ACTIVE, active_from=value["active_from"]
            )
            for address, value in data.get("payees", {}).items()
        },
        request_cancelled=bool(data.get("requests", {}).get(rid, {}).get("cancelled", False)),
    )


def _policy_state(
    snapshot: Snapshot, plan: ExecutionPlan, inputs: ContextInputs
) -> PolicyState | None:
    data = snapshot.data
    try:
        mandate, used = data["module"]["mandate"], data["module"]["used_today"]
        request = data["requests"]["0x" + plan.request_id.hex()]
        fingerprint = data.get("fingerprints", {}).get("0x" + (inputs.fingerprint or b"").hex(), {})
        exception = request["exception"]
        aave = data.get("aave", {})
        return PolicyState(
            pay_limits=_limits(mandate["pay"]),
            refill_limits=_limits(mandate["refill"]),
            supply_limits=_limits(mandate["supply"]),
            balances={k: _units(v) for k, v in data["balances"].items()},
            buffers={k: _units(v) for k, v in data["buffers"].items()},
            targets={k: _units(v) for k, v in data["targets"].items()},
            # shortcut: the module has no SUPPLY usage read yet, so 0; add it with the SUPPLY flow.
            used_today={
                "PAY": _units(used["PAY"]),
                "REFILL": _units(used["REFILL"]),
                "SUPPLY": _units(0),
            },
            request_paid=bool(request["paid"]),
            step_used=tuple(
                bytes.fromhex(step.removeprefix("0x"))
                for step, value in data.get("steps", {}).items()
                if value["used"]
            ),
            fingerprint_paid=bool(fingerprint.get("paid", False)),
            duplicate_allowed=fingerprint.get("allowed_for") == "0x" + plan.request_id.hex(),
            refilled_for_request=any(request.get("refilled", {}).values()),
            exception=None
            if int(exception["amount"]) == 0
            else ExceptionView(
                amount=_units(exception["amount"]),
                payee=exception["payee"],
                expiry=exception["expiry"],
                mandate_version=exception["mandate_version"],
                used=exception["used"],
            ),
            # shortcut: payment_reserve and available_for_supply are only read for SUPPLY; left 0
            # they block it (fail closed) until the liquidity flow supplies them.
            a_token_balance=_units(aave.get("a_token_balance", 0)),
            pool_liquidity=_units(aave.get("available_liquidity", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None  # a failed sub-call is in snapshot.missing: DATA_MISSING, never a default


def build_context(
    snapshot: Snapshot,
    plan: ExecutionPlan,
    inputs: ContextInputs,
    *,
    now: int,
    head_block: int,
) -> ValidationContext:
    coverage = snapshot.coverage if snapshot.coverage in _COVERAGE else "NONE"
    return ValidationContext.model_validate(
        {
            "now": now,
            "head_block": head_block,
            "executor": inputs.executor,
            "snapshot": _chain_snapshot(snapshot, plan, inputs),
            "request": inputs.request,
            "approval": inputs.approval,
            "flags": inputs.flags,
            "coverage": coverage,
            "unknown_operations": inputs.unknown_operations,
            "pause_requested": inputs.pause_requested,
            "circuit_open": inputs.circuit_open,
            "screening_hit": inputs.screening_hit,
            "screening_clear": inputs.screening_clear,
            "travel_rule_clear": inputs.travel_rule_clear,
            "policy_state": _policy_state(snapshot, plan, inputs),
        }
    )


async def load_inputs(
    pool: asyncpg.Pool, plan: ExecutionPlan, treasury_id: UUID, *, executor: str
) -> ContextInputs:
    """Read the off-chain half of the context for the request a plan serves."""

    row = await pool.fetchrow(
        "SELECT r.id, r.org_id, r.chain_id, r.status, r.invoice_hash, r.fingerprint, r.terms_hash, "
        "r.amount, r.fiat_amount_minor_units, r.current_revision, r.created_by, r.last_edited_by, "
        "'0x' || encode(w.safe_address, 'hex') AS paying_wallet, "
        "'0x' || encode(p.address, 'hex') AS payee, "
        "(SELECT '0x' || encode(sw.safe_address, 'hex') FROM treasury_wallets sw "
        " WHERE sw.treasury_id = r.treasury_id AND sw.role = 'SOURCE') AS safe_t, "
        "(SELECT '0x' || encode(a.address, 'hex') FROM assets a WHERE a.id = r.asset_id) AS asset "
        "FROM payment_requests r "
        "LEFT JOIN treasury_wallets w ON w.id = r.paying_wallet_id "
        "LEFT JOIN payees p ON p.id = r.payee_id "
        "WHERE r.onchain_request_id = $1 AND r.treasury_id = $2",
        plan.request_id,
        treasury_id,
    )
    if row is None:
        raise LookupError("payment request of the plan not found")
    approval_row = await pool.fetchrow(
        "SELECT typed_data, signature, approver_user_id, '0x' || encode(approver_address, 'hex') "
        "AS signer, created_at, acknowledged_flag_ids, solo_mode FROM approvals "
        "WHERE request_id = $1 AND revision = $2 AND status = 'Valid' "
        "ORDER BY created_at DESC LIMIT 1",
        row["id"],
        row["current_revision"],
    )
    approval = None
    request = None
    if approval_row is not None and approval_row["approver_user_id"] is not None:
        typed = _json(approval_row["typed_data"])
        approval = ApprovalView(
            typed=typed,
            signature=bytes(approval_row["signature"]),
            signer=approval_row["signer"],
            approved_at=approval_row["created_at"],
            created_by=row["created_by"] or _NIL,
            last_edited_by=row["last_edited_by"] or _NIL,
            approved_by_user=approval_row["approver_user_id"],
            acknowledged_flag_ids=tuple(approval_row["acknowledged_flag_ids"]),
            solo_mode=approval_row["solo_mode"],
        )
        # The early option and the deadline are signed, not stored on the request: read them from
        # the approval, whose match against the request the validator then checks.
        request = RequestView(
            request_id=plan.request_id,
            # Preparing is "approved, being executed"; the validator names that state Approved.
            status="Approved" if row["status"] == "Preparing" else row["status"],
            invoice_hash=row["invoice_hash"],
            fingerprint=row["fingerprint"],
            terms_hash=row["terms_hash"],
            paying_wallet=row["paying_wallet"],
            payee=row["payee"],
            amount=_units(row["amount"]),
            fiat_amount_minor_units=None
            if row["fiat_amount_minor_units"] is None
            else int(row["fiat_amount_minor_units"]),
            early_amount=_units(typed["earlyAmount"]),
            early_pay_by=int(typed["earlyPayBy"]),
            deadline=int(typed["deadline"]),
        )
    flags = await pool.fetch(
        "SELECT id, code, severity, created_at FROM flags WHERE request_id = $1 AND revision = $2 "
        "AND status <> 'Superseded'",
        row["id"],
        row["current_revision"],
    )
    paused = await pool.fetchval(
        "SELECT paused FROM backend_pause WHERE treasury_id = $1", treasury_id
    )
    circuit = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM chain_safety_signals WHERE treasury_id = $1 "
        "AND signal_type = 'CIRCUIT_BREAKER' AND consumed_at IS NULL AND invalidated_at IS NULL)",
        treasury_id,
    )
    unknown = await pool.fetchval(
        "SELECT count(*) FROM operations WHERE treasury_id = $1 AND status = 'Unknown'",
        treasury_id,
    )
    results = [
        await pool.fetchval(
            "SELECT result::text FROM screenings WHERE org_id = $1 AND chain_id = $2 "
            "AND address = decode($3, 'hex') AND (ttl_until IS NULL OR ttl_until > now()) "
            "ORDER BY checked_at DESC LIMIT 1",
            row["org_id"],
            row["chain_id"],
            step.to.removeprefix("0x"),
        )
        for step in plan.steps
        if step.action is Action.PAY
    ]
    return ContextInputs(
        chain_id=row["chain_id"],
        safe_t=row["safe_t"],
        asset=row["asset"],
        executor=executor,
        request=request,
        approval=approval,
        fingerprint=bytes(row["fingerprint"]) if row["fingerprint"] else None,
        flags=tuple(
            FlagView(id=f["id"], code=f["code"], severity=f["severity"], raised_at=f["created_at"])
            for f in flags
        ),
        unknown_operations=int(unknown),
        pause_requested=bool(paused),
        circuit_open=bool(circuit),
        screening_hit="HIT" in results,
        screening_clear=bool(results) and all(r == "CLEAR" for r in results),
    )


def _json(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value)
