from datetime import date, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiTask,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    fake_text,
    fake_tool_use,
)
from treasurypilot_worker.agent.errors import AiSchemaError, AiToolLimitExceeded, ToolError
from treasurypilot_worker.agent.plan_proposer import (
    PlanFact,
    PlanFacts,
    PlanProposal,
    PlanProposalRejected,
    check_references,
    explain_plan,
    needs_full_proposal,
    propose_plan,
)
from treasurypilot_worker.agent.types import AiResult, ProviderResponse, Tool, ToolCall

A, B = "req-a", "req-b"


def _adapter(
    provider: FakeProvider, config: AiConfig, clock: FakeClock, now: datetime
) -> AiAdapter:
    return AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: now,
    )


class _SnapIn(BaseModel):
    treasury_id: str


class _EvIn(BaseModel):
    evidence_id: str


def _tools(known: set[str]) -> tuple[Tool[Any], ...]:
    """Org-bound stand-ins: get_evidence refuses ids outside `known` (another org's)."""

    def evidence(args: _EvIn) -> dict[str, object]:
        if args.evidence_id not in known:
            raise ToolError("REFUSED: evidence not found in this organisation")
        return {"id": args.evidence_id}

    def snapshot(args: _SnapIn) -> dict[str, object]:
        return {"snapshot_id": "snap-1"}

    return (
        Tool("get_evidence", "Read.", _EvIn, evidence),
        Tool("get_snapshot", "Read.", _SnapIn, snapshot),
    )


def _reads(*ids: str) -> list[ProviderResponse]:
    return [
        fake_tool_use(
            *(ToolCall(f"t{i}", "get_evidence", {"evidence_id": e}) for i, e in enumerate(ids))
        )
    ]


def _propose(
    provider: FakeProvider, config: AiConfig, clock: FakeClock, now: datetime
) -> AiResult[PlanProposal]:
    return propose_plan(
        _adapter(provider, config, clock, now),
        org_id="org-1",
        treasury_id="t-1",
        eligible_request_ids=[A, B],
        tools=_tools({"ev-1"}),
    )


def _proposal(order: str = f'["{A}", "{B}"]', evidence: str = '["ev-1"]', extra: str = "") -> str:
    return (
        f'{{"request_order": {order}, "deferrals": [], "exception_requests": [], '
        f'"rationale": [{{"claim": "A is due first", "evidence_ids": {evidence}}}]{extra}}}'
    )


def test_valid_proposal_is_returned_from_the_plan_task(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([*_reads("ev-1"), fake_text(_proposal())])
    result = _propose(provider, repo_config, clock, october)
    assert result.output.request_order == (A, B)
    assert provider.calls[-1][0].model == "claude-opus-5-5"


def test_unknown_request_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider(
        [*_reads("ev-1"), fake_text(_proposal(order=f'["{A}", "req-other-org"]'))]
    )
    with pytest.raises(PlanProposalRejected, match="req-other-org"):
        _propose(provider, repo_config, clock, october)


def test_unresolved_evidence_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([*_reads("ev-1"), fake_text(_proposal(evidence='["ev-1", "ev-9"]'))])
    with pytest.raises(PlanProposalRejected, match="ev-9"):
        _propose(provider, repo_config, clock, october)


def test_amounts_are_not_accepted_from_the_model() -> None:
    with pytest.raises(ValueError, match="amount"):
        PlanProposal.model_validate_json(_proposal(extra=', "amount": "5000"'))


def test_trigger_rule() -> None:
    assert not needs_full_proposal(eligible_requests=1, terms_or_deferrals_matter=False)
    assert needs_full_proposal(eligible_requests=2, terms_or_deferrals_matter=False)
    assert needs_full_proposal(eligible_requests=1, terms_or_deferrals_matter=True)


FACTS = PlanFacts(items=(PlanFact(request_id=A, pay_day=date(2026, 10, 15), amount="3000"),))


def test_single_request_gets_explain_text_and_no_plan_call(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text('{"text": "Pays 3,000 on 2026-10-15, its due day."}')])
    text = explain_plan(
        _adapter(provider, repo_config, clock, october), org_id="org-1", facts=FACTS
    )
    assert text == "Pays 3,000 on 2026-10-15, its due day."
    assert [c[0].model for c in provider.calls] == ["claude-haiku-5-5"]
    assert repo_config.tasks[AiTask.EXPLAIN].model == "claude-haiku-5-5"


