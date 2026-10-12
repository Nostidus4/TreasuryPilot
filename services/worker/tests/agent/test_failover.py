from datetime import datetime

import pytest
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiTask,
    AiTimeout,
    AiUnavailable,
    FailoverProvider,
    FakeClock,
    FakeProvider,
    InMemoryBudgetLedger,
    Message,
    PromptTemplate,
    ProviderRequest,
    ProviderResponse,
    TextBlock,
    Tool,
    ToolCall,
    fake_text,
    fake_tool_use,
)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    treasury_id: str


PROMPT = PromptTemplate(version="failover.test.v1", system="You help.", instructions="Go.").render()
REQUEST = ProviderRequest(
    model="claude-sonnet-5-5",
    system="You help.",
    messages=(Message("user", (TextBlock("Go."),)),),
    tools=(),
    output_schema=Answer.model_json_schema(),
    max_output_tokens=100,
)


def _disabled(count: int) -> list[AiUnavailable]:
    return [AiUnavailable("Anthropic returned 401: disabled", retryable=False)] * count


def test_primary_unavailable_moves_the_turn_to_the_secondary(clock: FakeClock) -> None:
    primary = FakeProvider(_disabled(1))
    secondary = FakeProvider([fake_text('{"answer": "ok"}')])

    response = FailoverProvider([primary, secondary], clock=clock).complete(REQUEST, timeout_s=10)

    assert response.text == '{"answer": "ok"}'
    assert primary.calls[0][0] == secondary.calls[0][0] == REQUEST


def test_healthy_primary_never_touches_the_secondary(clock: FakeClock) -> None:
    secondary = FakeProvider([])

    FailoverProvider([FakeProvider([fake_text("{}")]), secondary], clock=clock).complete(
        REQUEST, timeout_s=10
    )

    assert secondary.calls == []


def test_secondary_gets_only_the_time_the_primary_left(clock: FakeClock) -> None:
    def slow_failure(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(4)
        raise AiUnavailable("Anthropic connection failed", retryable=True)

    secondary = FakeProvider([fake_text("{}")])

    FailoverProvider([FakeProvider([slow_failure]), secondary], clock=clock).complete(
        REQUEST, timeout_s=10
    )

    assert secondary.calls[0][1] == pytest.approx(6)


def test_last_provider_error_is_raised_with_its_retry_flag(clock: FakeClock) -> None:
    secondary_down = AiUnavailable("Bedrock returned 503", retryable=True)

    with pytest.raises(AiUnavailable) as raised:
        FailoverProvider(
            [FakeProvider(_disabled(1)), FakeProvider([secondary_down])], clock=clock
        ).complete(REQUEST, timeout_s=10)

    assert raised.value is secondary_down


def test_retryable_primary_failure_keeps_the_chain_retryable(clock: FakeClock) -> None:
    primary_overloaded = AiUnavailable("anthropic returned 529", retryable=True)
    secondary_misconfigured = AiUnavailable("bedrock returned 404", retryable=False)

    with pytest.raises(AiUnavailable) as raised:
        FailoverProvider(
            [FakeProvider([primary_overloaded]), FakeProvider([secondary_misconfigured])],
            clock=clock,
        ).complete(REQUEST, timeout_s=10)

    assert raised.value.retryable is True


def test_spent_deadline_does_not_try_the_secondary(clock: FakeClock) -> None:
    def exhausting(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(timeout_s)
        raise AiUnavailable("Anthropic returned 500", retryable=True)

    secondary = FakeProvider([])

    with pytest.raises(AiTimeout):
        FailoverProvider([FakeProvider([exhausting]), secondary], clock=clock).complete(
            REQUEST, timeout_s=10
        )
    assert secondary.calls == []


def _adapter(provider: FailoverProvider, config: AiConfig, clock: FakeClock, now: datetime):
    return AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: now,
    )


def test_extraction_works_through_the_secondary_with_the_primary_disabled(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FailoverProvider(
        [FakeProvider(_disabled(1)), FakeProvider([fake_text('{"answer": "INV-7"}')])],
        clock=clock,
    )

    result = _adapter(provider, repo_config, clock, october).run(
        AiTask.EXTRACT, org_id="org-1", prompt=PROMPT, output=Answer
    )

    assert result.output.answer == "INV-7"


def test_planning_tool_loop_works_through_the_secondary_with_the_primary_disabled(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    looked_up: list[str] = []
    tool = Tool(
        name="get_snapshot",
        description="Read the treasury snapshot.",
        input_model=SnapshotInput,
        handler=lambda args: looked_up.append(args.treasury_id) or {"balance": "6000"},
    )
    secondary = FakeProvider(
        [
            fake_tool_use(ToolCall("call-1", "get_snapshot", {"treasury_id": "t-1"})),
            fake_text('{"answer": "pay invoice A first"}'),
        ]
    )
    provider = FailoverProvider([FakeProvider(_disabled(2)), secondary], clock=clock)

    result = _adapter(provider, repo_config, clock, october).run(
        AiTask.PLAN, org_id="org-1", prompt=PROMPT, output=Answer, tools=[tool]
    )

    assert result.output.answer == "pay invoice A first"
    assert looked_up == ["t-1"]
    assert len(secondary.calls) == 2
