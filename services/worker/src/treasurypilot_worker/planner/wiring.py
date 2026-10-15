"""Production wiring of the planning pipeline: chain, policy key, fee estimate, AI queue."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from eth_abi import decode
from eth_hash.auto import keccak

from treasurypilot_core.domain.fee_policy import PRESETS, FeePreset, estimate_plan_fee_wei
from treasurypilot_core.engine import GAS_SWAP_VENUE, GasQuote
from treasurypilot_core.policy import Decision, ExecutionPlan
from treasurypilot_worker.attestation import attest, load_policy_key
from treasurypilot_worker.celery_app import app
from treasurypilot_worker.chain.rpc import RpcClient, build_rpc_client, decode_rpc_urls
from treasurypilot_worker.chain.snapshot import SnapshotPurpose, SnapshotScope, take_snapshot
from treasurypilot_worker.config import Settings
from treasurypilot_worker.planner.ai import PROPOSE_TASK, CeleryAiProposer
from treasurypilot_worker.planner.gas import GasSwapDeps
from treasurypilot_worker.planner.pipeline import PlannerDeps
from treasurypilot_worker.planner.reattest import AttestFn

# shortcut: a fixed per-step gas budget instead of eth_estimateGas (the planner has no calldata or
# simulation context yet); the signer re-estimates with a 20 % margin and refuses any step whose
# gas_limit * maxFeePerGas exceeds the cap, so an under-estimate fails closed (FEE_CAP_EXCEEDED).
# Upgrade when the executor's calldata builder is usable at plan time.
STEP_GAS = 150_000


def build_attest(settings: Settings) -> AttestFn:
    """Sign and store a PlanAttestation with the policy key (used by planning and re-attestation)."""

    if not (settings.executor_address and settings.database_url):
        raise RuntimeError("TP_EXECUTOR_ADDRESS and DATABASE_URL are required for attestation")
    database_url, executor = settings.database_url, settings.executor_address
    key = load_policy_key(settings.policy_keystore_path, settings.policy_keystore_password_file)

    async def issue(
        plan_id: uuid.UUID,
        plan: Mapping[str, Any],
        decision: Decision,
        digest: str,
        now: datetime,
    ) -> None:
        await asyncio.to_thread(
            attest,
            database_url,
            key,
            plan_id=plan_id,
            plan=plan,
            decision=decision,
            executor=executor,
            evidence_digest=digest,
            now=now,
        )

    return issue


async def _view(rpc: RpcClient, to: str, signature: str, output: str) -> Any:
    data = "0x" + keccak(signature.encode())[:4].hex()
    raw = await rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
    return decode([output], bytes.fromhex(raw.removeprefix("0x")))[0]


async def read_test_router_quote(rpc: RpcClient, module: str) -> GasQuote | None:
    """The module's configured test router and its fixed rate; None when none is configured."""

    router = str(await _view(rpc, module, "swapRouter()", "address"))
    if int(router, 16) == 0:
        return None
    return GasQuote(
        source=GAS_SWAP_VENUE,
        router=router,
        token_out=str(await _view(rpc, router, "tokenOut()", "address")),
        numerator=int(await _view(rpc, router, "numerator()", "uint256")),
        denominator=int(await _view(rpc, router, "denominator()", "uint256")),
    )


def build_deps(pool: asyncpg.Pool, settings: Settings) -> PlannerDeps:
    if not (settings.executor_address and settings.database_url):
        raise RuntimeError("TP_EXECUTOR_ADDRESS and DATABASE_URL are required for planning")
    executor = settings.executor_address

    async def snapshot(treasury_id: uuid.UUID, scope: SnapshotScope) -> Any:
        taken = await take_snapshot(pool, treasury_id, SnapshotPurpose.PLAN, scope)
        return taken, taken.block_number  # read at "latest": the head is the snapshot block

    async def treasury_rpc(treasury_id: uuid.UUID) -> RpcClient:
        urls = await pool.fetchval(
            "SELECT c.rpc_urls FROM treasuries t JOIN chains c ON c.chain_id = t.chain_id "
            "WHERE t.id = $1",
            treasury_id,
        )
        return build_rpc_client(decode_rpc_urls(urls))

    async def estimate_fee(treasury_id: uuid.UUID, plan: ExecutionPlan) -> int:
        row = await pool.fetchrow(
            "SELECT c.rpc_urls, (SELECT max_fee_multiplier_bps FROM treasury_fee_policies "
            " WHERE treasury_id = t.id AND accepted_at IS NOT NULL AND superseded_at IS NULL) "
            "AS multiplier FROM treasuries t JOIN chains c ON c.chain_id = t.chain_id "
            "WHERE t.id = $1",
            treasury_id,
        )
        rpc = build_rpc_client(decode_rpc_urls(row["rpc_urls"]))
        gas_price = int(await rpc.call("eth_gasPrice", []), 16)
        multiplier = row["multiplier"] or PRESETS[FeePreset.NORMAL].max_fee_multiplier_bps
        max_fee = gas_price * multiplier // 10_000
        steps = len(plan.steps)
        return estimate_plan_fee_wei([STEP_GAS] * steps, [max_fee] * steps)

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        result = app.send_task(PROPOSE_TASK, kwargs=request, queue="ai")
        # Blocking inside a task is safe here: the AI task runs on another queue and worker.
        payload: dict[str, Any] = result.get(
            timeout=settings.planning_ai_timeout_seconds, disable_sync_subtasks=False
        )
        return payload

    async def balance(treasury_id: uuid.UUID) -> int:
        rpc = await treasury_rpc(treasury_id)
        return int(await rpc.call("eth_getBalance", [executor, "latest"]), 16)

    async def quote(treasury_id: uuid.UUID, module: str) -> GasQuote | None:
        return await read_test_router_quote(await treasury_rpc(treasury_id), module)

    # Always wired so a shortage with swapping disabled (max_amount_in None) is logged.
    gas_swap = GasSwapDeps(
        balance, quote, settings.gas_swap_slippage_bps, settings.gas_swap_max_amount_in
    )
    return PlannerDeps(
        take_snapshot=snapshot,
        executor=executor,
        estimate_fee=estimate_fee,
        attest=build_attest(settings),
        ai=CeleryAiProposer(ask) if settings.planning_ai_enabled else None,
        gas_swap=gas_swap,
    )
