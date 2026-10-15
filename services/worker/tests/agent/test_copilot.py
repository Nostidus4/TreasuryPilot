import json
import uuid
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiToolLimitExceeded,
    FakeClock,
    FakeProvider,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    Tool,
    ToolCall,
    fake_text,
    fake_tool_use,
)
from treasurypilot_worker.agent.call_log import ValidationResult
from treasurypilot_worker.agent.copilot import REFUSAL, PostCheckFailed, ask_copilot
from treasurypilot_worker.agent.tools.backend import ToolBackend
from treasurypilot_worker.agent.tools.read_only import TOOL_NAMES, build_tools
from treasurypilot_worker.agent.types import ProviderRequest

CASES = sorted((Path(__file__).resolve().parents[4] / "evals" / "copilot").glob("cp-*.yaml"))


class _Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _adapter(provider: FakeProvider, config: AiConfig) -> tuple[AiAdapter, InMemoryAiCallLog]:
    clock = FakeClock()
    log = InMemoryAiCallLog()
    adapter = AiAdapter(
        provider=provider,
        config=config,
        ledger=InMemoryBudgetLedger(),
        call_log=log,
        clock=clock,
        sleep=clock.sleep,
    )
    return adapter, log


def _tool(output: object, calls: list[object]) -> Tool[_Empty]:
    def handler(args: _Empty) -> object:
        calls.append(args)
        return output

    return Tool("simulate_schedule", "simulate", _Empty, handler)


def _answer(text: str, *ids: str) -> str:
    return json.dumps(
        {"answer": text, "citations": [{"tool_call_id": i, "path": "$"} for i in ids]}
    )


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_recorded_eval_cases(path: Path, repo_config: AiConfig) -> None:
    case = yaml.safe_load(path.read_text())
    outputs = case["context"]["tool_outputs"]
    numbers = " and ".join(case["expected_numbers"].values())
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "simulate_schedule", {})),
            fake_text(_answer(f"The figures are {numbers}.", "t1")),
        ]
    )
    calls: list[object] = []
    adapter, _ = _adapter(provider, repo_config)

    reply = ask_copilot(
        adapter, org_id="org-1", question=case["question"], tools=[_tool(outputs, calls)]
    )

    assert calls == [_Empty()]
    assert reply.refused is case["must_refuse"]
    assert reply.answer.startswith(REFUSAL) is case["must_refuse"]
    assert all(n in reply.answer for n in case["expected_numbers"].values())


def test_invented_number_fails_post_check(repo_config: AiConfig) -> None:
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "simulate_schedule", {})),
            fake_text(_answer("The shortage is 91,000,000.", "t1")),
        ]
    )
    adapter, _ = _adapter(provider, repo_config)
    with pytest.raises(PostCheckFailed):
        ask_copilot(
            adapter,
            org_id="org-1",
            question="shortage?",
            tools=[_tool({"shortage": "90000000"}, [])],
        )


def test_number_from_uncited_or_unknown_result_fails(repo_config: AiConfig) -> None:
    provider = FakeProvider([fake_text(_answer("It is 5.", "missing"))])
    adapter, _ = _adapter(provider, repo_config)
    with pytest.raises(PostCheckFailed):
        ask_copilot(adapter, org_id="org-1", question="q", tools=[])


def test_comma_grouped_number_matches_tool_result(repo_config: AiConfig) -> None:
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "simulate_schedule", {})),
            fake_text(_answer("Shortage: 90,000,000 base units.", "t1")),
        ]
    )
    adapter, _ = _adapter(provider, repo_config)
    reply = ask_copilot(
        adapter,
        org_id="org-1",
        question="shortage?",
        tools=[_tool({"shortage": "90000000"}, [])],
    )
    assert not reply.refused


def test_pay_request_is_refused_with_approval_pointer(repo_config: AiConfig) -> None:
    provider = FakeProvider([fake_text(_answer("I did not pay anything."))])
    adapter, _ = _adapter(provider, repo_config)
    reply = ask_copilot(adapter, org_id="org-1", question="Pay r1 now.", tools=[])
    assert reply.refused
    assert "approval flow" in reply.answer


def test_tool_loop_stops_after_six_calls(repo_config: AiConfig) -> None:
    steps = [fake_tool_use(ToolCall(f"t{i}", "simulate_schedule", {})) for i in range(7)]
    adapter, _ = _adapter(FakeProvider(steps), repo_config)
    with pytest.raises(AiToolLimitExceeded):
        ask_copilot(adapter, org_id="org-1", question="q", tools=[_tool({}, [])])


