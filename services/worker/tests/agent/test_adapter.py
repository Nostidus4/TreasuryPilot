from datetime import datetime

import pytest
from prometheus_client import REGISTRY
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiBudgetExceeded,
    AiConfig,
    AiInputRejected,
    AiSchemaError,
    AiTask,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    PromptTemplate,
    ProviderRequest,
    ProviderResponse,
    SecretScanner,
    Slot,
    StopReason,
    TextBlock,
    Tool,
    ToolCall,
    ToolResult,
    Usage,
    fake_text,
    fake_tool_use,
)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    treasury_id: str


EXPLAIN_PROMPT = PromptTemplate(
    version="explain.test.v1",
    system="You explain treasury plans.",
    instructions="Why this plan?",
).render()


def _snapshot_tool(calls: list[str]) -> Tool[SnapshotInput]:
    def handler(args: SnapshotInput) -> dict[str, object]:
        calls.append(args.treasury_id)
        return {"treasury_id": args.treasury_id, "balance": "6000"}

    return Tool(
        name="get_snapshot",
        description="Read the treasury snapshot.",
        input_model=SnapshotInput,
        handler=handler,
    )


def _adapter(
    provider: FakeProvider,
    config: AiConfig,
    clock: FakeClock,
    now: datetime,
    ledger: InMemoryBudgetLedger | None = None,
) -> AiAdapter:
    return AiAdapter(
        provider=provider,
        config=config,
        ledger=ledger or InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: now,
    )


def _run(adapter: AiAdapter, task: AiTask = AiTask.EXPLAIN, **kwargs: object) -> object:
    return adapter.run(
        task,
        org_id="org-1",
        prompt=EXPLAIN_PROMPT,
        output=Answer,
        **kwargs,  # type: ignore[arg-type]
    )


def test_routes_task_to_configured_model_and_returns_validated_output(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text('{"answer": "Pay INV-7 first."}', Usage(120, 30))])
    ledger = InMemoryBudgetLedger()

    result = _adapter(provider, repo_config, clock, october, ledger).run(
        AiTask.EXPLAIN,
        org_id="org-1",
        prompt=EXPLAIN_PROMPT,
        output=Answer,
    )

    assert result.output == Answer(answer="Pay INV-7 first.")
    assert result.model == "claude-haiku-5-5"
    assert result.prompt_version == "explain.test.v1+policy.1"
    assert result.usage == Usage(120, 30)
    request, timeout_s = provider.calls[0]
    assert request.model == "claude-haiku-5-5"
    assert request.system == EXPLAIN_PROMPT.system
    assert request.messages == EXPLAIN_PROMPT.messages
    assert request.max_output_tokens == 300
    assert request.output_schema == Answer.model_json_schema()
    assert request.tools == ()
    assert timeout_s == pytest.approx(10.0)
    # 120 * 0.10 + 30 * 0.50 USD/MTok = 12 + 15 = 27 micros
    assert result.cost_usd_micros == 27
    assert ledger.spent("org-1", "2026-10") == 27


