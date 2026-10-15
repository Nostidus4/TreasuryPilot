"""Planner benchmark (AGT-014): arms, ground-truth isolation, record/replay, report, failure."""

import csv
import dataclasses
import io
import json
from pathlib import Path

import pytest

from treasurypilot_worker.agent import (
    AiAdapter,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    load_ai_config,
)
from treasurypilot_worker.agent.errors import AiTimeout
from treasurypilot_worker.agent.types import ProviderRequest, ProviderResponse, ToolResult
from treasurypilot_worker.planner_bench import cli
from treasurypilot_worker.planner_bench.arms import run_deterministic
from treasurypilot_worker.planner_bench.providers import (
    EdfStandInProvider,
    RecordedProvider,
    RecordingError,
    RecordingProvider,
)
from treasurypilot_worker.planner_bench.report import (
    CSV_FIELDS,
    RunInfo,
    render_csv,
    render_markdown,
    worse_cases,
)
from treasurypilot_worker.planner_bench.runner import (
    B2Run,
    ScenarioResult,
    ViolationError,
    check_violations,
    run_all,
)
from treasurypilot_worker.planner_bench.scenarios import Scenario, load_scenarios

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIOS = REPO_ROOT / "evals" / "scenarios"
REPS = 2


@pytest.fixture(scope="module")
def scenarios() -> list[Scenario]:
    return load_scenarios(SCENARIOS)


def _adapter(provider: object) -> AiAdapter:
    return AiAdapter(
        provider=provider,  # type: ignore[arg-type]
        config=load_ai_config(REPO_ROOT / "config" / "ai.yaml"),
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )


def _run(scenarios: list[Scenario], provider: object = None) -> list[ScenarioResult]:
    provider = provider or EdfStandInProvider()
    return run_all(_adapter(provider), provider, scenarios, REPS)  # type: ignore[arg-type]


def test_loads_every_dev_and_heldout_scenario(scenarios: list[Scenario]) -> None:
    assert len(scenarios) == 40
    assert sum(s.split == "dev" for s in scenarios) == 28
    assert sum(s.split == "heldout" for s in scenarios) == 12
    assert len(load_scenarios(SCENARIOS, "heldout")) == 12


def test_engine_reproduces_the_authored_reference(scenarios: list[Scenario]) -> None:
    """The mapping to engine inputs is faithful: B0 and the liquidity action match the labels."""

    for s in scenarios:
        arms = run_deterministic(s)
        reference = s.ground_truth["expected_b0"]
        assert arms.b0.value_saved == int(reference["value"]), s.id
        assert arms.b0.tx_count == reference["transaction_count"], s.id
        expected = s.ground_truth.get("expected_liquidity")
        if expected is not None:
            assert arms.b1.liquidity_action == expected["kind"], s.id


def test_three_arms_on_all_scenarios_with_zero_violations(scenarios: list[Scenario]) -> None:
    results = _run(scenarios)
    assert len(results) == 40
    assert all(r.b1.violations == 0 and r.b0.violations == 0 for r in results)
    assert all(len(r.b2) == REPS for r in results)
    assert all(run.outcome.violations == 0 for r in results for run in r.b2)
    by_id = {r.scenario.id: r for r in results}
    # B1's liquidity action fixes the new-obligation shortfall that idle cash (B0) leaves.
    assert by_id["sc-109"].b0.reserve_breaches == 1
    assert by_id["sc-109"].b1.reserve_breaches == 0
    assert by_id["sc-109"].b1.missed_deadlines < by_id["sc-109"].b0.missed_deadlines
    # B2 is B1 plus a checked proposal, so it never loses to B1 on an outcome metric.
    assert worse_cases(results) == []


def test_trigger_rule_skips_the_model_for_a_single_plain_request(
    scenarios: list[Scenario],
) -> None:
    results = {r.scenario.id: r for r in _run(scenarios)}
    assert {x.ai_status for x in results["sc-002"].b2} == {"SKIPPED"}
    assert {x.ai_status for x in results["sc-021"].b2} == {"OK"}


