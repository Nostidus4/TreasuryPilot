"""AI plan proposal (AGT-008): strict schema, trigger rule, reference check, EXPLAIN."""

import json
import re
from collections.abc import Collection, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.config import AiTask
from treasurypilot_worker.agent.errors import AiError
from treasurypilot_worker.agent.prompts.plan import EXPLAIN_TEMPLATE, PLAN_TEMPLATE
from treasurypilot_worker.agent.types import AiResult, Tool, ToolCallRecord

_EVIDENCE_TOOLS = frozenset({"get_snapshot", "list_requests", "get_policy_summary", "get_evidence"})
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
    amount: str  # display amount as the reviewer sees it (e.g. "3,000"), from the engine


class PlanFacts(_Strict):
    items: tuple[PlanFact, ...]


class Explanation(_Strict):
    text: str = Field(min_length=1, max_length=600)


class PlanProposalRejected(AiError):
    """The proposal named an id that is not an eligible request, or evidence that does not resolve."""


def needs_full_proposal(*, eligible_requests: int, terms_or_deferrals_matter: bool) -> bool:
    """M09-D6: a full proposal only when it can matter; else EXPLAIN the deterministic plan."""

    return eligible_requests >= 2 or terms_or_deferrals_matter


def evidence_from_tool_calls(tool_calls: Sequence[ToolCallRecord]) -> set[str]:
    """Evidence ids this run actually read: org-bound tools succeeded on them, nothing else counts.

    Citable: the `evidence_id` of a successful get_snapshot, get_policy_summary or get_evidence
    result and of each request row of a successful list_requests (`request:<id>`), plus the bare
    id of such a row. Failed, truncated or unparseable results contribute nothing.
    """

    seen: set[str] = set()
    for call in tool_calls:
        if call.is_error or call.truncated or call.name not in _EVIDENCE_TOOLS:
            continue
        try:
            body = json.loads(call.result)
        except ValueError:
            continue  # odd output: its ids are simply not citable
        if not isinstance(body, dict):
            continue
        _add(seen, body.get("evidence_id"))
        if call.name == "list_requests":
            rows = body.get("requests")
            for row in rows if isinstance(rows, list) else ():
                if isinstance(row, dict):
                    _add(seen, row.get("evidence_id"))
                    _add(seen, row.get("id"))
    return seen


def _add(seen: set[str], value: object) -> None:
    if isinstance(value, str) and value:
        seen.add(value)


def check_references(
    proposal: PlanProposal,
    *,
    eligible_request_ids: Collection[str],
    known_evidence_ids: Collection[str],
) -> None:
    """Raise `PlanProposalRejected` unless every id resolves inside the organisation.

    `eligible_request_ids` must come from the org-scoped request list; `known_evidence_ids`
    from `evidence_from_tool_calls` (org-bound tools). Whether every eligible request is
    covered is AGT-009's call, not checked here.
    """

    eligible = set(eligible_request_ids)
    deferred = [d.request_id for d in proposal.deferrals]
    groups = (list(proposal.request_order), deferred, list(proposal.exception_requests))
    for group in groups:
        if len(set(group)) != len(group):
            raise PlanProposalRejected("a request id is repeated within one list")
    named = [i for g in groups for i in g]
    unknown = sorted(set(named) - eligible)
    if unknown:
        raise PlanProposalRejected(f"unknown request ids: {unknown}")
    if len(set(named)) != len(named):
        raise PlanProposalRejected("a request id appears in more than one list")
    known = set(known_evidence_ids)
    for item in proposal.rationale:
        missing = [e for e in item.evidence_ids if e not in known]
        if missing:
            raise PlanProposalRejected(f"evidence ids do not resolve: {missing}")


def propose_plan(
    adapter: AiAdapter,
    *,
    org_id: str,
    treasury_id: str,
    eligible_request_ids: Sequence[str],
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
        result.output,
        eligible_request_ids=eligible_request_ids,
        known_evidence_ids=evidence_from_tool_calls(result.tool_calls),
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
    allowed = {n for f in facts.items for n in _numbers(f.amount) | _numbers(f.pay_day.isoformat())}
    if _numbers(text) <= allowed:
        return text
    return None


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}
