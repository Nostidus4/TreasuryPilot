"""Gate, approval, mandate, payee and plan-shape checks (M08 §8.1, POL-002).

Limits, liquidity and the final `Decision` are POL-003; this returns the checks they aggregate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from treasurypilot_core.eip712 import Erc1271Call, payment_approval_typed_data, verify_signature
from treasurypilot_core.policy.context import (
    Action,
    ApprovalView,
    ExecutionPlan,
    MandateView,
    PayeeView,
    PlanStep,
    RequestView,
    ValidationContext,
)
from treasurypilot_core.policy.decision import Check
from treasurypilot_core.policy.reason_codes import PolicyReasonCode as C

APPROVED_STATUSES = frozenset({"Approved", "Scheduled", "Paying"})


@dataclass(frozen=True)
class _Inputs:
    plan: ExecutionPlan
    steps: list[PlanStep]
    ctx: ValidationContext
    erc1271: Erc1271Call | None

    # Only read by rules that run after the gates (request, mandate) or with an approval.
    # Explicit checks, not assert: they must fail closed under `python -O` too (see `_run`).
    @property
    def request(self) -> RequestView:
        if self.ctx.request is None:
            raise LookupError("request")
        return self.ctx.request

    @property
    def mandate(self) -> MandateView:
        if self.ctx.snapshot.mandate is None:
            raise LookupError("mandate")
        return self.ctx.snapshot.mandate

    @property
    def approval(self) -> ApprovalView:
        if self.ctx.approval is None:
            raise LookupError("approval")
        return self.ctx.approval


type _Rule = tuple[str, C, Callable[[_Inputs], bool]]  # name, code on failure, passes?


def _same(a: object, b: object) -> bool:
    return str(a).lower() == str(b).lower()


def _hex(value: bytes) -> str:
    return "0x" + value.hex()


def _fresh(i: _Inputs) -> bool:
    ctx, cfg = i.ctx, i.ctx.config
    return (
        # A snapshot from the future (clock skew, lagging head) is not trusted either.
        0 <= ctx.now - ctx.snapshot.read_at <= cfg.snapshot_max_age_seconds
        and 0 <= ctx.head_block - ctx.snapshot.block_number <= cfg.snapshot_max_blocks_behind
    )


def _assets_match(i: _Inputs) -> bool:
    assets = [s.asset for s in i.plan.steps]
    if i.ctx.approval is not None:
        assets.append(i.ctx.approval.typed["asset"])
    return all(_same(a, i.ctx.snapshot.asset) for a in assets)


_GATES: list[_Rule] = [
    ("pause_requested", C.PAUSE_REQUESTED, lambda i: not i.ctx.pause_requested),
    ("circuit_open", C.CIRCUIT_OPEN, lambda i: not i.ctx.circuit_open),
    ("unknown_operations", C.UNKNOWN_OPERATION_PENDING, lambda i: i.ctx.unknown_operations == 0),
    ("coverage", C.COVERAGE_INCOMPLETE, lambda i: i.ctx.coverage in ("COMPLETE", "PARTIAL_ACK")),
    ("snapshot_fresh", C.SNAPSHOT_STALE, _fresh),
    (
        "data_present",
        C.DATA_MISSING,
        lambda i: i.ctx.request is not None and i.ctx.snapshot.mandate is not None,
    ),
    (
        "chain_match",
        C.CHAIN_MISMATCH,
        lambda i: i.plan.chain_id == i.ctx.snapshot.chain_id
        and _same(i.plan.treasury, i.ctx.snapshot.treasury),
    ),
    ("asset_match", C.ASSET_MISMATCH, _assets_match),
]

GATE_NAMES = frozenset(name for name, _, _ in _GATES)

_REQUEST_RULES: list[_Rule] = [
    ("request_present", C.DATA_MISSING, lambda i: i.ctx.request is not None),
    (
        "request_not_cancelled",
        C.REQUEST_CANCELLED,
        lambda i: i.request.status != "Cancelled" and not i.ctx.snapshot.request_cancelled,
    ),
    (
        # Cancelled is reported once, as REQUEST_CANCELLED.
        "request_approved",
        C.NOT_APPROVED,
        lambda i: i.ctx.approval is not None
        and (i.request.status in APPROVED_STATUSES or i.request.status == "Cancelled"),
    ),
]

# Need only the mandate, so they also run for liquidity (SUPPLY/WITHDRAW) plans.
_MANDATE_RULES: list[_Rule] = [
    ("screening", C.SCREENING_HIT, lambda i: not i.ctx.screening_hit),
    # A HIT is already reported as SCREENING_HIT; do not also call it missing data.
    ("screening_clear", C.DATA_MISSING, lambda i: i.ctx.screening_clear or i.ctx.screening_hit),
    ("mandate_not_paused", C.MANDATE_PAUSED, lambda i: i.mandate.status != "Paused"),
    ("mandate_not_revoked", C.MANDATE_REVOKED, lambda i: i.mandate.status != "Revoked"),
    ("mandate_started", C.MANDATE_NOT_ACTIVE, lambda i: i.ctx.now >= i.mandate.valid_from),
    ("mandate_not_expired", C.MANDATE_EXPIRED, lambda i: i.ctx.now <= i.mandate.expires_at),
    ("executor", C.EXECUTOR_MISMATCH, lambda i: _same(i.ctx.executor, i.mandate.executor)),
]


def _approval_matches_request(i: _Inputs) -> bool:
    t, r = i.approval.typed, i.request
    return (
        _same(t["requestId"], _hex(r.request_id))
        and _same(t["invoiceHash"], _hex(r.invoice_hash))
        and _same(t["fingerprint"], _hex(r.fingerprint))
        and _same(t["termsHash"], _hex(r.terms_hash))
        and _same(t["payingWallet"], r.paying_wallet)
        and _same(t["payee"], r.payee)
        and int(t["amount"]) == r.amount
        and int(t["earlyAmount"]) == r.early_amount
        and int(t["earlyPayBy"]) == r.early_pay_by
        and int(t["deadline"]) == r.deadline
    )


def _signature_valid(i: _Inputs) -> bool:
    a = i.approval
    typed = payment_approval_typed_data(
        a.typed, chain_id=i.plan.chain_id, verifying_contract=i.plan.treasury
    )
    return _same(a.typed["treasury"], i.plan.treasury) and verify_signature(
        typed, a.signer, a.signature, erc1271=i.erc1271
    )


def _flags_acknowledged(i: _Inputs) -> bool:
    """M08-D4: HIGH flags raised before approval are acknowledged; none raised at or after it."""
    a = i.approval
    return all(
        f.raised_at < a.approved_at and f.id in a.acknowledged_flag_ids
        for f in i.ctx.flags
        if f.severity == "HIGH"
    )


_APPROVAL_RULES: list[_Rule] = [
    ("approval_matches_request", C.APPROVAL_STALE, _approval_matches_request),
    ("approval_signature", C.APPROVAL_INVALID, _signature_valid),
    (
        "approver_in_current_set",
        C.NOT_IN_APPROVER_SET,
        lambda i: any(_same(i.approval.signer, x) for x in i.ctx.snapshot.approvers),
    ),
    (
        "approval_not_expired",
        C.APPROVAL_EXPIRED,
        lambda i: i.ctx.now <= int(i.approval.typed["expiry"]),
    ),
    (
        "maker_checker",
        C.MAKER_CHECKER,
        lambda i: i.approval.solo_mode
        or i.approval.approved_by_user not in (i.approval.created_by, i.approval.last_edited_by),
    ),
    ("flags_acknowledged", C.FLAG_UNACKNOWLEDGED, _flags_acknowledged),
]


def _payee(i: _Inputs) -> PayeeView | None:
    # The contract checks the approval's payee; the request equals it unless APPROVAL_STALE.
    return i.ctx.snapshot.payees.get(i.request.payee.lower())


_PAY_RULES: list[_Rule] = [
    ("payee_active", C.PAYEE_UNKNOWN, lambda i: (p := _payee(i)) is not None and p.active),
    # An unknown or deactivated payee is reported once, as PAYEE_UNKNOWN.
    (
        "payee_cooling_over",
        C.PAYEE_COOLING,
        lambda i: (p := _payee(i)) is None or not p.active or i.ctx.now >= p.active_from,
    ),
]


_PLAN_SHAPES = (
    [Action.PAY],
    [Action.REFILL, Action.PAY],
    [Action.WITHDRAW, Action.REFILL, Action.PAY],
    [Action.SUPPLY],
    [Action.WITHDRAW],
    [Action.SUPPLY, Action.WITHDRAW],
)


def _plan_well_formed(i: _Inputs) -> bool:
    """§8.1 plan shape. Request fields stand in for the approval's (APPROVAL_STALE covers drift).

    shortcut: stepId is not recomputed until POL-005 ships `step_id`; add it to this check then.
    """
    steps, snap = list(i.plan.steps), i.ctx.snapshot
    actions = [s.action for s in steps]
    if actions and all(action in (Action.SUPPLY, Action.WITHDRAW) for action in actions):
        return (
            [s.seq for s in steps] == list(range(len(steps)))
            and actions in _PLAN_SHAPES
            and len({s.step_id for s in steps}) == len(steps)
            and all(_same(s.to, snap.safe_t) for s in steps)
            # SUPPLY spends from Safe T (floor and reserve are checked on it); the pool is not modelled.
            and all(_same(s.from_wallet, snap.safe_t) for s in steps if s.action == Action.SUPPLY)
        )
    if i.ctx.request is None:
        return False
    r = i.request
    if (
        [s.seq for s in steps] != list(range(len(steps)))
        or actions not in _PLAN_SHAPES
        or len({s.step_id for s in steps}) != len(steps)
        or i.plan.request_id != r.request_id
    ):
        return False
    # Same choice as the module's pay(): the early option while it is open (ADR-019).
    early = r.early_amount > 0 and i.ctx.now <= r.early_pay_by
    by_action = {s.action: s for s in steps}
    pay, refill, withdraw = (by_action.get(a) for a in (Action.PAY, Action.REFILL, Action.WITHDRAW))
    if pay is None:
        return False
    return (
        pay.amount == (r.early_amount if early else r.amount)
        and _same(pay.from_wallet, r.paying_wallet)
        and _same(pay.to, r.payee)
        and (
            refill is None
            or (_same(refill.to, r.paying_wallet) and _same(refill.from_wallet, snap.safe_t))
        )
        and (withdraw is None or _same(withdraw.to, snap.safe_t))
    )


_PLAN_RULES: list[_Rule] = [("plan_shape", C.PLAN_MALFORMED, _plan_well_formed)]
_STEP_RULES: list[_Rule] = [("step_exists", C.PLAN_MALFORMED, lambda i: len(i.steps) == 1)]


def _run(rule: _Rule, inputs: _Inputs) -> Check:
    name, code, passes = rule
    try:
        ok = passes(inputs)
    except (LookupError, TypeError, ValueError):
        # Unparseable input (naive datetime, non-numeric amount, missing key) fails closed.
        ok, code = False, C.DATA_MISSING
    return Check(name=name, passed=ok, code=None if ok else code, expected=None, observed=None)


def _skip(rule: _Rule) -> Check:
    return Check(name=rule[0], passed=False, skipped=True, code=None, expected=None, observed=None)


def authorization_checks(
    plan: ExecutionPlan,
    ctx: ValidationContext,
    *,
    seq: int | None = None,
    erc1271: Erc1271Call | None = None,
) -> list[Check]:
    """Stage PLAN when ``seq`` is None, else PRE_STEP for the step with that ``seq``.

    Pass ``erc1271`` exactly when the approval signer has code (see ``verify_signature``).
    Every check runs; a failed gate skips the rest, and a missing approval skips its checks.
    """
    steps = list(plan.steps) if seq is None else [s for s in plan.steps if s.seq == seq]
    inputs = _Inputs(plan, steps, ctx, erc1271)

    # From the whole plan: a lone WITHDRAW step of a WITHDRAW -> REFILL -> PAY plan is not one.
    liquidity_plan = bool(plan.steps) and all(
        step.action in (Action.SUPPLY, Action.WITHDRAW) for step in plan.steps
    )
    gate_rules = list(_GATES)
    if liquidity_plan:
        gate_rules = [
            (name, code, lambda i: i.ctx.snapshot.mandate is not None)
            if name == "data_present"
            else (name, code, passes)
            for name, code, passes in gate_rules
        ]
    gates = [_run(rule, inputs) for rule in gate_rules]
    rest = _MANDATE_RULES if liquidity_plan else _REQUEST_RULES + _MANDATE_RULES + _APPROVAL_RULES
    if seq is not None:
        rest = rest + _STEP_RULES
    if any(s.action == Action.PAY for s in steps):
        rest = rest + _PAY_RULES
    if seq is None:
        rest = rest + _PLAN_RULES
    if not all(check.passed for check in gates):
        return gates + [_skip(rule) for rule in rest]
    return gates + [
        _skip(rule) if ctx.approval is None and rule in _APPROVAL_RULES else _run(rule, inputs)
        for rule in rest
    ]
