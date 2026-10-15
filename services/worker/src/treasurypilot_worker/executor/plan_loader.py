"""Load an attested plan from PostgreSQL and turn it into signer requests (EXE-008 driver)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.eip712 import PAY, REFILL, WITHDRAW
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep
from treasurypilot_worker.executor.outbox import StepExecution
from treasurypilot_worker.executor.sequencer import PlanRun
from treasurypilot_worker.executor.simulation import SimulationContext, build_calldata
from treasurypilot_worker.planner.context import ContextInputs

# SUPPLY/SWAP have no ExecutionPlan wire mapping yet (see ExecutionPlan.message).
_ACTIONS = {PAY: Action.PAY, REFILL: Action.REFILL, WITHDRAW: Action.WITHDRAW}


@dataclass(frozen=True)
class LoadedPlan:
    plan_id: UUID
    treasury_id: UUID
    request_id: UUID
    plan_step_ids: tuple[UUID, ...]  # plan_steps.id in seq order
    plan: ExecutionPlan
    typed_data: dict[str, Any]
    signature: bytes
    valid_until: datetime

    @property
    def executor(self) -> str:
        return str(self.typed_data["message"]["executor"])


def _hex(raw: Any) -> str:
    return "0x" + bytes(raw).hex()


async def load_plan(pool: asyncpg.Pool, plan_id: UUID) -> LoadedPlan | None:
    """The newest attestation of the plan with its steps; None when it has none or an unsupported step."""

    attestation = await pool.fetchrow(
        "SELECT id, request_id, typed_data, signature, valid_until FROM attestations "
        "WHERE plan_id = $1 ORDER BY created_at DESC, id DESC LIMIT 1",
        plan_id,
    )
    if attestation is None:
        return None
    rows = await pool.fetch(
        "SELECT * FROM plan_steps WHERE attestation_id = $1 ORDER BY seq", attestation["id"]
    )
    request = await pool.fetchrow(
        "SELECT id, treasury_id FROM payment_requests WHERE onchain_request_id = $1",
        attestation["request_id"],
    )
    if not rows or request is None or any(r["action"] not in _ACTIONS for r in rows):
        return None
    first = rows[0]
    typed = attestation["typed_data"]
    plan = ExecutionPlan(
        request_id=bytes(first["request_id"]),
        treasury=_hex(first["treasury_address"]),
        chain_id=first["chain_id"],
        steps=[
            PlanStep(
                seq=r["seq"],
                step_id=bytes(r["step_id"]),
                action=_ACTIONS[r["action"]],
                from_wallet=_hex(r["from_address"]),
                to=_hex(r["to_address"]),
                asset=_hex(r["asset_address"]),
                amount=BaseUnits(int(r["amount"])),
            )
            for r in rows
        ],
        planner_source="DETERMINISTIC",  # not persisted; the validator does not read it
        evidence_ids=[],
    )
    return LoadedPlan(
        plan_id=plan_id,
        treasury_id=request["treasury_id"],
        request_id=request["id"],
        plan_step_ids=tuple(r["id"] for r in rows),
        plan=plan,
        typed_data=typed if isinstance(typed, dict) else json.loads(typed),
        signature=bytes(attestation["signature"]),
        valid_until=attestation["valid_until"],
    )


def simulation_context(loaded: LoadedPlan, inputs: ContextInputs) -> SimulationContext:
    """What the signer will send; ``snapshot_block`` and ``policy_version`` are set per step."""

    approval = inputs.approval
    return SimulationContext(
        executor=loaded.executor,
        target=loaded.plan.treasury,
        attestation=loaded.typed_data["message"],
        attestation_signature=loaded.signature,
        policy_version=b"\x00" * 32,
        snapshot_block=0,
        approval=approval.typed if approval else None,
        approver_signature=approval.signature if approval else b"",
        travel_rule_clear=inputs.travel_rule_clear,
    )


def plan_run(loaded: LoadedPlan, inputs: ContextInputs, fees: dict[str, int]) -> PlanRun:
    """Signer requests for every step; ``fees`` is the signer's Fees body (EXE-005 policy)."""

    sim = simulation_context(loaded, inputs)
    body = loaded.plan.message()
    steps = []
    for step, row_id in zip(loaded.plan.steps, loaded.plan_step_ids, strict=True):
        steps.append(
            StepExecution(
                treasury_id=loaded.treasury_id,
                request_id=loaded.request_id,
                plan_step_id=row_id,
                step_id=step.step_id,
                kind=step.action.value,
                chain_id=loaded.plan.chain_id,
                sign_request={
                    "treasuryId": str(loaded.treasury_id),
                    "plan": body,
                    "attestation": loaded.typed_data,
                    "signature": "0x" + loaded.signature.hex(),
                    "stepSeq": step.seq,
                    "payload": {
                        "to": loaded.plan.treasury,
                        "data": "0x" + build_calldata(step, sim).hex(),
                    },
                    "fees": fees,
                },
            )
        )
    return PlanRun(loaded.plan_id, loaded.request_id, tuple(steps), loaded.valid_until)
