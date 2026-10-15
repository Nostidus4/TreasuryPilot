from datetime import datetime

import pytest

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    fake_text,
)
from treasurypilot_worker.agent.call_log import ValidationResult
from treasurypilot_worker.agent.exception_draft import (
    DraftOutcome,
    ExceptionFacts,
    _matches_engine,
    draft_exception,
    template_draft,
)

FACTS = ExceptionFacts(
    amount="12,500", cap="10,000", excess="2,500", daily_used="4,000", daily_remaining_after="7,500"
)


def _draft(
    repo_config: AiConfig,
    clock: FakeClock,
    now: datetime,
    *texts: str,
    log: InMemoryAiCallLog | None = None,
) -> DraftOutcome:
    adapter = AiAdapter(
        provider=FakeProvider([fake_text(t) for t in texts]),
        config=repo_config,
        ledger=InMemoryBudgetLedger(),
        call_log=log or InMemoryAiCallLog(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: now,
    )
    return draft_exception(adapter, org_id="org-1", facts=FACTS)


def _json(summary: str, evidence: str = '["amount"]') -> str:
    return (
        f'{{"summary": "{summary}", "reasons": [{{"text": "Over the cap by 2,500.", '
        f'"evidence_ids": {evidence}}}], "alternatives": ["Split into parts."]}}'
    )


def test_draft_with_engine_numbers_is_kept(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    outcome = _draft(repo_config, clock, october, _json("Pay 12,500 against a 10,000 cap."))
    assert outcome.source == "AI" and outcome.ai_call_id is not None
    assert outcome.draft.summary == "Pay 12,500 against a 10,000 cap."


def test_draft_with_a_number_that_differs_from_the_engine_uses_the_template(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    outcome = _draft(
        repo_config, clock, october, _json("Pay 12,000 against a 10,000 cap."), log=log
    )
    assert outcome.source == "TEMPLATE" and outcome.ai_call_id is None
    assert [e.validation_result for e in log.entries] == [ValidationResult.POSTCHECK_FAILED]
    assert outcome.draft == template_draft(FACTS)


def test_draft_citing_an_unknown_fact_uses_the_template(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    log = InMemoryAiCallLog()
    outcome = _draft(
        repo_config, clock, october, _json("Pay 12,500.", evidence='["made_up"]'), log=log
    )
    assert outcome.source == "TEMPLATE"
    assert [e.validation_result for e in log.entries] == [ValidationResult.POSTCHECK_FAILED]


def test_ai_failure_uses_the_template(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    outcome = _draft(
        repo_config, clock, october, "not json", "still not json"
    )  # schema error after one retry
    assert outcome.source == "TEMPLATE"


def test_template_only_contains_engine_numbers() -> None:
    assert _matches_engine(template_draft(FACTS), FACTS)


@pytest.mark.parametrize(
    ("summary", "ok"),
    [
        ("Pay 12,500 against 10,000.", True),
        ("Pay 12500 against 10000.", True),
        ("Pay -12,500 against 10,000.", False),  # sign flip
        ("Pay 1,2500 against 10,000.", False),  # misplaced separator
        ("Pay 12,500.00 against 10,000.", False),  # different spelling is not the engine's number
        ("Pay 25% over the cap.", False),  # percentages rejected deliberately
    ],
)
def test_number_check_is_exact_and_signed(summary: str, ok: bool) -> None:
    draft = template_draft(FACTS).model_copy(update={"summary": summary})
    assert _matches_engine(draft, FACTS) is ok
