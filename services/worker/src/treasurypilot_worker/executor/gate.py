"""Concrete ``Gate`` for the sequencer (EXE-008, M10 §7.3 step 1).

Before each step: a fresh PRE_STEP snapshot, ``validate_step`` on a context built from it, then the
``eth_call`` simulation, both recorded in ``validations``. The first non-ALLOW decision stops.
Snapshot freshness (30 s / 2 blocks, M08-D6) is the validator's ``snapshot_fresh`` gate: the context
carries the block time and the head read from the RPC just after the snapshot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.policy import Decision, ExecutionPlan, validate_step
from treasurypilot_worker.chain.rpc import RpcClient
from treasurypilot_worker.chain.snapshot import (
    Snapshot,
    SnapshotPurpose,
    SnapshotScope,
    take_snapshot,
)
from treasurypilot_worker.executor.sequencer import PlanRun
from treasurypilot_worker.executor.simulation import SimulationContext, record_validation, simulate
from treasurypilot_worker.planner.context import ContextInputs, build_context, scope_for

SnapshotFn = Callable[[SnapshotScope], Awaitable[Snapshot]]


@dataclass
class PlanGate:
    pool: asyncpg.Pool
    rpc: RpcClient
    plan_id: UUID
    plan: ExecutionPlan
    inputs: ContextInputs
    simulation: SimulationContext  # snapshot_block/policy_version are filled per step
    # Re-validates and re-attests the plan from step ``seq`` on (the planner pipeline, EXE-004).
    reattest_fn: Callable[[int], Awaitable[PlanRun | Decision]]
    snapshot_fn: SnapshotFn
    treasury_id: UUID | None = None

    @classmethod
    def for_treasury(cls, pool: asyncpg.Pool, treasury_id: UUID, **fields) -> PlanGate:  # type: ignore[no-untyped-def]
        async def snapshot(scope: SnapshotScope) -> Snapshot:
            return await take_snapshot(pool, treasury_id, SnapshotPurpose.PRE_STEP, scope)

        return cls(pool=pool, snapshot_fn=snapshot, treasury_id=treasury_id, **fields)

    async def pre_step(self, seq: int) -> Decision:
        # CHR-006 / chain-reader §8.4: pending PRE_STEP_REVALIDATION signals are read before the
        # snapshot (which is always fresh), and consumed once this validation has been recorded,
        # whether it allows or blocks. Signals arriving meanwhile stay pending for the next step.
        signal_ids: list[UUID] = []
        if self.treasury_id is not None:
            rows = await self.pool.fetch(
                "SELECT id FROM chain_safety_signals WHERE treasury_id = $1 "
                "AND signal_type = 'PRE_STEP_REVALIDATION' AND consumed_at IS NULL "
                "AND invalidated_at IS NULL",
                self.treasury_id,
            )
            signal_ids = [row["id"] for row in rows]
        snapshot = await self.snapshot_fn(scope_for(self.plan, self.inputs))
        head = int(await self.rpc.call("eth_blockNumber", []), 16)
        context = build_context(
            snapshot,
            self.plan,
            self.inputs,
            now=int(datetime.now(UTC).timestamp()),
            head_block=head,
        )
        decision = validate_step(self.plan, seq, context)
        await record_validation(self.pool, self.plan_id, decision)
        if signal_ids:
            await self.pool.execute(
                "UPDATE chain_safety_signals SET consumed_at = now() "
                "WHERE id = ANY($1::uuid[]) AND consumed_at IS NULL AND invalidated_at IS NULL",
                signal_ids,
            )
        if decision.decision != "ALLOW":
            return decision
        base = self.simulation
        simulation = SimulationContext(
            executor=base.executor,
            target=base.target,
            attestation=base.attestation,
            attestation_signature=base.attestation_signature,
            policy_version=decision.policy_version,
            snapshot_block=snapshot.block_number,
            approval=base.approval,
            approver_signature=base.approver_signature,
            travel_rule_clear=base.travel_rule_clear,
        )
        result = await simulate(self.rpc, self.plan.steps[seq], simulation)
        await record_validation(self.pool, self.plan_id, result)
        return result

    async def reattest(self, seq: int) -> PlanRun | Decision:
        return await self.reattest_fn(seq)
