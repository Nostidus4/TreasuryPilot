from datetime import date, datetime

import pytest

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiTask,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    fake_text,
)
from treasurypilot_worker.agent.plan_proposer import (
    PlanFact,
    PlanFacts,
    PlanProposal,
    PlanProposalRejected,
    explain_plan,
    needs_full_proposal,
    propose_plan,
)

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


def _propose(provider: FakeProvider, config: AiConfig, clock: FakeClock, now: datetime) -> object:
    return propose_plan(
        _adapter(provider, config, clock, now),
        org_id="org-1",
        treasury_id="t-1",
        eligible_request_ids=[A, B],
        evidence_exists=lambda e: e == "ev-1",
        tools=(),
    )


def _proposal(order: str = f'["{A}", "{B}"]', evidence: str = '["ev-1"]', extra: str = "") -> str:
    return (
        f'{{"request_order": {order}, "deferrals": [], "exception_requests": [], '
        f'"rationale": [{{"claim": "A is due first", "evidence_ids": {evidence}}}]{extra}}}'
    )


def test_valid_proposal_is_returned_from_the_plan_task(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text(_proposal())])
    result = _propose(provider, repo_config, clock, october)
    assert result.output.request_order == (A, B)  # type: ignore[attr-defined]
    assert provider.calls[0][0].model == "claude-opus-5-5"


def test_unknown_request_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text(_proposal(order=f'["{A}", "req-other-org"]'))])
    with pytest.raises(PlanProposalRejected, match="req-other-org"):
        _propose(provider, repo_config, clock, october)


def test_unresolved_evidence_is_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text(_proposal(evidence='["ev-1", "ev-9"]'))])
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
