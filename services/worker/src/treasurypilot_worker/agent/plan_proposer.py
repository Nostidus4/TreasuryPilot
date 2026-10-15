"""AI plan proposal (AGT-008): strict schema, trigger rule, reference check, EXPLAIN."""

import re
from collections.abc import Callable, Collection, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.config import AiTask
from treasurypilot_worker.agent.errors import AiError
from treasurypilot_worker.agent.prompts.plan import EXPLAIN_TEMPLATE, PLAN_TEMPLATE
from treasurypilot_worker.agent.types import AiResult, Tool

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class _Strict(BaseModel):
    # extra="forbid" is what keeps amounts out: the schema has no field for one.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Deferral(_Strict):
    request_id: str
    until_day: date
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")


class Rationale(_Strict):
    claim: str = Field(min_length=1, max_length=500)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class PlanProposal(_Strict):
    request_order: tuple[str, ...]
    deferrals: tuple[Deferral, ...] = ()
    exception_requests: tuple[str, ...] = ()
    rationale: tuple[Rationale, ...] = Field(max_length=20)


class PlanContext(_Strict):
    treasury_id: str
    eligible_request_ids: tuple[str, ...]


class PlanFact(_Strict):
    request_id: str
    pay_day: date
    amount: str  # base units, from the engine


class PlanFacts(_Strict):
    items: tuple[PlanFact, ...]


class Explanation(_Strict):
    text: str = Field(min_length=1, max_length=600)


class PlanProposalRejected(AiError):
    """The proposal named an id that is not an eligible request, or evidence that does not resolve."""


def needs_full_proposal(*, eligible_requests: int, terms_or_deferrals_matter: bool) -> bool:
    """M09-D6: a full proposal only when it can matter; else EXPLAIN the deterministic plan."""

    return eligible_requests >= 2 or terms_or_deferrals_matter


def check_references(
    proposal: PlanProposal,
    *,
    eligible_request_ids: Collection[str],
    evidence_exists: Callable[[str], bool],
) -> None:
    """Raise `PlanProposalRejected` unless every id resolves inside the organisation.

    `eligible_request_ids` must come from the org-scoped request list; `evidence_exists`
    from the org-scoped evidence lookup.
    """

    eligible = set(eligible_request_ids)
    named = [
        *proposal.request_order,
        *(d.request_id for d in proposal.deferrals),
        *proposal.exception_requests,
    ]
    unknown = sorted(set(named) - eligible)
    if unknown:
        raise PlanProposalRejected(f"unknown request ids: {unknown}")
    if len(set(proposal.request_order)) != len(proposal.request_order):
        raise PlanProposalRejected("request_order repeats a request id")
    for item in proposal.rationale:
        missing = [e for e in item.evidence_ids if not evidence_exists(e)]
        if missing:
            raise PlanProposalRejected(f"evidence ids do not resolve: {missing}")


def propose_plan(
    adapter: AiAdapter,
    *,
    org_id: str,
    treasury_id: str,
    eligible_request_ids: Sequence[str],
    evidence_exists: Callable[[str], bool],
    tools: Sequence[Tool[Any]],
) -> AiResult[PlanProposal]:
    """Run the PLAN task and check its references. Any `AiError` means: use the deterministic plan."""

    context = PlanContext(treasury_id=treasury_id, eligible_request_ids=tuple(eligible_request_ids))
    result = adapter.run(
        AiTask.PLAN,
        org_id=org_id,
        prompt=PLAN_TEMPLATE.render(context=context),
        output=PlanProposal,
        tools=tools,
    )
    check_references(
        result.output, eligible_request_ids=eligible_request_ids, evidence_exists=evidence_exists
    )
    return result


def explain_plan(adapter: AiAdapter, *, org_id: str, facts: PlanFacts) -> str | None:
    """Short rationale of a fixed plan on the cheap model, or None if it quotes a foreign number."""

    result = adapter.run(
        AiTask.EXPLAIN,
        org_id=org_id,
        prompt=EXPLAIN_TEMPLATE.render(plan=facts),
        output=Explanation,
    )
    text = result.output.text
    if _numbers(text) <= _numbers(facts.model_dump_json()):
        return text
    return None


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}