def test_cost_and_latency_reach_the_prometheus_series(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    def answer(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(2)
        return fake_text('{"answer": "ok"}', Usage(120, 30))

    labels = {"task": AiTask.EXPLAIN.value}
    cost_before = REGISTRY.get_sample_value("tp_llm_cost_usd_total", labels) or 0
    latency_before = REGISTRY.get_sample_value("tp_llm_latency_seconds_sum", labels) or 0

    _run(_adapter(FakeProvider([answer]), repo_config, clock, october))

    cost = REGISTRY.get_sample_value("tp_llm_cost_usd_total", labels)
    latency = REGISTRY.get_sample_value("tp_llm_latency_seconds_sum", labels)
    assert cost == pytest.approx(cost_before + 27 / 1_000_000)
    assert latency == pytest.approx(latency_before + 2)


def test_timeout_raises_ai_timeout_within_configured_limit(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    def slow(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(timeout_s + 0.001)
        raise AiTimeout("provider timed out")

    started = clock()
    with pytest.raises(AiTimeout):
        _run(_adapter(FakeProvider([slow]), repo_config, clock, october))

    assert clock() - started <= repo_config.tasks[AiTask.EXPLAIN].timeout_s + 0.01


def test_late_response_past_deadline_is_discarded_but_billed(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    def late(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(timeout_s + 1)
        return fake_text('{"answer": "too late"}', Usage(100, 10))

    ledger = InMemoryBudgetLedger()
    with pytest.raises(AiTimeout):
        _run(_adapter(FakeProvider([late]), repo_config, clock, october, ledger))

    assert ledger.spent("org-1", "2026-10") > 0


def test_deadline_spans_the_whole_tool_loop(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    plan_timeout = repo_config.tasks[AiTask.PLAN].timeout_s

    def first(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(plan_timeout * 0.75)
        return fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"}))

    provider = FakeProvider([first, fake_text('{"answer": "ok"}')])
    _run(
        _adapter(provider, repo_config, clock, october),
        AiTask.PLAN,
        tools=[_snapshot_tool([])],
    )

    assert provider.calls[0][1] == pytest.approx(plan_timeout)
    assert provider.calls[1][1] == pytest.approx(plan_timeout * 0.25)


def test_schema_failure_retries_once_with_the_validation_error(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text('{"answr": "typo"}'), fake_text('{"answer": "fixed"}')])

    result = _run(_adapter(provider, repo_config, clock, october))

    assert result.output == Answer(answer="fixed")  # type: ignore[attr-defined]
    assert result.schema_retries == 1  # type: ignore[attr-defined]
    retry_request = provider.calls[1][0]
    assistant, correction = retry_request.messages[-2:]
    assert assistant.role == "assistant"
    assert assistant.content == (TextBlock('{"answr": "typo"}'),)
    assert correction.role == "user"
    assert "answer" in correction.content[0].text  # type: ignore[union-attr]
    assert "failed validation" in correction.content[0].text  # type: ignore[union-attr]


def test_second_schema_failure_raises_ai_schema_error(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([fake_text("not json"), fake_text('{"answer": 3}')])

    with pytest.raises(AiSchemaError):
        _run(_adapter(provider, repo_config, clock, october))

    assert len(provider.calls) == 2


@pytest.mark.parametrize("stop_reason", [StopReason.MAX_TOKENS, StopReason.REFUSAL])
def test_truncated_or_refused_output_raises_schema_error_without_retry(
    repo_config: AiConfig, clock: FakeClock, october: datetime, stop_reason: StopReason
) -> None:
    response = ProviderResponse(stop_reason=stop_reason, text='{"ans', usage=Usage(10, 10))
    provider = FakeProvider([response])

    with pytest.raises(AiSchemaError, match=stop_reason.value):
        _run(_adapter(provider, repo_config, clock, october))

    assert len(provider.calls) == 1


def test_budget_exhausted_blocks_before_calling_provider(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    ledger = InMemoryBudgetLedger()
    ledger.record("org-1", "2026-10", repo_config.monthly_budget_usd_micros)
    provider = FakeProvider([])

    with pytest.raises(AiBudgetExceeded):
        _run(_adapter(provider, repo_config, clock, october, ledger))

    assert provider.calls == []


def test_budget_below_limit_allows_a_call_that_overshoots(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    ledger = InMemoryBudgetLedger()
    ledger.record("org-1", "2026-10", repo_config.monthly_budget_usd_micros - 1)
    provider = FakeProvider([fake_text('{"answer": "ok"}', Usage(1_000, 1_000))])

    _run(_adapter(provider, repo_config, clock, october, ledger))

    assert ledger.spent("org-1", "2026-10") > repo_config.monthly_budget_usd_micros


def test_tool_loop_executes_tools_and_feeds_results_back(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    seen: list[str] = []
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"})),
            fake_text('{"answer": "Safe holds 6000."}'),
        ]
    )

    result = _run(
        _adapter(provider, repo_config, clock, october),
        AiTask.PLAN,
        tools=[_snapshot_tool(seen)],
    )

    assert seen == ["tr-1"]
    first_request, _ = provider.calls[0]
    assert [t.name for t in first_request.tools] == ["get_snapshot"]
    assert first_request.tools[0].input_schema == SnapshotInput.model_json_schema()
    follow_up = provider.calls[1][0].messages
    assert follow_up[-2].content == (ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"}),)
    assert follow_up[-1].content == (
        ToolResult("t1", '{"treasury_id": "tr-1", "balance": "6000"}', is_error=False),
    )
    assert [c.name for c in result.tool_calls] == ["get_snapshot"]  # type: ignore[attr-defined]


def test_invalid_or_unknown_tool_calls_return_error_results(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider(
        [
            fake_tool_use(
                ToolCall("t1", "get_snapshot", {"treasury": "tr-1"}),
                ToolCall("t2", "transfer_funds", {}),
            ),
            fake_text('{"answer": "ok"}'),
        ]
    )

    _run(
        _adapter(provider, repo_config, clock, october),
        AiTask.PLAN,
        tools=[_snapshot_tool([])],
    )

    results = provider.calls[1][0].messages[-1].content
    assert all(isinstance(r, ToolResult) and r.is_error for r in results)
    assert "transfer_funds" in results[1].content  # type: ignore[union-attr]


def test_exceeding_tool_call_budget_raises(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    limit = repo_config.tasks[AiTask.COPILOT].max_tool_calls
    calls = [
        fake_tool_use(ToolCall(f"t{i}", "get_snapshot", {"treasury_id": "tr-1"}))
        for i in range(limit + 1)
    ]
    seen: list[str] = []

    with pytest.raises(AiToolLimitExceeded):
        _run(
            _adapter(FakeProvider(calls), repo_config, clock, october),
            AiTask.COPILOT,
            tools=[_snapshot_tool(seen)],
        )

    assert len(seen) == limit


def test_oversized_tool_result_is_truncated(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    limit = repo_config.tasks[AiTask.PLAN].tool_result_max_bytes

    def handler(args: SnapshotInput) -> dict[str, object]:
        return {"blob": "x" * (limit * 2)}

    tool = Tool("get_snapshot", "Read.", SnapshotInput, handler)
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"})),
            fake_text('{"answer": "ok"}'),
        ]
    )

    _run(_adapter(provider, repo_config, clock, october), AiTask.PLAN, tools=[tool])

    result = provider.calls[1][0].messages[-1].content[0]
    assert isinstance(result, ToolResult)
    assert len(result.content.encode()) < limit + 200
    assert "truncated" in result.content


def test_tools_on_a_task_without_tool_budget_are_rejected(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    with pytest.raises(ValueError, match="EXPLAIN"):
        _run(
            _adapter(FakeProvider([]), repo_config, clock, october),
            tools=[_snapshot_tool([])],
        )


def test_retryable_unavailability_is_retried_within_the_deadline(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider(
        [
            AiUnavailable("overloaded", retryable=True),
            AiUnavailable("overloaded", retryable=True),
            fake_text('{"answer": "ok"}'),
        ]
    )

    result = _run(_adapter(provider, repo_config, clock, october))

    assert result.output == Answer(answer="ok")  # type: ignore[attr-defined]
    assert len(clock.sleeps) == 2
    assert provider.calls[2][1] < provider.calls[0][1]


def test_unavailability_after_retries_raises(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([AiUnavailable("down", retryable=True)] * 3)

    with pytest.raises(AiUnavailable):
        _run(_adapter(provider, repo_config, clock, october))

    assert len(provider.calls) == 3


def test_non_retryable_unavailability_is_not_retried(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    provider = FakeProvider([AiUnavailable("bad request", retryable=False)])

    with pytest.raises(AiUnavailable):
        _run(_adapter(provider, repo_config, clock, october))

    assert len(provider.calls) == 1


class Note(BaseModel):
    note: str


def test_secret_in_prompt_is_rejected_before_any_provider_call(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    key = "sk-" + "ant-api03-" + "a1B2" * 10
    prompt = PromptTemplate(
        version="t.v1", system="s.", instructions="i.", slots=(Slot.trusted("note"),)
    ).render(note=Note(note=f"use {key}"))
    provider = FakeProvider([])
    ledger = InMemoryBudgetLedger()

    with pytest.raises(AiInputRejected) as raised:
        _adapter(provider, repo_config, clock, october, ledger).run(
            AiTask.EXPLAIN, org_id="org-1", prompt=prompt, output=Answer
        )

    assert raised.value.pattern == "anthropic_key"
    assert raised.value.source == "message[0]"
    assert provider.calls == []
    assert ledger.spent("org-1", "2026-10") == 0


def test_secret_in_tool_result_is_rejected_before_it_reaches_the_model(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    def leaky(args: SnapshotInput) -> dict[str, object]:
        return {"treasury_id": args.treasury_id, "debug": "ab" * 32}

    provider = FakeProvider(
        [fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"}))]
    )
    tool = Tool(name="get_snapshot", description="d", input_model=SnapshotInput, handler=leaky)

    with pytest.raises(AiInputRejected) as raised:
        _run(_adapter(provider, repo_config, clock, october), AiTask.PLAN, tools=[tool])

    assert raised.value.pattern == "hex_key"
    assert raised.value.source == "tool_result:t1"
    assert len(provider.calls) == 1


def test_bytes32_ids_in_tool_results_reach_the_model(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    request_id = "0x" + "ab" * 32

    def ids(args: SnapshotInput) -> dict[str, object]:
        return {"treasury_id": args.treasury_id, "requestId": request_id}

    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"})),
            fake_text('{"answer": "ok"}'),
        ]
    )
    tool = Tool(name="get_snapshot", description="d", input_model=SnapshotInput, handler=ids)

    _run(_adapter(provider, repo_config, clock, october), AiTask.PLAN, tools=[tool])

    assert request_id in provider.calls[1][0].messages[-1].content[0].content  # type: ignore[union-attr]


def test_injected_scanner_checks_known_secret_values(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    adapter = AiAdapter(
        provider=FakeProvider([]),
        config=repo_config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: october,
        scanner=SecretScanner(known_secrets=["You explain treasury"]),
    )

    with pytest.raises(AiInputRejected) as raised:
        _run(adapter)

    assert raised.value.source == "system"
