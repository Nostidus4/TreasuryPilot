"""Choose between the AI proposal and the deterministic plan (AGT-009, M09 section 8.2)."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal

from treasurypilot_core.domain import ApprovedRequest, PolicyView, Schedule, ScheduledItem, Snapshot
from treasurypilot_core.engine import schedule_in_order, score
from treasurypilot_core.engine.scoring import PlanScore
from treasurypilot_worker.agent.plan_proposer import PlanProposal, PlanProposalRejected
from treasurypilot_worker.recovery.retry import ReviewIntent

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanSelection:
    """`review` is set when the proposal was rejected; the caller persists it (AI_REJECTED)."""

    planner_source: Literal["AI", "DETERMINISTIC"]
    items: tuple[ScheduledItem, ...]
    chosen_reason: str
    deterministic_score: PlanScore
    ai_score: PlanScore | None = None
    review: ReviewIntent | None = None


def build_ai_plan(
    proposal: PlanProposal,
    requests: list[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
    today: date,
) -> tuple[ScheduledItem, ...]:
    """Concrete plan from the proposal's order and deferrals; every amount is the engine's.

    Raises `PlanProposalRejected` unless each eligible request is named exactly once.
    """

    eligible = {request.id for request in requests}
    named = [
        *proposal.request_order,
        *(d.request_id for d in proposal.deferrals),
        *proposal.exception_requests,
    ]
    if set(named) != eligible or len(named) != len(eligible):
        raise PlanProposalRejected("proposal does not cover every eligible request exactly once")
    # Deferrals follow the ordered requests; exception requests are left unpaid for review.
    priority = [*proposal.request_order, *(d.request_id for d in proposal.deferrals)]
    # `today` is the calendar date of snapshot.day, so a deferral date maps to an engine day.
    not_before = {
        d.request_id: snapshot.day + (d.until_day - today).days for d in proposal.deferrals
    }
    return schedule_in_order(priority, not_before, requests, snapshot, policy)


def select_plan(
    deterministic: Schedule,
    proposal: PlanProposal | PlanProposalRejected | None,
    requests: list[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
    today: date,
) -> PlanSelection:
    """AI plan only if it is valid and strictly better than the deterministic score; a tie keeps
    the deterministic plan. `None` means the AI path produced nothing (the caller handles outages)."""

    det_score = score(deterministic, requests, snapshot, policy)
    items = tuple(deterministic.items)

    def keep(
        reason: str, ai: PlanScore | None = None, review: ReviewIntent | None = None
    ) -> PlanSelection:
        return PlanSelection("DETERMINISTIC", items, reason, det_score, ai, review)

    if proposal is None:
        return keep("No AI proposal; deterministic plan used")
    try:
        if isinstance(proposal, PlanProposalRejected):
            raise proposal
        ai_items = build_ai_plan(proposal, requests, snapshot, policy, today)
    except PlanProposalRejected as exc:
        log.warning("AI plan rejected: %s", exc)
        review = ReviewIntent("AI_REJECTED", "AI_PLAN_REJECTED", ("AI_PLAN_REJECTED",))
        return keep(f"AI plan rejected: {exc}", review=review)

    ai_score = score(ai_items, requests, snapshot, policy)
    log.info("plan comparison: ai=%s deterministic=%s", ai_score, det_score)
    if ai_score[0] == 0 and ai_score < det_score:
        gain = det_score[2] - ai_score[2]  # score[2] is negated value
        reason = f"AI plan scored better: value +{gain}, score {ai_score} vs {det_score}"
        return PlanSelection("AI", ai_items, reason, det_score, ai_score)
    return keep(f"AI plan not better: score {ai_score} vs {det_score}", ai_score)
