"""POL-003 limit, liquidity, warning and plan-level policy decisions (M08 §8)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from eth_abi import encode
from eth_hash.auto import keccak

from treasurypilot_core.policy.authorization import GATE_NAMES, authorization_checks
from treasurypilot_core.policy.context import Action, ExecutionPlan, PlanStep, ValidationContext
from treasurypilot_core.policy.decision import Check, Decision, aggregate
from treasurypilot_core.policy.reason_codes import PolicyReasonCode as C
from treasurypilot_core.policy.reason_codes import is_warning


def _check(name: str, passed: bool, code: C) -> Check:
    return Check(
        name=name, passed=passed, code=None if passed else code, expected=None, observed=None
    )


def _above(balances: dict[str, int], floors: Mapping[str, int], source: str, amount: int) -> bool:
    """Source is known and keeps at least its floor (buffer/reserve) after paying ``amount``."""
    return (
        source in balances and source in floors and balances[source] - amount >= int(floors[source])
    )


def _state_checks(steps: list[PlanStep], ctx: ValidationContext) -> list[Check]:
    try:
        return _project(steps, ctx)
    except (ArithmeticError, LookupError, TypeError, ValueError):
        # Malformed state (non-numeric amount, missing key) fails closed, like authorization._run.
        return [_check("policy_state_valid", False, C.DATA_MISSING)]


def _project(steps: list[PlanStep], ctx: ValidationContext) -> list[Check]:
    state = ctx.policy_state
    if state is None:
        return [_check("policy_state_present", False, C.DATA_MISSING)]
    checks: list[Check] = []
    balances = {key: int(value) for key, value in state.balances.items()}
    used = {key: int(value) for key, value in state.used_today.items()}
    # Liquidity figures are projected across steps like balances and counters.
    a_token, pool_liquidity = int(state.a_token_balance), int(state.pool_liquidity)
    available_for_supply = int(state.available_for_supply)
    for step in steps:
        source, target, amount = step.from_wallet.lower(), step.to.lower(), int(step.amount)
        key = step.action.value
        if step.step_id in state.step_used:
            checks.append(_check(f"step_unused_{step.seq}", False, C.STEP_ALREADY_EXECUTED))
        if step.action == Action.PAY:
            limit, exception = state.pay_limits, state.exception
            if ctx.request is None:
                checks.append(_check(f"request_present_{step.seq}", False, C.DATA_MISSING))
            else:
                checks.append(
                    _check(
                        f"payment_option_{step.seq}",
                        ctx.request.allows_pay_amount(amount, ctx.now),
                        C.WRONG_PAYMENT_OPTION,
                    )
                )
            checks.append(
                _check(f"request_unpaid_{step.seq}", not state.request_paid, C.REQUEST_ALREADY_PAID)
            )
            checks.append(
                _check(
                    f"fingerprint_unique_{step.seq}",
                    not state.fingerprint_paid or state.duplicate_allowed,
                    C.DUPLICATE_FINGERPRINT,
                )
            )
            exception_valid = bool(
                exception
                and not exception.used
                and exception.expiry >= ctx.now
                and ctx.snapshot.mandate is not None
                and exception.mandate_version == ctx.snapshot.mandate.version
                # Owners except the signed amount; a fiat payment may be below it (pay() matches the same).
                and ctx.request is not None
                and exception.amount == ctx.request.approved_amount(ctx.now)
                and exception.payee.lower() == target
            )
            if exception is not None and amount > limit.per_request:
                checks.append(
                    _check(f"exception_valid_{step.seq}", exception_valid, C.EXCEPTION_INVALID)
                )
            checks.append(
                _check(
                    f"pay_per_request_{step.seq}",
                    amount <= limit.per_request or exception_valid,
                    C.OVER_PER_REQUEST_LIMIT,
                )
            )
            checks.append(
                _check(
                    f"pay_daily_{step.seq}",
                    used.get(key, 0) + amount <= limit.daily,
                    C.OVER_DAILY_LIMIT,
                )
            )
            checks.append(
                _check(
                    f"pay_buffer_{step.seq}",
                    _above(balances, state.buffers, source, amount),
                    C.BUFFER_BREACH,
                )
            )
            if source in balances:
                balances[source] -= amount
            used[key] = used.get(key, 0) + amount
        elif step.action == Action.REFILL:
            limit = state.refill_limits
            checks.append(
                _check(
                    f"refill_request_{step.seq}",
                    not state.refilled_for_request,
                    C.ALREADY_REFILLED_FOR_REQUEST,
                )
            )
            checks.append(
                _check(
                    f"refill_per_request_{step.seq}",
                    amount <= limit.per_request,
                    C.OVER_REFILL_PER_REQUEST,
                )
            )
            checks.append(
                _check(
                    f"refill_daily_{step.seq}",
                    used.get(key, 0) + amount <= limit.daily,
                    C.OVER_REFILL_DAILY,
                )
            )
            checks.append(
                _check(
                    f"refill_source_buffer_{step.seq}",
                    _above(balances, state.buffers, source, amount),
                    C.SOURCE_BUFFER_BREACH,
                )
            )
            request_amount = int(ctx.request.amount) if ctx.request is not None else 0
            target_balance, target_limit = balances.get(target), state.targets.get(target)
            checks.append(
                _check(
                    f"refill_bound_{step.seq}",
                    target_balance is not None
                    and target_limit is not None
                    and target_balance + amount <= request_amount + int(target_limit),
                    C.REFILL_EXCEEDS_NEED,
                )
            )
            if source in balances and target_balance is not None:
                balances[source] -= amount
                balances[target] += amount
            used[key] = used.get(key, 0) + amount
        elif step.action == Action.SUPPLY:
            limit = state.supply_limits
            checks.append(
                _check(
                    f"supply_per_tx_{step.seq}", amount <= limit.per_request, C.OVER_SUPPLY_PER_TX
                )
            )
            checks.append(
                _check(
                    f"supply_daily_{step.seq}",
                    used.get(key, 0) + amount <= limit.daily,
                    C.OVER_SUPPLY_DAILY,
                )
            )
            checks.append(
                _check(
                    f"supply_floor_{step.seq}",
                    _above(balances, state.buffers, source, amount),
                    C.SUPPLY_FLOOR_BREACH,
                )
            )
            checks.append(
                _check(
                    f"supply_available_{step.seq}",
                    available_for_supply >= amount,
                    C.SOURCE_INSUFFICIENT,
                )
            )
            checks.append(
                _check(
                    f"supply_minimum_{step.seq}",
                    amount >= ctx.config.min_supply,
                    C.BELOW_MIN_SUPPLY,
                )
            )
            checks.append(
                _check(
                    f"payment_reserve_{step.seq}",
                    source in balances and balances[source] - amount >= int(state.payment_reserve),
                    C.RESERVE_BREACH,
                )
            )
            if source in balances:
                balances[source] -= amount
            available_for_supply -= amount
            used[key] = used.get(key, 0) + amount
        elif step.action == Action.WITHDRAW:
            checks.append(
                _check(
                    f"withdraw_atoken_{step.seq}",
                    amount <= a_token,
                    C.INSUFFICIENT_A_TOKEN,
                )
            )
            checks.append(
                _check(
                    f"withdraw_liquidity_{step.seq}",
                    amount <= pool_liquidity,
                    C.INSUFFICIENT_POOL_LIQUIDITY,
                )
            )
            balances[target] = balances.get(target, 0) + amount
            a_token -= amount
            pool_liquidity -= amount
        else:
            checks.append(_check(f"supported_action_{step.seq}", False, C.PLAN_MALFORMED))
    return checks


def _policy_version(ctx: ValidationContext) -> bytes:
    """Hash mandate version, validator version and canonical off-chain policy config."""
    mandate_version = ctx.snapshot.mandate.version if ctx.snapshot.mandate is not None else 0
    config_hash = keccak(
        json.dumps(
            ctx.config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    )
    return keccak(
        encode(
            ["uint256", "string", "bytes32"],
            [mandate_version, ctx.config.validator_version, config_hash],
        )
    )


def _decide(
    checks: list[Check], ctx: ValidationContext, stage: Literal["PLAN", "PRE_STEP"], seq: int | None
) -> Decision:
    codes = [c.code for c in checks if c.code is not None and not is_warning(c.code)]
    warnings = [c.code for c in checks if c.code is not None and is_warning(c.code)]
    outcome, primary = aggregate(codes)
    return Decision(
        decision=outcome,
        primary=primary,
        codes=codes,
        warnings=warnings,
        checks=checks,
        stage=stage,
        step_seq=seq,
        policy_version=_policy_version(ctx),
        snapshot_block=ctx.snapshot.block_number,
    )


def _timing_checks(steps: list[PlanStep], ctx: ValidationContext) -> list[Check]:
    """Late-payment warnings; only a PAY step has a deadline or an early-payment discount."""
    request = ctx.request
    if request is None or not any(step.action == Action.PAY for step in steps):
        return []
    checks: list[Check] = []
    if ctx.now > request.deadline:
        checks.append(_check("deadline", False, C.DEADLINE_MISSED))
    if request.early_amount > 0 and ctx.now > request.early_pay_by:
        checks.append(_check("discount", False, C.DISCOUNT_MISSED))
    return checks


def _gated(auth: list[Check], steps: list[PlanStep], ctx: ValidationContext) -> list[Check]:
    """Authorization checks plus the limit, liquidity and timing checks (M08 §8.1).

    A failed gate skips the step checks: their inputs may be untrustworthy.
    """
    if any(c.name in GATE_NAMES and not c.passed for c in auth):
        skipped = Check(
            name="policy_state", passed=False, skipped=True, code=None, expected=None, observed=None
        )
        return [*auth, skipped]
    return auth + _state_checks(steps, ctx) + _timing_checks(steps, ctx)


def validate_plan(plan: ExecutionPlan, ctx: ValidationContext) -> Decision:
    """Validate every step in order, projecting balances and counters across the plan."""
    steps = list(plan.steps)
    return _decide(_gated(authorization_checks(plan, ctx), steps, ctx), ctx, "PLAN", None)


def validate_step(plan: ExecutionPlan, seq: int, ctx: ValidationContext) -> Decision:
    """Validate one step against the supplied fresh state snapshot."""
    step = next((item for item in plan.steps if item.seq == seq), None)
    checks = (
        [_check("step_exists", False, C.PLAN_MALFORMED)]
        if step is None
        else _gated(authorization_checks(plan, ctx, seq=seq), [step], ctx)
    )
    return _decide(checks, ctx, "PRE_STEP", seq)
