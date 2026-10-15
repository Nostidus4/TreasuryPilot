"""Gas-shortage handling of the planning pipeline (EXE-011, F-064): prepend a bounded swap.

When the executor's native balance cannot pay the plan's estimated fee, the plan gets a leading
SWAP step on the test router. The engine sizes it (``plan_gas_swap``); this module only gathers
the inputs and builds the step.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from treasurypilot_core.eip712 import SWAP_IN, step_id
from treasurypilot_core.engine import GasQuote, GasSwapInfeasible, plan_gas_swap
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep

logger = logging.getLogger(__name__)


class GasSwapUnavailable(RuntimeError):
    """There is a gas shortage but no configured test source to quote it."""


@dataclass(frozen=True)
class GasSwapDeps:
    native_balance: Callable[[uuid.UUID], Awaitable[int]]  # executor native balance, wei
    quote: Callable[[uuid.UUID, str], Awaitable[GasQuote | None]]  # (treasury, module) -> quote
    slippage_bps: int
    # the module's per-swap cap (no on-chain getter); None = swapping disabled, shortage only logged
    max_amount_in: int | None


async def with_gas_swap(
    deps: GasSwapDeps,
    treasury_id: uuid.UUID,
    plan: ExecutionPlan,
    *,
    required_wei: int,
    safe_t: str,
    asset: str,
) -> ExecutionPlan:
    """``plan`` unchanged without a shortage, else with the swap first.

    Raises ``GasSwapUnavailable`` (no quote source) or ``GasSwapInfeasible`` (over the bound).
    shortcut: ``required_wei`` is the fee of the plan without the swap step; add its gas if the
    margin matters.
    """

    balance = await deps.native_balance(treasury_id)
    if balance >= required_wei:
        return plan
    if deps.max_amount_in is None:
        logger.warning(
            "gas_shortage_swap_disabled",
            extra={
                "treasury_id": str(treasury_id),
                "balance_wei": balance,
                "required_wei": required_wei,
            },
        )
        return plan
    quote = await deps.quote(treasury_id, plan.treasury)
    if quote is None:
        raise GasSwapUnavailable("no test-router quote is configured")
    swap = plan_gas_swap(
        required_wei=required_wei,
        native_balance_wei=balance,
        quote=quote,
        slippage_bps=deps.slippage_bps,
        max_amount_in=deps.max_amount_in,
    )
    assert swap is not None  # balance < required_wei
    step = PlanStep(
        seq=0,
        step_id=step_id(plan.request_id, SWAP_IN, safe_t),
        action=Action.SWAP,
        from_wallet=safe_t,
        to=swap.router,
        asset=asset,
        amount=BaseUnits(int(swap.amount_in)),
        min_out=swap.min_out,
        venue=swap.venue,
    )
    shifted = [s.model_copy(update={"seq": s.seq + 1}) for s in plan.steps]
    return plan.model_copy(update={"steps": [step, *shifted]})


__all__ = ["GasSwapDeps", "GasSwapInfeasible", "GasSwapUnavailable", "with_gas_swap"]