class _Spy(EdfStandInProvider):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        self.seen.append(repr(request.system) + repr(request.messages))
        return super().complete(request, timeout_s=timeout_s)


def test_ground_truth_never_reaches_a_prompt_or_tool_result(scenarios: list[Scenario]) -> None:
    spy = _Spy()
    _run(scenarios, spy)
    assert spy.seen
    text = "\n".join(spy.seen)
    for forbidden in (
        "expected",
        "explanation",
        "review_status",
        "authoring_exposure",
        "Independent enumeration",
    ):
        assert forbidden not in text
    for s in scenarios:  # no label string of any scenario appears either
        for label in s.ground_truth.values():
            assert json.dumps(label.get("explanation", "")) not in text


def test_violation_fails_the_run(scenarios: list[Scenario]) -> None:
    results = _run(scenarios[:3])
    bad = dataclasses.replace(results[0].b1, violations=1)
    with pytest.raises(ViolationError, match="sc-001 B1=1"):
        check_violations([dataclasses.replace(results[0], b1=bad)])
    run = results[0].b2[0]
    worse_run = dataclasses.replace(run, outcome=dataclasses.replace(run.outcome, violations=2))
    with pytest.raises(ViolationError, match="B2#0=2"):
        check_violations([dataclasses.replace(results[0], b2=(worse_run,))])


def test_report_has_three_arms_csv_and_lists_worse_cases(scenarios: list[Scenario]) -> None:
    results = _run(scenarios)
    info = RunInfo("stand-in", "none", "plan.v1", REPS, stand_in=True)
    report = render_markdown(results, info)
    assert "B0 manual/EDF, idle cash | B1 deterministic | B2 AI + checks" in report
    assert "## Scenarios where B2 is worse" in report
    assert "not a model result" in report
    assert "None. In all 40 scenarios" in report
    rows = list(csv.DictReader(io.StringIO(render_csv(results))))
    assert tuple(rows[0]) == CSV_FIELDS
    assert len(rows) == 40 * 2 + 40 * REPS
    assert {r["arm"] for r in rows} == {"B0", "B1", "B2"}

    # A B2 repetition that loses to B1 is listed with the metrics it loses on.
    target = results[20]
    run = target.b2[0]
    lost = dataclasses.replace(run.outcome, value_saved=run.outcome.value_saved - 5, tx_count=9)
    results[20] = dataclasses.replace(
        target, b2=(dataclasses.replace(run, outcome=lost), *target.b2[1:])
    )
    worse = render_markdown(results, info)
    assert f"- {target.scenario.id} repetition 0: worse on" in worse
    assert "value saved" in worse and "transactions" in worse
    assert "None. In all" not in worse


class _ReverseOrder(EdfStandInProvider):
    """Proposes the opposite of EDF so select_plan has something it must not trust blindly."""

    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        response = super().complete(request, timeout_s=timeout_s)
        if response.text is None:
            return response
        data = json.loads(response.text)
        data["request_order"] = list(reversed(data["request_order"]))
        return dataclasses.replace(response, text=json.dumps(data))


def test_a_worse_ai_order_never_makes_b2_worse(scenarios: list[Scenario]) -> None:
    results = _run(scenarios, _ReverseOrder())
    assert worse_cases(results) == []
    assert all(r.outcome.violations == 0 for res in results for r in res.b2)


class _Timeout(EdfStandInProvider):
    def complete(self, request: ProviderRequest, *, timeout_s: float) -> ProviderResponse:
        raise AiTimeout("slow")


def test_model_failure_falls_back_to_b1(scenarios: list[Scenario]) -> None:
    results = _run(scenarios[20:24], _Timeout())
    for r in results:
        for run in r.b2:
            assert run.planner_source == "DETERMINISTIC"
            assert run.outcome.worse_than(r.b1) == []
    assert {x.ai_status for r in results for x in r.b2} == {"AiTimeout"}