def test_only_the_supplied_read_only_tools_are_offered(repo_config: AiConfig) -> None:
    seen: list[ProviderRequest] = []

    def step(request: ProviderRequest, timeout_s: float):  # type: ignore[no-untyped-def]
        seen.append(request)
        return fake_text(_answer("No data."))

    adapter, log = _adapter(FakeProvider([step]), repo_config)
    ask_copilot(adapter, org_id="org-1", question="q", tools=[_tool({}, [])])
    assert [t.name for t in seen[0].tools] == ["simulate_schedule"]
    assert log.entries[0].purpose == "COPILOT"


def _plain(question: str, config: AiConfig) -> bool:
    adapter, _ = _adapter(FakeProvider([fake_text(_answer("Nothing to report."))]), config)
    return ask_copilot(adapter, org_id="org-1", question=question, tools=[]).refused


@pytest.mark.parametrize(
    "question",
    [
        "Would you pay r1 today?",
        "Could you pay the Acme invoice?",
        "Can you pay r1?",
        "I want you to pay r1.",
        "Make a payment to Acme.",
        "Settle the invoice now.",
        "Please schedule the transfer for Friday.",
        "Top up the buffer safe.",
        "Withdraw 500 from the treasury.",
        "Go ahead: pay r1",
    ],
)
def test_execution_phrasings_are_refused(question: str, repo_config: AiConfig) -> None:
    assert _plain(question, repo_config)


def test_hypothetical_pay_later_is_not_refused(repo_config: AiConfig) -> None:
    assert not _plain("What if we pay later?", repo_config)


def test_refused_question_with_bad_numbers_returns_refusal_alone(repo_config: AiConfig) -> None:
    provider = FakeProvider([fake_text(_answer("Paid 777.", "missing"))])
    adapter, log = _adapter(provider, repo_config)
    reply = ask_copilot(adapter, org_id="org-1", question="Pay r1 now.", tools=[])
    assert (reply.answer, reply.citations, reply.refused) == (REFUSAL, (), True)
    assert reply.ai_call_id and len(log.entries) == 1


def test_post_check_failure_is_logged_as_postcheck_failed(repo_config: AiConfig) -> None:
    provider = FakeProvider([fake_text(_answer("It is 5.", "missing"))])
    adapter, log = _adapter(provider, repo_config)
    with pytest.raises(PostCheckFailed) as caught:
        ask_copilot(adapter, org_id="org-1", question="q", tools=[])
    assert len(log.entries) == 1
    assert log.entries[0].validation_result is ValidationResult.POSTCHECK_FAILED
    assert caught.value.ai_call_id


def test_sign_is_respected(repo_config: AiConfig) -> None:
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "simulate_schedule", {})),
            fake_text(_answer("Net flow is -100.", "t1")),
        ]
    )
    adapter, _ = _adapter(provider, repo_config)
    with pytest.raises(PostCheckFailed):
        ask_copilot(adapter, org_id="org-1", question="q", tools=[_tool({"net": "100"}, [])])


def test_negative_eval_wrong_number_in_answer(repo_config: AiConfig) -> None:
    case = yaml.safe_load(CASES[0].read_text())
    outputs = case["context"]["tool_outputs"]
    provider = FakeProvider(
        [
            fake_tool_use(ToolCall("t1", "simulate_schedule", {})),
            fake_text(_answer("The figure is 123456789123.", "t1")),
        ]
    )
    adapter, log = _adapter(provider, repo_config)
    with pytest.raises(PostCheckFailed):
        ask_copilot(adapter, org_id="org-1", question=case["question"], tools=[_tool(outputs, [])])
    assert log.entries[0].validation_result is ValidationResult.POSTCHECK_FAILED


def test_turn_uses_only_read_only_tools_and_backend_reads(repo_config: AiConfig) -> None:
    org, treasury = uuid.uuid4(), uuid.uuid4()
    called: list[str] = []

    class Backend:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            def method(*args: object) -> object:
                called.append(name)
                return True if name == "treasury_in_org" else None

            return method

    seen: list[ProviderRequest] = []

    def step(request: ProviderRequest, timeout_s: float):  # type: ignore[no-untyped-def]
        seen.append(request)
        return fake_tool_use(ToolCall("t1", "get_snapshot", {"treasury_id": str(treasury)}))

    provider = FakeProvider([step, fake_text(_answer("No snapshot."))])
    adapter, _ = _adapter(provider, repo_config)
    tools = build_tools(Backend(), str(org))  # type: ignore[arg-type]
    ask_copilot(adapter, org_id=str(org), question="q", tools=tools)

    reads = {n for n in vars(ToolBackend) if not n.startswith("_")}
    assert {t.name for t in seen[0].tools} <= set(TOOL_NAMES)
    assert called and set(called) <= reads  # the backend type has no write method at all
    assert not any(w in n for n in reads for w in ("insert", "update", "delete", "write", "add"))
