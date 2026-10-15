"""Run B0, B1 and N repetitions of B2 over scenarios, with identical state and checks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from treasurypilot_worker.agent import AiAdapter, AiError
from treasurypilot_worker.agent.plan_proposer import (
    PlanProposal,
    PlanProposalRejected,
    propose_plan,
)
from treasurypilot_worker.agent.plan_selection import select_plan
from treasurypilot_worker.planner_bench.arms import (
    DeterministicArms,
    Outcome,
    measure,
    run_deterministic,
)
from treasurypilot_worker.planner_bench.providers import RunScopedProvider
from treasurypilot_worker.planner_bench.scenarios import Scenario, proposal_needed
from treasurypilot_worker.planner_bench.tools import build_tools


class ViolationError(RuntimeError):
    """An arm produced a plan that breaks a policy check; the benchmark fails (BR-052)."""


@dataclass(frozen=True)
class B2Run:
    repetition: int
    outcome: Outcome
    planner_source: str  # AI or DETERMINISTIC (what select_plan chose)
    ai_status: str  # OK, SKIPPED, REJECTED, or the AiError class name
    chosen_reason: str
    provider_calls: int


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    b0: Outcome
    b1: Outcome
    b2: tuple[B2Run, ...]


def run_b2(
    adapter: AiAdapter,
    provider: RunScopedProvider,
    scenario: Scenario,
    arms: DeterministicArms,
    repetition: int,
) -> B2Run:
    position, requests = arms.b1_position, scenario.requests
    proposal: PlanProposal | PlanProposalRejected | None = None
    status, latency, cost, calls = "SKIPPED", 0, 0, 0
    if proposal_needed(scenario):
        provider.begin(scenario.id, repetition)
        try:
            result = propose_plan(
                adapter,
                org_id=f"bench-{scenario.id}-r{repetition}",
                treasury_id=scenario.id,
                eligible_request_ids=[r.id for r in requests],
                tools=build_tools(scenario, position),
            )
        except PlanProposalRejected as error:
            proposal, status = error, "REJECTED"
        except AiError as error:
            status = type(error).__name__
        else:
            proposal, status = result.output, "OK"
            recorded = provider.recorded_latency_ms(scenario.id, repetition)
            latency = result.latency_ms if recorded is None else recorded
            cost, calls = result.cost_usd_micros, result.provider_calls
            provider.finish(latency)
    selection = select_plan(
        arms.b1_schedule, proposal, requests, position.snapshot, scenario.policy, scenario.as_of
    )
    outcome = measure(scenario, position, selection.items, latency_ms=latency, cost_usd_micros=cost)
    return B2Run(
        repetition, outcome, selection.planner_source, status, selection.chosen_reason, calls
    )


def run_scenario(
    adapter: AiAdapter,
    provider: RunScopedProvider,
    scenario: Scenario,
    repetitions: int,
) -> ScenarioResult:
    arms = run_deterministic(scenario)
    runs = tuple(run_b2(adapter, provider, scenario, arms, rep) for rep in range(repetitions))
    return ScenarioResult(scenario, arms.b0, arms.b1, runs)


def run_all(
    adapter: AiAdapter,
    provider: RunScopedProvider,
    scenarios: Sequence[Scenario],
    repetitions: int,
) -> list[ScenarioResult]:
    results = [run_scenario(adapter, provider, s, repetitions) for s in scenarios]
    check_violations(results)
    return results


def check_violations(results: Sequence[ScenarioResult]) -> None:
    """Fail the run unless B1 and B2 have zero violations everywhere (acceptance, BR-052)."""

    bad = [
        f"{r.scenario.id} {arm}={o.violations}"
        for r in results
        for arm, o in (("B1", r.b1), *((f"B2#{run.repetition}", run.outcome) for run in r.b2))
        if o.violations
    ]
    if bad:
        raise ViolationError("policy violations in: " + ", ".join(bad))