def _b2_view(results: list[ScenarioResult]) -> list[tuple[str, int, str, str, object]]:
    return [
        (r.scenario.id, x.repetition, x.ai_status, x.planner_source, x.outcome)
        for r in results
        for x in r.b2
    ]


def test_record_then_replay_reproduces_b2(scenarios: list[Scenario], tmp_path: Path) -> None:
    subset = scenarios[18:26]
    recorder = RecordingProvider(EdfStandInProvider())
    live = run_all(_adapter(recorder), recorder, subset, REPS)
    recorder.write(tmp_path, subset, model="test-model", recorded_at="2026-10-16")

    replay = RecordedProvider(tmp_path, subset, REPS)
    again = run_all(_adapter(replay), replay, subset, REPS)
    assert _b2_view(again) == _b2_view(live)
    assert replay.models == {"test-model"}


def test_recording_is_refused_when_stale(scenarios: list[Scenario], tmp_path: Path) -> None:
    subset = scenarios[20:22]
    recorder = RecordingProvider(EdfStandInProvider())
    run_all(_adapter(recorder), recorder, subset, REPS)
    recorder.write(tmp_path, subset, model="m", recorded_at="2026-10-16")

    with pytest.raises(RecordingError, match="no recording"):
        RecordedProvider(tmp_path, scenarios[20:24], REPS)
    with pytest.raises(RecordingError, match="no repetition"):
        RecordedProvider(tmp_path, subset, REPS + 1)
    changed = [dataclasses.replace(subset[0], inputs_sha256="0" * 64), subset[1]]
    with pytest.raises(RecordingError, match="different inputs"):
        RecordedProvider(tmp_path, changed, REPS)
    path = tmp_path / f"{subset[0].id}.json"
    data = json.loads(path.read_text())
    data["prompt_version"] = "plan.v0"
    path.write_text(json.dumps(data))
    with pytest.raises(RecordingError, match="re-record"):
        RecordedProvider(tmp_path, subset, REPS)


def test_recorded_provider_replays_a_timeout(scenarios: list[Scenario], tmp_path: Path) -> None:
    subset = scenarios[20:21]
    recorder = RecordingProvider(_Timeout())
    first = run_all(_adapter(recorder), recorder, subset, 1)
    recorder.write(tmp_path, subset, model="m", recorded_at="2026-10-16")
    replay = RecordedProvider(tmp_path, subset, 1)
    assert _b2_view(run_all(_adapter(replay), replay, subset, 1)) == _b2_view(first)


def test_cli_stand_in_writes_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--mode", "stand-in", "--repetitions", "1", "--out", str(tmp_path)])
    assert code == 0
    assert "B0" in (tmp_path / "planner-benchmark.md").read_text()
    assert (tmp_path / "planner-benchmark.csv").read_text().startswith("scenario,")
    capsys.readouterr()


def test_cli_recorded_without_recordings_exits_2(tmp_path: Path) -> None:
    code = cli.main(
        ["--mode", "recorded", "--recordings", str(tmp_path / "none"), "--out", str(tmp_path)]
    )
    assert code == 2


def test_cli_exits_non_zero_on_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object) -> list[ScenarioResult]:
        raise ViolationError("policy violations in: sc-001 B1=1")

    monkeypatch.setattr(cli, "run_all", boom)
    assert cli.main(["--mode", "stand-in", "--out", str(tmp_path)]) == 1
    assert not (tmp_path / "planner-benchmark.md").exists()


def test_cli_record_needs_live_mode() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--mode", "recorded", "--record"])


def test_b2run_and_results_are_plain_values() -> None:
    assert dataclasses.is_dataclass(B2Run) and dataclasses.is_dataclass(ScenarioResult)
    assert ToolResult  # the stand-in reads tool results, imported to keep the contract visible
