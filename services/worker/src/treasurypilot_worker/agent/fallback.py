"""Rule-based fallback plans (BR-055, FR-409): tested templates, never more authority.

No model, no I/O. The plan is built from the validator's own context and accepted only if
`validate_plan` says ALLOW, so a template cannot do anything the AI path could not.
"""

from dataclasses import dataclass
from enum import StrEnum

from treasurypilot_core.domain import WalletState
from treasurypilot_core.eip712 import PAY, REFILL, step_id
from treasurypilot_core.engine import preferred_refill, refill_bound, shortage
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ExecutionPlan,
    PlanStep,
    ValidationContext,
    validate_plan,
)
from treasurypilot_worker.agent.errors import (
    AiBudgetExceeded,
    AiError,
    AiSchemaError,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
)

# An AiInputRejected is a secret in the input, not an outage: the fallback must not hide it.
_OUTAGE = (AiTimeout, AiUnavailable, AiBudgetExceeded, AiSchemaError, AiToolLimitExceeded)


class FallbackTemplate(StrEnum):
    PAY_DIRECT = "PAY_DIRECT"
    REFILL_THEN_PAY = "REFILL_THEN_PAY"
    # SWAP_THEN_PAY is P2: Action.SWAP has no module code or validator rule yet.


class FallbackRefusal(StrEnum):
    """Why no fallback runs; every one routes the request to NeedsReview."""

    NOT_AN_OUTAGE = "NOT_AN_OUTAGE"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    SAFETY_ALERT = "SAFETY_ALERT"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"
    NO_TEMPLATE = "NO_TEMPLATE"


@dataclass(frozen=True)
class FallbackPlan:
    template: FallbackTemplate
    plan: ExecutionPlan


@dataclass(frozen=True)
class FallbackRefused:
    reason: FallbackRefusal


def plan_fallback(ctx: ValidationContext, error: AiError) -> FallbackPlan | FallbackRefused:
    """BR-055: the AI failed with ``error`` and every other condition holds, else refuse."""
    if not isinstance(error, _OUTAGE):
        return FallbackRefused(FallbackRefusal.NOT_AN_OUTAGE)
    if ctx.unknown_operations:
        return FallbackRefused(FallbackRefusal.UNKNOWN_OPERATION)
    # shortcut: any HIGH flag blocks, acknowledged or not; relax if BR-066 acks should pass.
    if (
        ctx.pause_requested
        or ctx.circuit_open
        or ctx.screening_hit
        or any(flag.severity == "HIGH" for flag in ctx.flags)
    ):
        return FallbackRefused(FallbackRefusal.SAFETY_ALERT)
    request, state = ctx.request, ctx.policy_state
    if (
        ctx.coverage != "COMPLETE"
        or request is None
        or state is None
        or ctx.approval is None
        or ctx.snapshot.mandate is None
        or not ctx.screening_clear
        or ctx.travel_rule_clear is False
    ):
        return FallbackRefused(FallbackRefusal.DATA_INCOMPLETE)

    wallet_key = request.paying_wallet.lower()
    try:
        wallet = WalletState(
            address=request.paying_wallet,
            balance=state.balances[wallet_key],
            buffer=state.buffers[wallet_key],
            target=state.targets[wallet_key],
        )
    except (KeyError, ValueError):
        return FallbackRefused(FallbackRefusal.DATA_INCOMPLETE)

    early = request.early_amount > 0 and ctx.now <= request.early_pay_by
    amount = request.early_amount if early else request.amount
    missing = shortage(wallet, amount, BaseUnits(0))
    refills: list[BaseUnits] = []
    if missing:
        # BR-032: top up to the target if allowed, else just enough to pay.
        preferred = BaseUnits(
            min(preferred_refill(wallet, amount, BaseUnits(0)), refill_bound(wallet, amount))
        )
        refills = [preferred, missing] if preferred > missing else [missing]

    for refill in refills or [BaseUnits(0)]:
        template = FallbackTemplate.REFILL_THEN_PAY if refill else FallbackTemplate.PAY_DIRECT
        plan = _plan(ctx, request.paying_wallet, amount, refill, template)
        if validate_plan(plan, ctx).decision == "ALLOW":
            return FallbackPlan(template, plan)
    return FallbackRefused(FallbackRefusal.NO_TEMPLATE)


def _plan(
    ctx: ValidationContext,
    wallet: str,
    amount: BaseUnits,
    refill: BaseUnits,
    template: FallbackTemplate,
) -> ExecutionPlan:
    request, snapshot = ctx.request, ctx.snapshot
    assert request is not None
    steps = []
    if refill:
        steps.append(
            PlanStep(
                seq=0,
                step_id=step_id(request.request_id, REFILL, wallet),
                action=Action.REFILL,
                from_wallet=snapshot.safe_t,
                to=wallet,
                asset=snapshot.asset,
                amount=refill,
            )
        )
    steps.append(
        PlanStep(
            seq=len(steps),
            step_id=step_id(request.request_id, PAY, wallet),
            action=Action.PAY,
            from_wallet=wallet,
            to=request.payee,
            asset=snapshot.asset,
            amount=amount,
        )
    )
    return ExecutionPlan(
        request_id=request.request_id,
        treasury=snapshot.treasury,
        chain_id=snapshot.chain_id,
        steps=steps,
        planner_source="RULE_BASED",
        evidence_ids=[f"template:{template}"],
    )
