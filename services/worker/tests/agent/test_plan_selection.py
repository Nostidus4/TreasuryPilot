import logging
from datetime import date

import pytest

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import schedule_edf, score
from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.agent.plan_proposer import (
    Deferral,
    PlanProposal,
    PlanProposalRejected,
    Rationale,
)
from treasurypilot_worker.agent.plan_selection import build_ai_plan, select_plan

TODAY = date(2026, 1, 1)


def _snapshot() -> Snapshot:
    wallet = WalletState(
        address="ops", balance=BaseUnits(2_000), buffer=BaseUnits(0), target=BaseUnits(0)
    )
    return Snapshot(
        day=0,
        source=WalletState(
            address="safe", balance=BaseUnits(0), buffer=BaseUnits(0), target=BaseUnits(0)
        ),
        operational={"ops": wallet},
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={"payee": 0},
        safe_usdc=BaseUnits(0),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


POLICY = PolicyView(
    pay=Limits(per_request=BaseUnits(10_000), daily=BaseUnits(700)),
    refill=Limits(per_request=BaseUnits(10_000), daily=BaseUnits(10_000)),
    cooling_seconds=0,
)


def _req(request_id: str, *, discount: bool = False, seq: int = 0, due: int = 5) -> ApprovedRequest:
    extra = {"discount_bps": 1_000, "discount_deadline_day": 0} if discount else {}
    return ApprovedRequest(
        id=request_id,
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(600),
        approved_seq=seq,
        terms=PaymentTerms(net_due_day=due, **extra),
        **({"early_amount": BaseUnits(540), "early_pay_by": 0} if discount else {}),
    )


def _proposal(order: tuple[str, ...], **kw: object) -> PlanProposal:
    rationale = (Rationale(claim="c", evidence_ids=("e",)),)
    return PlanProposal(request_order=order, rationale=rationale, **kw)  # type: ignore[arg-type]


# Daily cap 700 pays one 600 request a day. "a" is due day 1, "b" has a day-0 discount.
# EDF pays a then b (no discount); paying b first keeps a on time and captures the discount.
REQS = [_req("a", due=1), _req("b", discount=True, seq=1, due=5)]


def test_worse_ai_plan_is_not_chosen_and_comparison_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    snap = _snapshot()
    det = schedule_edf(REQS, snap, POLICY)
    # Leaving a unpaid (exception) misses its deadline: worse than the deterministic plan.
    with caplog.at_level(logging.INFO):
        sel = select_plan(
            det, _proposal(("b",), exception_requests=("a",)), REQS, snap, POLICY, TODAY
        )
    assert sel.planner_source == "DETERMINISTIC"
    assert sel.items == tuple(det.items)
    assert sel.ai_score is not None and sel.ai_score > sel.deterministic_score
    assert "plan comparison" in caplog.text
    assert sel.review is None


def test_tie_keeps_deterministic() -> None:
    snap = _snapshot()
    det = schedule_edf(REQS, snap, POLICY)
    sel = select_plan(det, _proposal(("a", "b")), REQS, snap, POLICY, TODAY)
    assert sel.ai_score == sel.deterministic_score
    assert sel.planner_source == "DETERMINISTIC"


def test_better_ai_plan_is_chosen_with_engine_amounts() -> None:
    snap = _snapshot()
    det = schedule_edf(REQS, snap, POLICY)
    ai = _proposal(("b", "a"))
    sel = select_plan(det, ai, REQS, snap, POLICY, TODAY)
    assert sel.planner_source == "AI"
    assert sel.items == build_ai_plan(ai, REQS, snap, POLICY, TODAY)
    assert sel.ai_score == score(sel.items, REQS, snap, POLICY) < sel.deterministic_score
    assert "value +" in sel.chosen_reason


def test_deferral_delays_payment_to_engine_day() -> None:
    snap = _snapshot()
    ai = _proposal(
        ("a",),
        deferrals=(Deferral(request_id="b", until_day=date(2026, 1, 3), reason_code="WAIT"),),
    )
    days = {i.request_id: i.day for i in build_ai_plan(ai, REQS, snap, POLICY, TODAY)}
    assert days == {"a": 0, "b": 2}


@pytest.mark.parametrize(
    "proposal",
    [
        _proposal(("a",)),  # b not covered
        _proposal(("a", "b"), exception_requests=("b",)),  # b twice
        PlanProposalRejected("unknown request ids: ['x']"),  # out-of-mandate, from the proposer
    ],
)
def test_invalid_proposal_creates_review_and_keeps_deterministic(
    proposal: PlanProposal | PlanProposalRejected,
) -> None:
    snap = _snapshot()
    det = schedule_edf(REQS, snap, POLICY)
    sel = select_plan(det, proposal, REQS, snap, POLICY, TODAY)
    assert sel.planner_source == "DETERMINISTIC"
    assert sel.items == tuple(det.items)
    assert sel.review is not None
    assert (sel.review.kind, sel.review.primary_code) == ("AI_REJECTED", "AI_PLAN_REJECTED")
    assert sel.ai_score is None


def test_no_proposal_is_deterministic_without_review() -> None:
    snap = _snapshot()
    sel = select_plan(schedule_edf(REQS, snap, POLICY), None, REQS, snap, POLICY, TODAY)
    assert (sel.planner_source, sel.review) == ("DETERMINISTIC", None)