def test_explain_with_a_number_not_in_the_plan_is_discarded(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text('{"text": "Pays 3,500 on 2026-10-15."}')])
    assert (
        explain_plan(_adapter(provider, repo_config, clock, october), org_id="org-1", facts=FACTS)
        is None
    )


def test_other_orgs_evidence_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    # ev-foreign exists in another org: the org-bound tool refuses it, so it is never citable.
    provider = FakeProvider(
        [*_reads("ev-foreign"), fake_text(_proposal(evidence='["ev-foreign"]'))]
    )
    with pytest.raises(PlanProposalRejected, match="ev-foreign"):
        _propose(provider, repo_config, clock, october)


def test_evidence_never_read_by_a_tool_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text(_proposal())])
    with pytest.raises(PlanProposalRejected, match="ev-1"):
        _propose(provider, repo_config, clock, october)


def test_snapshot_id_is_citable(repo_config: AiConfig, clock: FakeClock, october: datetime) -> None:
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "t-1"})),
            fake_text(_proposal(evidence='["snap-1"]')),
        ]
    )
    assert _propose(provider, repo_config, clock, october).output.request_order == (A, B)


def test_plan_call_over_the_tool_limit_raises(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    limit = repo_config.tasks[AiTask.PLAN].max_tool_calls
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall(f"t{i}", "get_snapshot", {"treasury_id": "t-1"}))
            for i in range(limit + 1)
        ]
    )
    with pytest.raises(AiToolLimitExceeded):
        _propose(provider, repo_config, clock, october)


def test_reply_with_an_amount_is_rejected_end_to_end(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    bad = fake_text(_proposal(extra=', "amount": "5000"'))
    with pytest.raises(AiSchemaError, match="amount"):
        _propose(FakeProvider([bad, bad]), repo_config, clock, october)


def _defer(rid: str) -> dict[str, str]:
    return {"request_id": rid, "until_day": "2026-10-20", "reason_code": "DISCOUNT"}


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"exception_requests": ["req-x"]}, "req-x"),
        ({"deferrals": [_defer("req-x")]}, "req-x"),
        ({"request_order": [A, B], "deferrals": [_defer(B)]}, "more than one"),
        ({"request_order": [A], "deferrals": [_defer(B), _defer(B)]}, "repeated"),
        ({"request_order": [A], "exception_requests": [B, B]}, "repeated"),
    ],
)
def test_reference_check_rejects_bad_lists(fields: dict[str, Any], match: str) -> None:
    data = {"request_order": [A], "rationale": [{"claim": "c", "evidence_ids": ["ev-1"]}], **fields}
    with pytest.raises(PlanProposalRejected, match=match):
        check_references(
            PlanProposal.model_validate(data),
            eligible_request_ids=[A, B],
            known_evidence_ids={"ev-1"},
        )


def test_empty_claim_is_rejected() -> None:
    with pytest.raises(ValueError, match="claim"):
        PlanProposal.model_validate_json(_proposal().replace("A is due first", ""))


def test_explain_schema_failure_retries_once(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider(
        [fake_text("not json"), fake_text('{"text": "Pays 3,000 on 2026-10-15."}')]
    )
    text = explain_plan(
        _adapter(provider, repo_config, clock, october), org_id="org-1", facts=FACTS
    )
    assert text == "Pays 3,000 on 2026-10-15."
    assert len(provider.calls) == 2


def test_explain_ignores_digits_of_request_ids(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    facts = PlanFacts(
        items=(PlanFact(request_id="req-77", pay_day=date(2026, 10, 15), amount="3,000"),)
    )
    provider = FakeProvider([fake_text('{"text": "Request 77 pays 3,000."}')])
    assert (
        explain_plan(_adapter(provider, repo_config, clock, october), org_id="org-1", facts=facts)
        is None
    )
