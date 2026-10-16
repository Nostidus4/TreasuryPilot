"""Renew an expired attestation mid-plan (M10 §5): validate again, sign again, same plan and steps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.policy import Decision, validate_plan
from treasurypilot_worker.chain.rpc import RpcClient
from treasurypilot_worker.chain.snapshot import SnapshotPurpose, take_snapshot
from treasurypilot_worker.executor.plan_loader import (
    LoadedPlan,
    load_plan,
    plan_run,
    snapshot_executor,
)
from treasurypilot_worker.executor.sequencer import PlanRun
from treasurypilot_worker.planner.context import ContextInputs, build_context, scope_for
from treasurypilot_worker.planner.pipeline import evidence_digest

# (plan_id, plan message, decision, evidence digest, now[, liquidity_cycle_id= for a liquidity plan])
AttestFn = Callable[..., Awaitable[None]]


def reattest_fn(
    pool: asyncpg.Pool,
    loaded: LoadedPlan,
    inputs: ContextInputs,
    *,
    rpc: RpcClient,
    attest: AttestFn,
    fees: dict[str, int],
) -> Callable[[int], Awaitable[PlanRun | Decision]]:
    """The ``PlanGate.reattest_fn`` for ``loaded``: a non-ALLOW decision stops the plan."""

    async def reattest(seq: int) -> PlanRun | Decision:
        snapshot = await take_snapshot(
            pool, loaded.treasury_id, SnapshotPurpose.PRE_STEP, scope_for(loaded.plan, inputs)
        )
        now = datetime.now(UTC)
        context = build_context(
            snapshot,
            loaded.plan,
            inputs,
            now=int(now.timestamp()),
            head_block=int(await rpc.call("eth_blockNumber", []), 16),
        )
        # Steps before ``seq`` are already used on chain and would fail validation: only the
        # remaining ones are checked, while the attestation covers the whole plan (its hash).
        remaining = loaded.plan.model_copy(update={"steps": loaded.plan.steps[seq:]})
        decision = validate_plan(remaining, context)
        if decision.decision != "ALLOW":
            return decision
        cycle = {} if loaded.liquidity_cycle_id is None else {
            "liquidity_cycle_id": "0x" + loaded.liquidity_cycle_id.hex()
        }  # fmt: skip
        await attest(
            loaded.plan_id, loaded.plan.message(), decision, evidence_digest(snapshot), now, **cycle
        )
        renewed = await load_plan(pool, loaded.plan_id)  # the newest attestation, with its steps
        assert renewed is not None
        return plan_run(renewed, inputs, fees, snapshot_executor(snapshot))

    return reattest
